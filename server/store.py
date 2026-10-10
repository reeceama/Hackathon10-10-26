import json
import os
import threading
from typing import Dict, List, Optional

import numpy as np

from embeddings import embed
from keywords import KeywordIndex

DATA_FILE = "store.json"
VECTOR_FILE = "store.npy"

_passages: List[Dict] = []          # {"text": ..., "source": {...}}
_vectors: Optional[np.ndarray] = None
_seen_urls = set()
_lock = threading.Lock()
_keywords = KeywordIndex()

CANDIDATES = 20  # how many passages each search method puts forward before combining
RRF_K = 60       # reciprocal rank fusion constant (the usual default)


def add_page(metadata: Dict, passages: List[str], pages: Optional[List[int]] = None,
             times: Optional[List[int]] = None) -> int:
    """Store a page's passages. Returns how many were added (0 if already captured).

    pages: for PDFs, the page each passage starts on, so citations can give page numbers.
    times: for videos, the second each passage starts at, so citations can give timestamps.
    """
    global _vectors
    url = metadata.get("url")
    if url in _seen_urls:
        return 0

    new_vectors = embed(passages)
    with _lock:
        for i, text in enumerate(passages):
            passage = {"text": text, "source": metadata}
            if pages:
                passage["page"] = pages[i]
            if times:
                passage["time"] = times[i]
            _passages.append(passage)
        _keywords.add(passages)
        _vectors = new_vectors if _vectors is None else np.vstack([_vectors, new_vectors])
        _seen_urls.add(url)
        _save()
    return len(passages)


def search(sentence: str, k: int = 3, project: Optional[str] = None) -> List[Dict]:
    """Return the k stored passages that best match the sentence.

    project: only use reading captured for that project (plus reading with no project).

    Combines meaning (embeddings) with keywords (BM25) by reciprocal rank fusion, so a
    passage ranked well by either method is put forward. "score" stays the cosine
    similarity, which is what the caller's minimum-similarity filter expects.
    """
    if _vectors is None:
        return []
    query = embed([sentence])[0]
    cosine = _vectors @ query
    if project:
        outside = [i for i, p in enumerate(_passages) if p["source"].get("project") not in (None, "", project)]
        cosine[outside] = -np.inf
    by_meaning = [i for i in np.argsort(cosine)[::-1][:CANDIDATES] if np.isfinite(cosine[i])]
    keyword_scores = {i: v for i, v in _keywords.scores(sentence).items() if np.isfinite(cosine[i])}
    by_keywords = sorted(keyword_scores, key=keyword_scores.get, reverse=True)[:CANDIDATES]

    fused: Dict[int, float] = {}
    for ranking in (by_meaning, by_keywords):
        for rank, i in enumerate(ranking):
            fused[int(i)] = fused.get(int(i), 0.0) + 1 / (RRF_K + rank + 1)
    top = sorted(fused, key=fused.get, reverse=True)[:k]
    return [{**_passages[i], "score": float(cosine[i])} for i in top]


def sources() -> List[Dict]:
    """One entry per captured page or PDF: its metadata and how many passages it gave."""
    found: Dict[str, Dict] = {}
    for p in _passages:
        url = p["source"].get("url")
        entry = found.setdefault(url, {**p["source"], "passages": 0})
        entry["passages"] += 1
    return list(found.values())


def forget(url: str) -> int:
    """Remove one source's passages. Returns how many were removed."""
    global _vectors
    with _lock:
        keep = [i for i, p in enumerate(_passages) if p["source"].get("url") != url]
        removed = len(_passages) - len(keep)
        if removed == 0:
            return 0
        if not keep:
            _vectors = None
        else:
            _vectors = _vectors[keep]
        kept = [_passages[i] for i in keep]
        _passages.clear()
        _passages.extend(kept)
        _seen_urls.discard(url)
        _keywords.clear()
        _keywords.add([p["text"] for p in _passages])
        if _vectors is None:
            for f in (DATA_FILE, VECTOR_FILE):
                if os.path.exists(f):
                    os.remove(f)
        else:
            _save()
    return removed


def clear() -> None:
    global _vectors
    with _lock:
        _passages.clear()
        _seen_urls.clear()
        _keywords.clear()
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
        _keywords.add([p["text"] for p in _passages])
        _vectors = np.load(VECTOR_FILE)
        _seen_urls.update(p["source"].get("url") for p in _passages)


_load()