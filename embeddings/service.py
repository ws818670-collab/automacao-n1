import logging
import math
import re
from hashlib import sha256
from time import perf_counter

import numpy as np

from openai import OpenAI

from exceptions import ConfigurationError, EmbeddingError
from utils.retry import external_retry
from utils.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class EmbeddingService:
    def __init__(self) -> None:
        provider = self._get_provider()
        self._use_local = provider == "local"
        self._client = OpenAI(api_key=settings.openai_api_key_value()) if not self._use_local else None
        if self._use_local:
            from sentence_transformers import SentenceTransformer
            self._local_model = SentenceTransformer(settings.local_embedding_model)
        else:
            self._local_model = None

    def embed(self, text: str) -> list[float]:
        if not text.strip():
            return [0.0] * settings.embedding_dimension

        started_at = perf_counter()
        if self._use_local:
            vector = self._local_embed(text)
            logger.info(
                "embedding_generated",
                extra={"provider": "local", "dimension": len(vector), "duration_ms": round((perf_counter() - started_at) * 1000, 2)},
            )
            return vector

        try:
            vector = self._openai_embed(text)
        except Exception as exc:
            raise EmbeddingError("Falha ao gerar embedding com OpenAI") from exc
        logger.info(
            "embedding_generated",
            extra={"provider": "openai", "dimension": len(vector), "duration_ms": round((perf_counter() - started_at) * 1000, 2)},
        )
        return vector

    def _get_provider(self) -> str:
        current = get_settings()
        if current.embedding_provider == "openai" and not current.openai_api_key_value():
            raise ConfigurationError("OPENAI_API_KEY obrigatoria quando EMBEDDING_PROVIDER=openai")
        return current.embedding_provider

    @external_retry()
    def _openai_embed(self, text: str) -> list[float]:
        response = self._client.embeddings.create(
            model=settings.embedding_model,
            input=text,
        )
        return response.data[0].embedding

    def _local_embed(self, text: str) -> list[float]:
        if self._local_model is None:
            return self._fallback_embed(text)

        vector = self._local_model.encode(text, normalize_embeddings=True, show_progress_bar=False)
        adapted = _adapt_vector_dimension(np.asarray(vector, dtype=np.float32), settings.embedding_dimension)
        return adapted.tolist()

    def _fallback_embed(self, text: str) -> list[float]:
        # Fallback lexical deterministico para desenvolvimento local; nao usar em producao.
        dimension = settings.embedding_dimension
        vector = [0.0] * dimension
        tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())

        if not tokens:
            return vector

        for token in tokens:
            digest = sha256(token.encode("utf-8")).digest()
            idx_a = int.from_bytes(digest[0:4], "little") % dimension
            idx_b = int.from_bytes(digest[4:8], "little") % dimension
            sign = 1.0 if digest[8] % 2 == 0 else -1.0
            weight = 1.0 + min(len(token), 20) / 20.0
            vector[idx_a] += sign * weight
            vector[idx_b] += (sign * 0.5)

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector

        return [v / norm for v in vector]


def _adapt_vector_dimension(vector: np.ndarray, target_dimension: int) -> np.ndarray:
    current_dimension = int(vector.shape[0])
    if current_dimension == target_dimension:
        return vector

    # Deterministic projection so stored vectors remain comparable in pgvector.
    projection = np.zeros(target_dimension, dtype=np.float32)
    for index, value in enumerate(vector):
        digest = sha256(f"proj:{index}".encode("utf-8")).digest()
        dest_a = int.from_bytes(digest[0:4], "little") % target_dimension
        dest_b = int.from_bytes(digest[4:8], "little") % target_dimension
        sign = 1.0 if digest[8] % 2 == 0 else -1.0
        projection[dest_a] += float(value) * sign
        projection[dest_b] += float(value) * (sign * 0.5)

    norm = float(np.linalg.norm(projection))
    if norm == 0.0:
        return projection
    return projection / norm
