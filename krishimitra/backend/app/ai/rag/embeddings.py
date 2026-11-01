"""Embedders. 'hash' is a deterministic offline bag-of-words embedder for tests/dev (not semantic).
Production should use sentence-transformers (multilingual, supports Marathi/English)."""
import hashlib
import math
import re
from typing import Protocol

from app.core.config import get_settings


class Embedder(Protocol):
    dim: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for w in re.findall(r"\w+", t.lower()):
                h = int(hashlib.md5(w.encode()).hexdigest(), 16)
                v[h % self.dim] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class STEmbedder:
    def __init__(self, model: str):
        from sentence_transformers import SentenceTransformer
        self.m = SentenceTransformer(model)
        self.dim = self.m.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.m.encode(texts, normalize_embeddings=True).tolist()


_emb: Embedder | None = None


def get_embedder() -> Embedder:
    global _emb
    if _emb is None:
        s = get_settings()
        _emb = HashEmbedder(s.embedding_dim) if s.embedding_backend == "hash" else STEmbedder(s.embedding_model)
    return _emb


def set_embedder(e: Embedder | None) -> None:
    global _emb
    _emb = e
