import json
import os
import threading
from typing import Dict, List, Optional

import numpy as np

from embeddings import embed

DATA_FILE = "store.json"
VECTOR_FILE = "store.npy"

_passages: List[Dict] = []          # {"text": ..., "source": {...}}
_vectors: Optional[np.ndarray] = None
_seen_urls = set()
_lock = threading.Lock()


def add_page(metadata: Dict, passages: List[str]) -> int:
    """Store a page's passages. Returns how many were added (0 if already captured)."""
    global _vectors
    url = metadata.get("url")
    if url in _seen_urls:
        return 0

    new_vectors = embed(passages)
    with _lock:
        _passages.extend({"text": p, "source": metadata} for p in passages)
        _vectors = new_vectors if _vectors is None else np.vstack([_vectors, new_vectors])
        _seen_urls.add(url)
        _save()
    return len(passages)


def search(sentence: str, k: int = 3) -> List[Dict]:
    """Return the k stored passages closest in meaning to the sentence."""
    if _vectors is None:
        return []
    query = embed([sentence])[0]
    scores = _vectors @ query
    top = np.argsort(scores)[::-1][:k]
    return [{**_passages[i], "score": float(scores[i])} for i in top]


def clear() -> None:
    global _vectors
    with _lock:
        _passages.clear()
        _seen_urls.clear()
        _vectors = None
        for f in (DATA_FILE, VECTOR_FILE):
            if os.path.exists(f):
                os.remove(f)


def _save() -> None:
    if _vectors is None:
        return
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(_passages, f)
    np.save(VECTOR_FILE, _vectors)


def _load() -> None:
    global _vectors
    if os.path.exists(DATA_FILE) and os.path.exists(VECTOR_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            _passages.extend(json.load(f))
        _vectors = np.load(VECTOR_FILE)
        _seen_urls.update(p["source"].get("url") for p in _passages)


_load()