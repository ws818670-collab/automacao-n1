from datetime import datetime, timezone

from worker.email_consumer import InboxMessage, build_avalara_internal_comment, extract_jira_keys


def test_extract_jira_keys_deduplicates_and_preserves_order() -> None:
    text = "Re: JDMSN1-2720 e JDMSN1-2720 com copia para ABC-123"
    keys = extract_jira_keys(text)
    assert keys == ["JDMSN1-2720", "ABC-123"]


def test_extract_jira_keys_works_with_lowercase_input() -> None:
    text = "retorno no chamado jdmsn1-1001"
    keys = extract_jira_keys(text)
    assert keys == ["JDMSN1-1001"]


def test_build_avalara_internal_comment_contains_main_fields() -> None:
    msg = InboxMessage(
        uid="1",
        sender="suporte@avalara.com",
        subject="Re: JDMSN1-2720",
        body="Segue retorno da investigacao.",
        received_at=datetime(2026, 4, 30, 15, 0, tzinfo=timezone.utc),
    )

    comment = build_avalara_internal_comment(msg, "JDMSN1-2720")

    assert "Retorno da Avalara recebido por e-mail." in comment
    assert "Chave identificada: JDMSN1-2720" in comment
    assert "Remetente: suporte@avalara.com" in comment
    assert "Assunto: Re: JDMSN1-2720" in comment
    assert "Corpo da mensagem:" in comment
    assert "Segue retorno da investigacao." in comment
