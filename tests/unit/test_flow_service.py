from unittest.mock import MagicMock

import pytest

from jira.flow_service import JiraFlowService


@pytest.fixture
def flow_service(configured_env: None) -> JiraFlowService:
    return JiraFlowService(
        jira_client=MagicMock(),
        ingestion_service=MagicMock(),
        embedding_service=MagicMock(),
        retrieval_service=MagicMock(),
        llm_service=MagicMock(),
        allowed_statuses=["Resolvido"],
    )


def _setup_issue_mocks(flow_service: JiraFlowService) -> None:
    raw_issue = {
        "key": "JDMSN1-2797",
        "fields": {
            "assignee": {"displayName": "Agente"},
            "status": {"name": "Analise JDMS"},
        },
    }
    flow_service.jira_client.get_issue.return_value = raw_issue
    flow_service.jira_client.extract_request_id.return_value = None
    flow_service.jira_client.extract_reporter_first_name.return_value = "Maria"
    flow_service.jira_client.transition_issue.return_value = True
    flow_service.llm_service.generate_triage_comment.return_value = ("comentario", [], False)


def test_process_issue_accepts_null_transition_name(flow_service: JiraFlowService, sqlite_session) -> None:
    _setup_issue_mocks(flow_service)

    result = flow_service.process_issue(
        sqlite_session,
        "JDMSN1-2797",
        saudacao_publica=False,
        transicionar=True,
        atribuir=False,
        comentario_interno=False,
        nome_transicao=None,
    )

    flow_service.jira_client.transition_issue.assert_called_once_with(
        "JDMSN1-2797",
        transition_name="Analise JDMS",
    )
    assert result["transicao_realizada"] is True


def test_process_issue_uses_custom_transition_name(flow_service: JiraFlowService, sqlite_session) -> None:
    _setup_issue_mocks(flow_service)

    flow_service.process_issue(
        sqlite_session,
        "JDMSN1-2797",
        saudacao_publica=False,
        transicionar=True,
        atribuir=False,
        comentario_interno=False,
        nome_transicao="  Triagem N1  ",
    )

    flow_service.jira_client.transition_issue.assert_called_once_with(
        "JDMSN1-2797",
        transition_name="Triagem N1",
    )


def test_process_email_body_reply_posts_comment_and_transitions(flow_service: JiraFlowService) -> None:
    raw_issue = {
        "key": "JDMSN1-2222",
        "fields": {
            "assignee": {"displayName": "Agente"},
            "status": {"name": "Analise JDMS"},
        },
    }
    flow_service.jira_client.get_issue.return_value = raw_issue
    flow_service.jira_client.transition_issue.return_value = True

    result = flow_service.process_email_body_reply("JDMSN1-2222", "Testando automação")

    flow_service.jira_client.post_comment_direct.assert_called_once_with(
        "JDMSN1-2222",
        "Comentário Avalara\n\nTestando automação",
    )
    flow_service.jira_client.transition_issue.assert_called_once_with(
        "JDMSN1-2222",
        transition_name="Analise JDMS",
    )
    flow_service.ingestion_service.process_ticket_data.assert_not_called()
    flow_service.llm_service.generate_triage_comment.assert_not_called()
    assert result["comentario_motivo"] == "realizada"
    assert result["transicao_motivo"] == "realizada"
    assert result["transicao_destino"] == "Analise JDMS"


def test_process_email_body_reply_already_in_status(flow_service: JiraFlowService) -> None:
    flow_service.jira_client.get_issue.return_value = {
        "key": "JDMSN1-2222",
        "fields": {"status": {"name": "Analise JDMS"}},
    }
    flow_service.jira_client.transition_issue.return_value = False

    result = flow_service.process_email_body_reply("JDMSN1-2222", "Corpo")

    assert result["transicao_motivo"] == "ja_no_status"
    assert result["transicao_realizada"] is False


def test_process_email_body_reply_issue_not_found(flow_service: JiraFlowService) -> None:
    from exceptions import JiraIssueNotFoundError

    flow_service.jira_client.get_issue.return_value = None

    with pytest.raises(JiraIssueNotFoundError):
        flow_service.process_email_body_reply("JDMSN1-9999", "Corpo")

    flow_service.jira_client.post_comment_direct.assert_not_called()
