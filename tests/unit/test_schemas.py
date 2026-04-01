import pytest
from pydantic import ValidationError

from api.schemas import AnalyzeRequest, ChatQueryRequest, IngestRequest, JiraWebhookPayload


def test_webhook_payload_rejects_invalid_issue_key() -> None:
    with pytest.raises(ValidationError):
        JiraWebhookPayload(chave_jira="invalido", resumo="ok")


def test_chat_query_requires_non_blank_question() -> None:
    with pytest.raises(ValidationError):
        ChatQueryRequest(pergunta="   ")


def test_analyze_request_accepts_valid_issue_key() -> None:
    payload = AnalyzeRequest(chave_jira="JDMSN1-1234")
    assert payload.chave_jira == "JDMSN1-1234"


def test_ingest_request_limits_max_results() -> None:
    with pytest.raises(ValidationError):
        IngestRequest(jql="project = JDMSN1", max_results=1000)