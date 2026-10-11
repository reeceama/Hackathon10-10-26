"""Sentence embeddings for search: all-MiniLM-L6-v2, run directly with ONNX Runtime.

The same vectors as the PyTorch and fastembed versions (they agree to within 1e-6), with the
memory kept low: passages are embedded a few at a time, and ONNX Runtime's scratch arena is
off, so working memory is returned after each batch. Works on macOS, Windows and Linux.
"""

import os
import pickle
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List

import numpy as np

MODEL = "Qdrant/all-MiniLM-L6-v2-onnx"  # the ONNX export of sentence-transformers/all-MiniLM-L6-v2
MAX_TOKENS = 256  # all-MiniLM-L6-v2's limit; longer passages are truncated, as in sentence-transformers
BATCH = 8         # larger batches are no faster on a CPU but use several times the memory
IDLE_SECONDS = 600  # unload the model after this long unused; it reloads in a second or two


FILES = ["model.onnx", "tokenizer.json"]


def model_folder() -> Path:

    """
    Downloaded once into Referee's own folder, not the system's temporary one. Once saved, the
    files are opened directly, without loading the download library (~25 MB).
    """

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Referee"
    else:
        base = Path.home() / ".referee"
    cache = base / "models"
    for snapshot in sorted((cache / f"models--{MODEL.replace('/', '--')}" / "snapshots").glob("*")):
        if all((snapshot / name).exists() for name in FILES):
            return snapshot
    from huggingface_hub import snapshot_download  # first run only
    return Path(snapshot_download(MODEL, cache_dir=cache, allow_patterns=FILES))


class Embedder:

    def __init__(self):

        import onnxruntime as ort  # only in the model process
        from tokenizers import Tokenizer

        folder = model_folder()
        self.tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))
        self.tokenizer.enable_truncation(MAX_TOKENS)
        self.tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.enable_cpu_mem_arena = False
        options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(folder / "model.onnx"), options, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}

    def embed(self, texts: List[str]) -> np.ndarray:

        """
        Normalised vectors, one row per text: the mean of the token vectors, as sentence-transformers does.
        """

        rows = []
        for start in range(0, len(texts), BATCH):
            encoded = self.tokenizer.encode_batch(texts[start:start + BATCH])
            ids = np.array([e.ids for e in encoded], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feeds["token_type_ids"] = np.zeros_like(ids)
            tokens = self.session.run(None, feeds)[0]
            pooled = (tokens * mask[..., None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
            rows.append(pooled / np.linalg.norm(pooled, axis=1, keepdims=True))
        return np.vstack(rows).astype(np.float32) if rows else np.zeros((0, 384), dtype=np.float32)


def send(stream, value):

    data = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(struct.pack("<Q", len(data)) + data)
    stream.flush()


def receive(stream):

    header = stream.read(8)
    if len(header) < 8:
        raise EOFError("the model process stopped")
    return pickle.loads(stream.read(struct.unpack("<Q", header)[0]))


def serve():

    """
    The model's own process (python embeddings.py --serve): embeds each list of texts that
    arrives on stdin and replies on stdout, until stdin closes.
    """

    embedder = Embedder()
    while True:
        try:
            texts = receive(sys.stdin.buffer)
        except EOFError:
            return
        send(sys.stdout.buffer, embedder.embed(texts))


class LazyEmbedder:

    """
    Runs the model in a separate process, started when first needed and stopped after
    IDLE_SECONDS without use. ONNX Runtime keeps its memory for the life of a process, so
    stopping the process is the only way to give the ~150 MB back while Referee sits idle.
    Checks and captures run in the background, so the second or two to restart isn't something
    anyone waits on.
    """

    def __init__(self):

        self.process = None
        self.last_used = 0.0
        self.lock = threading.Lock()
        threading.Thread(target=self.stop_when_idle, daemon=True).start()

    def start(self):

        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, creationflags=flags)

    def stop(self):

        try:
            self.process.stdin.close()
            self.process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
        self.process = None

    def embed(self, texts: List[str]) -> np.ndarray:

        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self.start()
            self.last_used = time.time()
            send(self.process.stdin, list(texts))
            return receive(self.process.stdout)

    def stop_when_idle(self):

        while True:
            time.sleep(60)
            with self.lock:
                if self.process is not None and time.time() - self.last_used > IDLE_SECONDS:
                    self.stop()


_embedder = LazyEmbedder()


def embed(texts: List[str]) -> np.ndarray:
    """Turn a list of texts into normalised vectors (one row per text)."""
    return _embedder.embed(texts)


if __name__ == "__main__" and "--serve" in sys.argv:
    serve()
