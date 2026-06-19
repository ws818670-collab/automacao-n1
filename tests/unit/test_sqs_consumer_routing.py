from unittest.mock import MagicMock, patch

from worker.sqs_consumer import _process_message


def test_process_message_routes_email_body_without_db() -> None:
    flow_service = MagicMock()
    flow_service.process_email_body_reply.return_value = {
        "chave_jira": "JDMSN1-2222",
        "comentario_motivo": "realizada",
        "transicao_motivo": "realizada",
    }

    body = {"chave_jira": "JDMSN1-2222", "bodyDoEmail": "Testando automação"}
    result = _process_message(flow_service, body)

    flow_service.process_email_body_reply.assert_called_once_with(
        "JDMSN1-2222",
        "Testando automação",
    )
    flow_service.process_issue.assert_not_called()
    assert result["comentario_motivo"] == "realizada"


@patch("worker.sqs_consumer.SessionLocal")
def test_process_message_default_flow_enables_duplicate_guard(mock_session_local: MagicMock) -> None:
    flow_service = MagicMock()
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db
    flow_service.process_issue.return_value = {
        "chave_jira": "JDMSN1-2844",
        "comentario_motivo": "realizada",
    }

    result = _process_message(flow_service, {"chave_jira": "JDMSN1-2844"})

    flow_service.process_issue.assert_called_once()
    assert flow_service.process_issue.call_args.kwargs["skip_if_automation_commented"] is True
    mock_db.commit.assert_called_once()
    assert result["comentario_motivo"] == "realizada"


@patch("worker.sqs_consumer.SessionLocal")
def test_process_message_partial_flow_disables_duplicate_guard(mock_session_local: MagicMock) -> None:
    flow_service = MagicMock()
    mock_session_local.return_value = MagicMock()
    flow_service.process_issue.return_value = {"chave_jira": "JDMSN1-2844"}

    _process_message(flow_service, {"chave_jira": "JDMSN1-2844", "transicionar": False})

    assert flow_service.process_issue.call_args.kwargs["skip_if_automation_commented"] is False
