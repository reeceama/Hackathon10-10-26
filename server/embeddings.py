from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer

_model = SentenceTransformer("all-MiniLM-L6-v2")


def embed(texts: List[str]) -> np.ndarray:
    """Turn a list of texts into normalised vectors (one row per text)."""
    return _model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)