"""Parse e resumo de mensagens da fila SQS do worker Jira."""

from __future__ import annotations

import json
import re
from typing import Any

_JIRA_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$", re.IGNORECASE)

FLOW_BOOL_DEFAULTS: dict[str, bool] = {
    "saudacao_publica": True,
    "transicionar": True,
    "atribuir": True,
    "comentario_interno": True,
}

FLOW_BOOL_LABELS: dict[str, str] = {
    "saudacao_publica": "saudacao",
    "transicionar": "trans",
    "atribuir": "atrib",
    "comentario_interno": "comentario",
}


def _looks_like_jira_key(value: str) -> bool:
    return bool(_JIRA_KEY_RE.match(value.strip()))


def parse_message_body(raw: str) -> tuple[dict[str, Any], str]:
    """
    Converte o corpo bruto da SQS em dict normalizado.

    Retorna (body, formato) onde formato e:
      - json_completo: objeto JSON
      - json_chave: string JSON com a chave do ticket
      - texto_chave: texto puro com a chave do ticket
    """
    text = raw.strip()
    if not text:
        raise ValueError("Mensagem SQS vazia")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        if _looks_like_jira_key(text):
            return {"chave_jira": text.upper()}, "texto_chave"
        raise ValueError("Corpo SQS nao e JSON valido nem chave Jira reconhecivel") from None

    if isinstance(parsed, str):
        key = parsed.strip()
        if not key:
            raise ValueError("Chave Jira vazia no JSON")
        return {"chave_jira": key.upper() if _looks_like_jira_key(key) else key}, "json_chave"

    if isinstance(parsed, dict):
        return parsed, "json_completo"

    raise ValueError(f"Tipo JSON nao suportado: {type(parsed).__name__}")


def resolve_flow_flags(body: dict[str, Any]) -> dict[str, Any]:
    """Aplica defaults do fluxo e normaliza campos opcionais."""
    return {
        "saudacao_publica": bool(body.get("saudacao_publica", True)),
        "transicionar": bool(body.get("transicionar", True)),
        "atribuir": bool(body.get("atribuir", True)),
        "comentario_interno": bool(body.get("comentario_interno", True)),
        "responsavel_account_id": body.get("responsavel_account_id") or "",
        "nome_transicao": body.get("nome_transicao") or "",
    }


def describe_message_profile(body: dict[str, Any], *, body_format: str) -> str:
    """Linha legivel do perfil da mensagem para logs do worker."""
    explicit_bool = [key for key in FLOW_BOOL_DEFAULTS if key in body]
    explicit_str = [
        key
        for key in ("responsavel_account_id", "nome_transicao")
        if key in body and str(body.get(key) or "").strip()
    ]
    format_label = {
        "json_completo": "json",
        "json_chave": "json_só_chave",
        "texto_chave": "texto_só_chave",
    }.get(body_format, body_format)

    if not explicit_bool and not explicit_str:
        return (
            f"formato={format_label} | perfil=completo | "
            "fluxo=padrao (saudacao+trans+atrib+comentario)"
        )

    parts = [f"formato={format_label}", "perfil=parcial"]
    for key, default in FLOW_BOOL_DEFAULTS.items():
        label = FLOW_BOOL_LABELS[key]
        if key in body:
            parts.append(f"{label}={body[key]}")
        else:
            parts.append(f"{label}=default({default})")

    transition_name = str(body.get("nome_transicao") or "").strip()
    if transition_name:
        parts.append(f"nome_transicao={transition_name}")

    assignee = str(body.get("responsavel_account_id") or "").strip()
    if assignee:
        parts.append("responsavel=informado")

    return " | ".join(parts)


def format_parsed_message_preview(
    raw_body: str,
    body: dict[str, Any],
    *,
    body_format: str,
) -> list[str]:
    """Linhas legiveis da mensagem SQS (bruto, parseado e flags com defaults)."""
    flags = resolve_flow_flags(body)
    lines = [
        "mensagem_sqs:",
        f"  corpo_bruto: {raw_body.strip()}",
        f"  formato_detectado: {body_format}",
        "  parseado:",
    ]
    parsed_json = json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True)
    lines.extend(f"    {line}" for line in parsed_json.splitlines())
    lines.append("  flags_resolvidas:")
    flags_json = json.dumps(flags, ensure_ascii=False, indent=2, sort_keys=True)
    lines.extend(f"    {line}" for line in flags_json.splitlines())
    return lines
