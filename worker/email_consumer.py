"""
Worker Microsoft Graph API para capturar respostas da Avalara por e-mail.

Fluxo:
1) Le e-mails nao lidos da caixa configurada via Microsoft Graph API.
2) Extrai chaves Jira (ex.: JDMSN1-2720) de assunto/corpo.
3) Publica comentario interno no chamado.
4) Transiciona o chamado para "Analise JDMS" (ou EMAIL_TRIAGE_TRANSITION_NAME).

Pre-requisito: execute uma vez `python tools/get_graph_token.py` para gerar o
refresh token e salve o resultado no .env como GRAPH_REFRESH_TOKEN.

Uso: na pasta project, com venv ativo: python -m worker.email_consumer
"""

import logging
import re
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import msal
except ImportError as _exc:
    raise ImportError("Instale o msal: pip install 'msal>=1.31.0'") from _exc

import httpx
from dateutil import parser as date_parser

from exceptions import JiraClientError, JiraIssueNotFoundError
from jira.client import JiraClient
from utils.config import Settings, get_settings
from utils.logging import compact_error_message, configure_logging, set_correlation_id

logger = logging.getLogger(__name__)
slog = logging.getLogger("worker.email")

_JIRA_KEY_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_GRAPH_SCOPES = ["https://graph.microsoft.com/Mail.Read"]


@dataclass(slots=True)
class InboxMessage:
    uid: str
    sender: str
    subject: str
    body: str
    received_at: datetime | None


class _ShutdownFlag:
    __slots__ = ("active",)

    def __init__(self) -> None:
        self.active = True

    def request_stop(self, signum, _frame) -> None:
        slog.info("Encerrando worker de e-mail (sinal %s)", signum)
        self.active = False


_shutdown = _ShutdownFlag()


class GraphInboxClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._allowed_senders = {s.strip().lower() for s in settings.email_allowed_senders if s.strip()}
        self._msal_app = msal.PublicClientApplication(
            client_id=settings.graph_client_id,
            authority=f"https://login.microsoftonline.com/{settings.graph_tenant_id}",
        )
        self._cached_token: str | None = None

    def _get_access_token(self) -> str:
        accounts = self._msal_app.get_accounts()
        if accounts:
            result = self._msal_app.acquire_token_silent(_GRAPH_SCOPES, account=accounts[0])
            if result and "access_token" in result:
                return result["access_token"]

        result = self._msal_app.acquire_token_by_refresh_token(
            self._settings.graph_refresh_token,
            scopes=_GRAPH_SCOPES,
        )
        if "access_token" not in result:
            desc = result.get("error_description") or result.get("error") or str(result)
            raise RuntimeError(f"Falha ao renovar token Graph: {desc}")
        return result["access_token"]

    def fetch_unseen(self, limit: int) -> list[InboxMessage]:
        token = self._get_access_token()
        mailbox = self._settings.graph_mailbox or self._settings.email_imap_username
        url = (
            f"{_GRAPH_BASE}/users/{mailbox}/mailFolders/Inbox/messages"
            f"?$filter=isRead eq false"
            f"&$top={limit}"
            f"&$select=id,subject,from,receivedDateTime,body"
            f"&$orderby=receivedDateTime desc"
        )
        headers = {"Authorization": f"Bearer {token}"}
        response = httpx.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        out: list[InboxMessage] = []
        for item in response.json().get("value", []):
            sender = item.get("from", {}).get("emailAddress", {}).get("address", "").lower()
            if self._allowed_senders and sender not in self._allowed_senders:
                continue

            body_obj = item.get("body", {})
            body_text = body_obj.get("content", "") or ""
            if body_obj.get("contentType", "").lower() == "html":
                body_text = _strip_html(body_text)

            received_at: datetime | None = None
            received_str = item.get("receivedDateTime", "")
            if received_str:
                try:
                    received_at = date_parser.parse(received_str)
                except (TypeError, ValueError):
                    pass

            out.append(
                InboxMessage(
                    uid=item["id"],
                    sender=sender,
                    subject=item.get("subject", "") or "",
                    body=body_text,
                    received_at=received_at,
                )
            )
        return out

    def mark_seen(self, uid: str) -> None:
        token = self._get_access_token()
        mailbox = self._settings.graph_mailbox or self._settings.email_imap_username
        url = f"{_GRAPH_BASE}/users/{mailbox}/messages/{uid}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        httpx.patch(url, headers=headers, json={"isRead": True}, timeout=30).raise_for_status()


def _strip_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", without_tags).strip()


def _extract_raw_email(fetch_payload) -> bytes:
    for part in fetch_payload:
        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
            return bytes(part[1])
    return b""


def _decode_subject(subject: str) -> str:
    from email.header import decode_header
    chunks: list[str] = []
    for value, charset in decode_header(subject):
        if isinstance(value, bytes):
            chunks.append(value.decode(charset or "utf-8", errors="replace"))
        else:
            chunks.append(value)
    return "".join(chunks).strip()


def _extract_sender(msg) -> str:
    from email.utils import parseaddr
    _, addr = parseaddr(msg.get("From", ""))
    return (addr or "").strip().lower()


def _extract_received_at(msg) -> datetime | None:
    from email.utils import parsedate_to_datetime
    value = msg.get("Date")
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _extract_body_text(msg) -> str:
    import email as _email
    if msg.is_multipart():
        plain_parts: list[str] = []
        html_parts: list[str] = []
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", "")).lower()
            if "attachment" in disposition:
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace").strip()
            if not text:
                continue
            if content_type == "text/plain":
                plain_parts.append(text)
            elif content_type == "text/html":
                html_parts.append(_strip_html(text))
        if plain_parts:
            return "\n\n".join(plain_parts)
        if html_parts:
            return "\n\n".join(html_parts)
        return ""
    payload = msg.get_payload(decode=True)
    if payload is None:
        return ""
    charset = msg.get_content_charset() or "utf-8"
    text = payload.decode(charset, errors="replace").strip()
    if msg.get_content_type() == "text/html":
        return _strip_html(text)
    return text


def extract_jira_keys(text: str) -> list[str]:
    found = _JIRA_KEY_PATTERN.findall((text or "").upper())
    ordered: list[str] = []
    seen: set[str] = set()
    for key in found:
        if key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def build_avalara_internal_comment(message: InboxMessage, jira_key: str) -> str:
    received = message.received_at.isoformat() if message.received_at else "Data nao informada"
    body = (message.body or "").strip()
    if len(body) > 9000:
        body = body[:9000].rstrip() + "\n\n[texto truncado]"

    return (
        "Retorno da Avalara recebido por e-mail.\n"
        f"Chave identificada: {jira_key}\n"
        f"Remetente: {message.sender or 'nao identificado'}\n"
        f"Assunto: {message.subject or 'sem assunto'}\n"
        f"Data do e-mail: {received}\n"
        "\n"
        "Corpo da mensagem:\n"
        f"{body or '[sem conteudo textual]'}"
    )


def _validate_graph_settings(settings: Settings) -> None:
    missing = []
    if not settings.graph_tenant_id.strip():
        missing.append("GRAPH_TENANT_ID")
    if not settings.graph_client_id.strip():
        missing.append("GRAPH_CLIENT_ID")
    if not settings.graph_refresh_token.strip():
        missing.append("GRAPH_REFRESH_TOKEN")
    mailbox = settings.graph_mailbox.strip() or settings.email_imap_username.strip()
    if not mailbox:
        missing.append("GRAPH_MAILBOX (ou EMAIL_IMAP_USERNAME)")
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"Configuracao Microsoft Graph incompleta: {joined}\n"
            "Execute: python tools/get_graph_token.py"
        )


def _process_message(jira_client: JiraClient, message: InboxMessage, transition_name: str) -> int:
    search_text = f"{message.subject}\n\n{message.body}"
    keys = extract_jira_keys(search_text)
    if not keys:
        slog.warning("E-mail ignorado: nenhuma chave Jira encontrada | assunto=%s", message.subject[:120])
        return 0

    processed = 0
    for key in keys:
        set_correlation_id(key)
        try:
            jira_client.post_comment_direct(key, build_avalara_internal_comment(message, key))
            jira_client.transition_issue(key, transition_name)
            slog.info("Atualizacao Jira via e-mail concluida | %s", key)
            processed += 1
        except JiraIssueNotFoundError:
            slog.warning("Chave Jira nao encontrada no retorno de e-mail | %s", key)
        except JiraClientError as exc:
            slog.error("Falha ao atualizar Jira via e-mail | %s | %s", key, compact_error_message(exc))
            raise
        finally:
            set_correlation_id(None)

    return processed


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.worker_log_format, for_worker=True)
    _validate_graph_settings(settings)

    jira_client = JiraClient()
    if not jira_client.is_configured():
        raise RuntimeError("Jira client nao configurado")

    inbox_client = GraphInboxClient(settings)

    signal.signal(signal.SIGINT, _shutdown.request_stop)
    signal.signal(signal.SIGTERM, _shutdown.request_stop)

    transition_name = settings.email_triage_transition_name.strip() or settings.jira_triage_transition_name
    mailbox = settings.graph_mailbox.strip() or settings.email_imap_username.strip()

    slog.info(
        "Worker de e-mail (Graph API) pronto | caixa=%s | intervalo=%ss | remetentes=%s",
        mailbox,
        settings.email_poll_interval_seconds,
        ",".join(settings.email_allowed_senders) if settings.email_allowed_senders else "todos",
    )

    while _shutdown.active:
        try:
            messages = inbox_client.fetch_unseen(settings.email_max_messages_per_poll)
            if not messages:
                time.sleep(max(1, settings.email_poll_interval_seconds))
                continue

            for msg in messages:
                try:
                    count = _process_message(jira_client, msg, transition_name)
                    if settings.email_mark_as_seen:
                        inbox_client.mark_seen(msg.uid)
                    slog.info("E-mail processado | assunto=%s | chamados_atualizados=%s", msg.subject[:120], count)
                except Exception:
                    slog.exception("Falha ao processar e-mail | assunto=%s", msg.subject[:120])

        except httpx.HTTPStatusError as exc:
            slog.error("Falha Graph API HTTP %s: %s", exc.response.status_code, compact_error_message(exc))
            time.sleep(max(5, settings.email_poll_interval_seconds))
        except Exception:
            slog.exception("Falha inesperada no worker de e-mail")
            time.sleep(max(5, settings.email_poll_interval_seconds))


if __name__ == "__main__":
    run()
