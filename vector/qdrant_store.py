import logging
from time import perf_counter

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from exceptions import RetrievalError
from utils.config import Settings, get_settings

logger = logging.getLogger(__name__)


class QdrantVectorStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._collection = self._settings.qdrant_collection.strip() or "jira_ticket_embeddings"
        self._client = QdrantClient(
            url=self._settings.qdrant_url.strip(),
            api_key=self._settings.qdrant_api_key_value(),
        )
        self._ensure_collection()
        self._ensure_payload_indexes()

    _FILTER_PAYLOAD_INDEXES: tuple[str, ...] = ("status", "chave_jira")

    @property
    def collection_name(self) -> str:
        return self._collection

    def _ensure_collection(self) -> None:
        if self._client.collection_exists(self._collection):
            return

        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=VectorParams(
                size=self._settings.embedding_dimension,
                distance=Distance.COSINE,
            ),
        )
        logger.info(
            "qdrant_collection_created",
            extra={"collection": self._collection, "dimension": self._settings.embedding_dimension},
        )

    def _ensure_payload_indexes(self) -> None:
        for field_name in self._FILTER_PAYLOAD_INDEXES:
            try:
                self._client.create_payload_index(
                    collection_name=self._collection,
                    field_name=field_name,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
                logger.info(
                    "qdrant_payload_index_created",
                    extra={"collection": self._collection, "field": field_name},
                )
            except Exception as exc:
                message = str(exc).lower()
                if "already exists" in message or "already exist" in message:
                    continue
                logger.warning(
                    "qdrant_payload_index_skipped",
                    extra={"collection": self._collection, "field": field_name, "reason": str(exc)[:200]},
                )

    def upsert(
        self,
        *,
        ticket_id: int,
        chave_jira: str,
        vector: list[float],
        status: str,
        produto: str,
    ) -> None:
        started_at = perf_counter()
        point = PointStruct(
            id=ticket_id,
            vector=vector,
            payload={
                "ticket_id": ticket_id,
                "chave_jira": chave_jira,
                "status": status or "",
                "produto": produto or "",
            },
        )
        try:
            self._client.upsert(collection_name=self._collection, points=[point], wait=True)
        except Exception as exc:
            raise RetrievalError(f"Falha ao salvar embedding no Qdrant ({chave_jira})") from exc

        logger.info(
            "qdrant_upsert_completed",
            extra={
                "chave_jira": chave_jira,
                "ticket_id": ticket_id,
                "collection": self._collection,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )

    def search(
        self,
        vector: list[float],
        *,
        top_k: int = 5,
        exclude_ticket_key: str | None = None,
        allowed_statuses: list[str] | None = None,
    ) -> list[tuple[int, float]]:
        query_filter = _build_search_filter(exclude_ticket_key, allowed_statuses)
        try:
            response = self._client.query_points(
                collection_name=self._collection,
                query=vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=False,
            )
        except Exception as exc:
            raise RetrievalError("Falha ao buscar similares no Qdrant") from exc

        results: list[tuple[int, float]] = []
        for point in response.points:
            ticket_id = int(point.id)
            # Qdrant cosine score is similarity; repository expects distance (1 - similarity).
            distance = max(0.0, 1.0 - float(point.score or 0.0))
            results.append((ticket_id, distance))
        return results

    def delete_by_ticket_ids(self, ticket_ids: list[int]) -> None:
        if not ticket_ids:
            return
        try:
            self._client.delete(
                collection_name=self._collection,
                points_selector=list(ticket_ids),
                wait=True,
            )
        except Exception as exc:
            raise RetrievalError("Falha ao remover embeddings do Qdrant") from exc

    def delete_all(self) -> None:
        try:
            self._client.delete_collection(self._collection)
            self._ensure_collection()
        except Exception as exc:
            raise RetrievalError("Falha ao limpar collection do Qdrant") from exc


def _build_search_filter(
    exclude_ticket_key: str | None,
    allowed_statuses: list[str] | None,
) -> Filter | None:
    must: list[FieldCondition] = []
    must_not: list[FieldCondition] = []

    if allowed_statuses:
        must.append(FieldCondition(key="status", match=MatchAny(any=allowed_statuses)))
    if exclude_ticket_key:
        must_not.append(FieldCondition(key="chave_jira", match=MatchValue(value=exclude_ticket_key)))

    if not must and not must_not:
        return None
    return Filter(must=must or None, must_not=must_not or None)
