from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from vector.qdrant_store import QdrantVectorStore, _build_search_filter


@pytest.fixture
def qdrant_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "test@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "token")
    monkeypatch.setenv("QDRANT_URL", "https://qdrant.example.com")
    monkeypatch.setenv("QDRANT_API_KEY", "test-key")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "1536")
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")

    from utils.config import get_settings
    from vector.factory import build_vector_store

    get_settings.cache_clear()
    build_vector_store.cache_clear()
    return get_settings()


def test_build_search_filter_with_status_and_exclude() -> None:
    query_filter = _build_search_filter("JDMSN1-1", ["Concluido", "Analise JDMS"])
    assert query_filter is not None
    assert query_filter.must is not None
    assert query_filter.must_not is not None


def test_build_search_filter_empty_returns_none() -> None:
    assert _build_search_filter(None, None) is None


@patch("vector.qdrant_store.QdrantClient")
def test_qdrant_store_upsert_and_search(mock_client_cls, qdrant_settings) -> None:
    mock_client = MagicMock()
    mock_client.collection_exists.return_value = True
    mock_client.query_points.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(id=10, score=0.82),
            SimpleNamespace(id=20, score=0.71),
        ]
    )
    mock_client_cls.return_value = mock_client

    store = QdrantVectorStore(qdrant_settings)
    vector = [0.1] * qdrant_settings.embedding_dimension
    store.upsert(
        ticket_id=10,
        chave_jira="JDMSN1-10",
        vector=vector,
        status="Concluido",
        produto="Tax Compliance",
    )
    results = store.search(vector, top_k=2, exclude_ticket_key="JDMSN1-99", allowed_statuses=["Concluido"])

    mock_client.upsert.assert_called_once()
    mock_client.query_points.assert_called_once()
    assert results == [(10, pytest.approx(0.18)), (20, pytest.approx(0.29))]


@patch("vector.qdrant_store.QdrantClient")
def test_build_vector_store_returns_none_without_url(mock_client_cls, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "test@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "token")
    monkeypatch.setenv("QDRANT_URL", "")
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")

    from utils.config import get_settings
    from vector.factory import build_vector_store

    get_settings.cache_clear()
    build_vector_store.cache_clear()

    assert build_vector_store() is None
    mock_client_cls.assert_not_called()
