import pytest

from utils.sqs_message import (
    describe_message_profile,
    format_parsed_message_preview,
    is_default_triage_flow,
    parse_message_body,
    resolve_email_body_flow,
    resolve_flow_flags,
)


def test_parse_json_completo() -> None:
    body, fmt = parse_message_body('{"chave_jira": "JDMSN1-1234", "transicionar": false}')
    assert body["chave_jira"] == "JDMSN1-1234"
    assert body["transicionar"] is False
    assert fmt == "json_completo"


def test_parse_json_somente_chave() -> None:
    body, fmt = parse_message_body('"JDMSN1-5678"')
    assert body == {"chave_jira": "JDMSN1-5678"}
    assert fmt == "json_chave"


def test_parse_texto_somente_chave() -> None:
    body, fmt = parse_message_body("jdmsn1-9999")
    assert body == {"chave_jira": "JDMSN1-9999"}
    assert fmt == "texto_chave"


def test_describe_perfil_completo() -> None:
    body = {"chave_jira": "JDMSN1-1"}
    summary = describe_message_profile(body, body_format="json_completo")
    assert "perfil=completo" in summary
    assert "fluxo=padrao" in summary
    assert "guard=duplicata_automacao" in summary


def test_is_default_triage_flow_only_key() -> None:
    assert is_default_triage_flow({"chave_jira": "JDMSN1-2844"}) is True


def test_is_default_triage_flow_with_flags() -> None:
    assert is_default_triage_flow({"chave_jira": "X", "transicionar": False}) is False


def test_is_default_triage_flow_with_body_do_email() -> None:
    assert is_default_triage_flow({"chave_jira": "X", "bodyDoEmail": "corpo"}) is False


def test_describe_perfil_parcial() -> None:
    body = {
        "chave_jira": "JDMSN1-1",
        "saudacao_publica": False,
        "comentario_interno": False,
        "transicionar": True,
        "nome_transicao": "Analise JDMS",
    }
    summary = describe_message_profile(body, body_format="json_completo")
    assert "perfil=parcial" in summary
    assert "saudacao=False" in summary
    assert "comentario=False" in summary
    assert "trans=True" in summary
    assert "nome_transicao=Analise JDMS" in summary


def test_resolve_flow_flags_defaults() -> None:
    flags = resolve_flow_flags({"chave_jira": "X-1"})
    assert flags["saudacao_publica"] is True
    assert flags["transicionar"] is True
    assert flags["nome_transicao"] == ""


def test_resolve_flow_flags_null_transition() -> None:
    flags = resolve_flow_flags({"nome_transicao": None})
    assert flags["nome_transicao"] == ""


def test_format_parsed_message_preview() -> None:
    body = {
        "chave_jira": "JDMSN1-1",
        "saudacao_publica": False,
        "transicionar": True,
        "nome_transicao": "Analise JDMS",
    }
    lines = format_parsed_message_preview(
        '{"chave_jira":"JDMSN1-1","saudacao_publica":false}',
        body,
        body_format="json_completo",
    )
    text = "\n".join(lines)
    assert "mensagem_sqs:" in text
    assert "corpo_bruto:" in text
    assert '"chave_jira": "JDMSN1-1"' in text
    assert "flags_resolvidas:" in text
    assert '"transicionar": true' in text


def test_parse_invalid_body_raises() -> None:
    with pytest.raises(ValueError):
        parse_message_body("nao-e-json-nem-chave")


def test_resolve_email_body_flow_absent() -> None:
    assert resolve_email_body_flow({"chave_jira": "JDMSN1-1"}) is None


def test_resolve_email_body_flow_camel_case() -> None:
    assert resolve_email_body_flow({"bodyDoEmail": "  Testando automação  "}) == "Testando automação"


def test_resolve_email_body_flow_snake_case() -> None:
    assert resolve_email_body_flow({"body_do_email": "Corpo do e-mail"}) == "Corpo do e-mail"


def test_resolve_email_body_flow_prefers_body_do_email_when_both_present() -> None:
    body = {"bodyDoEmail": "camel", "body_do_email": "snake"}
    assert resolve_email_body_flow(body) == "camel"


def test_resolve_email_body_flow_empty_raises() -> None:
    with pytest.raises(ValueError, match="bodyDoEmail"):
        resolve_email_body_flow({"bodyDoEmail": "   "})


def test_describe_perfil_email_body() -> None:
    body = {"chave_jira": "JDMSN1-1", "bodyDoEmail": "Teste"}
    summary = describe_message_profile(body, body_format="json_completo")
    assert "perfil=email_body" in summary
    assert "fluxo=comentario_avalara+trans" in summary
