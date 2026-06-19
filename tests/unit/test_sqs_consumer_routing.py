from unittest.mock import MagicMock

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
