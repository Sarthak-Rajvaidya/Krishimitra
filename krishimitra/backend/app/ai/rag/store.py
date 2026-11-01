import math
import uuid
from dataclasses import dataclass
from typing import Protocol

from app.core.config import get_settings


@dataclass
class Hit:
    score: float
    payload: dict


class VectorStore(Protocol):
    def upsert(self, points: list[tuple[str, list[float], dict]]) -> None: ...
    def search(self, vector: list[float], limit: int) -> list[Hit]: ...
    def delete_document(self, document_id: int) -> None: ...
    def health(self) -> dict: ...


class MemoryStore:
    """Cosine-similarity store for tests and offline demos."""
    def __init__(self):
        self.points: dict[str, tuple[list[float], dict]] = {}

    def upsert(self, points):
        for pid, vec, payload in points:
            self.points[pid] = (vec, payload)

    def search(self, vector, limit):
        def cos(a, b):
            d = sum(x * y for x, y in zip(a, b))
            return d / ((math.sqrt(sum(x * x for x in a)) or 1) * (math.sqrt(sum(y * y for y in b)) or 1))
        hits = [Hit(cos(vector, v), p) for v, p in self.points.values()]
        return sorted(hits, key=lambda h: h.score, reverse=True)[:limit]

    def delete_document(self, document_id):
        self.points = {k: v for k, v in self.points.items() if v[1].get("document_id") != document_id}

    def health(self):
        return {"ok": True, "backend": "memory", "points": len(self.points)}


class QdrantStore:
    def __init__(self, url: str, collection: str, dim: int):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
        self.c = QdrantClient(url=url, timeout=10)
        self.collection = collection
        if not self.c.collection_exists(collection):
            self.c.create_collection(collection, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))

    def upsert(self, points):
        from qdrant_client.models import PointStruct
        self.c.upsert(self.collection, points=[PointStruct(id=pid, vector=vec, payload=pl) for pid, vec, pl in points])

    def search(self, vector, limit):
        res = self.c.query_points(self.collection, query=vector, limit=limit, with_payload=True)
        return [Hit(p.score, p.payload or {}) for p in res.points]

    def delete_document(self, document_id):
        from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue
        self.c.delete(self.collection, points_selector=FilterSelector(
            filter=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))])))

    def health(self):
        try:
            n = self.c.count(self.collection).count
            return {"ok": True, "backend": "qdrant", "points": n}
        except Exception as ex:
            return {"ok": False, "backend": "qdrant", "error": type(ex).__name__}


_store: VectorStore | None = None


def get_store() -> VectorStore:
    global _store
    if _store is None:
        s = get_settings()
        _store = QdrantStore(s.qdrant_url, s.qdrant_collection, s.embedding_dim)
    return _store


def set_store(st: VectorStore | None) -> None:
    global _store
    _store = st


def new_point_id() -> str:
    return str(uuid.uuid4())
