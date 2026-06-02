from functools import lru_cache

from utils.config import get_settings
from vector.qdrant_store import QdrantVectorStore


@lru_cache
def build_vector_store() -> QdrantVectorStore | None:
    current = get_settings()
    if not current.uses_qdrant():
        return None
    return QdrantVectorStore(current)
