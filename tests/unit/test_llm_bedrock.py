"""LLMService — somente Amazon Bedrock."""

import json
from unittest.mock import MagicMock, patch

import pytest

from llm.service import LLMService
from utils.config import get_settings


@pytest.fixture
def bedrock_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("JIRA_BASE_URL", "https://x.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "test@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "token")
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA123")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "shhh")
    monkeypatch.setenv("BEDROCK_MODEL", "amazon.nova-lite-v1:0")
    get_settings.cache_clear()


def test_request_llm_json_uses_only_bedrock(bedrock_settings: None) -> None:
    payload_json = {
        "cenario": "Erro na integracao",
        "causa_provavel": "Campo obrigatorio ausente",
        "chamados_relacionados": [],
        "analise_chamados": "Padrao recorrente",
        "acao_recomendada_n1": ["a", "b", "c"],
        "criterios_escalonamento_n2": ["x"],
        "passos_n1": ["1", "2", "3"],
        "indicacao": "Resolver no N1",
        "confianca": "Alta",
    }
    mock_client = MagicMock()
    mock_client.converse.return_value = {
        "output": {"message": {"content": [{"text": json.dumps(payload_json)}]}},
        "usage": {"totalTokens": 120},
    }

    with patch("llm.service.make_bedrock_runtime_client", return_value=mock_client):
        service = LLMService()

    raw = service._request_llm_json("system prompt", {"resumo": "teste"})
    assert raw is not None
    assert json.loads(raw)["cenario"] == "Erro na integracao"
    mock_client.converse.assert_called_once()
    call_kwargs = mock_client.converse.call_args.kwargs
    assert call_kwargs["modelId"] == "amazon.nova-lite-v1:0"
    assert call_kwargs["system"] == [{"text": "system prompt"}]
