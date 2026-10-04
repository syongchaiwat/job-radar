"""Local sentence embeddings of role cards.

Role cards are English by construction, so an English model is enough.
Loaded lazily once per process (~1.3 GB RAM, a few seconds); vectors are
L2-normalized float32, so cosine similarity is a dot product.
"""
import hashlib
from functools import lru_cache

import numpy as np

EMBED_MODEL = "BAAI/bge-large-en-v1.5"


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBED_MODEL)


def embed_texts(texts: list[str]) -> np.ndarray:
    return _model().encode(texts, normalize_embeddings=True, convert_to_numpy=True).astype(np.float32)


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def to_bytes(vec: np.ndarray) -> bytes:
    return vec.astype(np.float32).tobytes()


def from_bytes(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)
