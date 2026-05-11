import logging
import unicodedata
from datetime import datetime
from typing import Any

import httpx
from dateutil import parser as date_parser

from exceptions import JiraClientError, JiraIssueNotFoundError
from utils.retry import external_retry
from utils.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class JiraClient:
    def __init__(self) -> None:
        self.base_url = settings.jira_base_url.rstrip("/")
        self.auth = (settings.jira_email, settings.jira_api_token_value())
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}

    def is_configured(self) -> bool:
        return bool(self.base_url and settings.jira_email and settings.jira_api_token_value())

    def search_issues(self, jql: str, max_results: int = 0) -> list[dict[str, Any]]:
        if not self.is_configured():
            logger.warning("Jira client nao configurado; retornando lista vazia.")
            return []

        fields = ["summary", "description", "comment", "status", "created", "resolutiondate", "*navigable"]
        page_limit = 100
        requested_limit = max_results if max_results > 0 else None

        # Primary strategy for modern Jira Cloud: /search/jql with nextPageToken.
        try:
            return self._search_issues_jql_token(
                jql=jql,
                fields=fields,
                page_limit=page_limit,
                requested_limit=requested_limit,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {404, 405, 410}:
                raise
            logger.info(
                "Endpoint Jira /search/jql indisponivel (%s). Tentando fallback legado /search.",
                exc.response.status_code,
            )

        # Legacy fallback: /search with startAt (older/alternate environments).
        return self._search_issues_legacy_start_at(
            jql=jql,
            fields=fields,
            page_limit=page_limit,
            requested_limit=requested_limit,
        )

    def _search_issues_jql_token(
        self,
        *,
        jql: str,
        fields: list[str],
        page_limit: int,
        requested_limit: int | None,
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        next_page_token: str | None = None
        url = f"{self.base_url}/rest/api/3/search/jql"

        with httpx.Client(timeout=settings.external_timeout_seconds) as client:
            while True:
                remaining = (requested_limit - len(collected)) if requested_limit is not None else page_limit
                if requested_limit is not None and remaining <= 0:
                    break

                page_size = min(page_limit, remaining) if requested_limit is not None else page_limit
                payload: dict[str, Any] = {
                    "jql": jql,
                    "maxResults": page_size,
                    "fields": fields,
                }
                if next_page_token:
                    payload["nextPageToken"] = next_page_token

                response = self._request_with_retry(client, "POST", url, json=payload)
                data = response.json()
                issues = data.get("issues", [])
                if not issues:
                    break

                collected.extend(issues)
                next_page_token = data.get("nextPageToken")
                is_last = bool(data.get("isLast", False))

                if requested_limit is not None and len(collected) >= requested_limit:
                    break
                if is_last or not next_page_token:
                    break

        if requested_limit is not None:
            return collected[:requested_limit]
        return collected

    def _search_issues_legacy_start_at(
        self,
        *,
        jql: str,
        fields: list[str],
        page_limit: int,
        requested_limit: int | None,
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        start_at = 0

        with httpx.Client(timeout=settings.external_timeout_seconds) as client:
            while True:
                remaining = (requested_limit - len(collected)) if requested_limit is not None else page_limit
                if requested_limit is not None and remaining <= 0:
                    break

                page_size = min(page_limit, remaining) if requested_limit is not None else page_limit
                payload = {
                    "jql": jql,
                    "startAt": start_at,
                    "maxResults": page_size,
                    "fields": fields,
                }
                candidates: list[tuple[str, str, dict[str, Any]]] = [
                    (
                        "POST",
                        f"{self.base_url}/rest/api/3/search",
                        {"json": payload},
                    ),
                    (
                        "GET",
                        f"{self.base_url}/rest/api/3/search",
                        {
                            "params": {
                                "jql": jql,
                                "startAt": start_at,
                                "maxResults": page_size,
                                "fields": ",".join(fields),
                            }
                        },
                    ),
                ]

                data: dict[str, Any] | None = None
                last_error: Exception | None = None
                for method, url, kwargs in candidates:
                    try:
                        response = self._request_with_retry(client, method, url, **kwargs)
                        if response.status_code in {404, 405, 410}:
                            continue
                        data = response.json()
                        break
                    except JiraClientError as exc:
                        last_error = exc

                if data is None:
                    if last_error is not None:
                        raise last_error
                    break

                issues = data.get("issues", [])
                if not issues:
                    break

                collected.extend(issues)
                total = data.get("total")
                start_at += len(issues)

                if requested_limit is not None and len(collected) >= requested_limit:
                    break
                if isinstance(total, int) and start_at >= total:
                    break

        if requested_limit is not None:
            return collected[:requested_limit]
        return collected

    def get_issue(self, key: str) -> dict[str, Any] | None:
        if not self.is_configured():
            logger.warning("Jira client nao configurado; sem leitura de issue.")
            return None

        url = f"{self.base_url}/rest/api/3/issue/{key}"
        params = {"fields": "*navigable", "expand": "names"}
        with httpx.Client(timeout=settings.external_timeout_seconds) as client:
            try:
                response = self._request_with_retry(client, "GET", url, params=params)
            except JiraIssueNotFoundError:
                return None
            return response.json()

    def get_issue_property_keys(self, key: str) -> list[str]:
        if not self.is_configured():
            logger.warning("Jira client nao configurado; sem leitura de propriedades da issue.")
            return []

        url = f"{self.base_url}/rest/api/3/issue/{key}/properties"
        with httpx.Client(timeout=settings.external_timeout_seconds) as client:
            try:
                response = self._request_with_retry(client, "GET", url)
            except JiraIssueNotFoundError:
                return []
            data = response.json()
            keys = data.get("keys", [])
            return [str(item.get("key", "")).strip() for item in keys if item.get("key")]

    def get_issue_property(self, key: str, property_key: str) -> dict[str, Any] | None:
        if not self.is_configured():
            logger.warning("Jira client nao configurado; sem leitura de propriedade da issue.")
            return None

        url = f"{self.base_url}/rest/api/3/issue/{key}/properties/{property_key}"
        with httpx.Client(timeout=settings.external_timeout_seconds) as client:
            try:
                response = self._request_with_retry(client, "GET", url)
            except JiraIssueNotFoundError:
                return None
            return response.json()

    def extract_request_id(self, issue: dict[str, Any]) -> str | None:
        fields = issue.get("fields", {})
        request_field = fields.get("customfield_10010")
        if isinstance(request_field, dict):
            links = request_field.get("_links", {})
            for link_key in ("self", "jiraRest", "web"):
                link = links.get(link_key, "")
                if isinstance(link, str):
                    candidate = link.rstrip("/").split("/")[-1]
                    if candidate.isdigit():
                        return candidate

        for value in fields.values():
            if not isinstance(value, dict):
                continue
            links = value.get("_links", {})
            if not isinstance(links, dict):
                continue
            for link_key in ("self", "jiraRest", "web"):
                link = links.get(link_key, "")
                if isinstance(link, str) and "/request/" in link:
                    candidate = link.rstrip("/").split("/")[-1]
                    if candidate.isdigit():
                        return candidate
        return None

    def extract_reporter_first_name(self, issue: dict[str, Any]) -> str:
        fields = issue.get("fields", {})
        reporter = fields.get("reporter") or {}
        display_name = reporter.get("displayName", "") if isinstance(reporter, dict) else ""
        first_name = display_name.strip().split()[0] if display_name else "Equipe"
        return first_name or "Equipe"

    def post_public_comment(self, request_id: str, body: str) -> None:
        if not self.is_configured():
            raise JiraClientError("Jira client nao configurado")
        if not request_id.strip():
            raise JiraClientError("Request ID do Service Desk nao encontrado")

        url = f"{self.base_url}/rest/servicedeskapi/request/{request_id}/comment"
        payload = {"body": body, "public": True}
        with httpx.Client(timeout=settings.external_timeout_seconds) as client:
            self._request_with_retry(client, "POST", url, json=payload)

    def transition_issue(self, issue_key: str, transition_name: str) -> bool:
        if not self.is_configured():
            raise JiraClientError("Jira client nao configurado")

        current_issue = self.get_issue(issue_key)
        current_status = ((current_issue or {}).get("fields", {}).get("status", {}) or {}).get("name", "")
        if _normalize_label(current_status) == _normalize_label(transition_name):
            return False

        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/transitions"
        with httpx.Client(timeout=settings.external_timeout_seconds) as client:
            transitions_response = self._request_with_retry(client, "GET", url)
            transitions = transitions_response.json().get("transitions", [])
            transition_id = next(
                (
                    item.get("id")
                    for item in transitions
                    if _normalize_label((item.get("to") or {}).get("name", "")) == _normalize_label(transition_name)
                ),
                None,
            )
            if not transition_id:
                raise JiraClientError(f"Transicao Jira nao encontrada: {transition_name}")
            self._request_with_retry(client, "POST", url, json={"transition": {"id": transition_id}})
        return True

    def assign_issue(self, issue_key: str, account_id: str) -> None:
        if not self.is_configured():
            raise JiraClientError("Jira client nao configurado")
        if not account_id.strip():
            raise JiraClientError("Account ID do responsavel nao informado")

        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/assignee"
        with httpx.Client(timeout=settings.external_timeout_seconds) as client:
            self._request_with_retry(client, "PUT", url, json={"accountId": account_id})

    def create_internal_comment(self, issue_key: str, body: str) -> None:
        if not self.is_configured():
            logger.warning("Jira client nao configurado; comentario interno nao enviado.")
            return

        if not settings.jira_post_comments:
            logger.warning("Envio de comentarios Jira desabilitado (JIRA_POST_COMMENTS=false).")
            return

        # Post via issue comments API marking sd.public.comment as internal.
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/comment"
        lines = [line.strip() for line in body.split("\n") if line.strip()]
        content = [{"type": "paragraph", "content": [{"type": "text", "text": line}]} for line in lines]
        payload = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": content,
            },
            "properties": [
                {
                    "key": "sd.public.comment",
                    "value": {"internal": True},
                }
            ],
        }
        with httpx.Client(timeout=settings.external_timeout_seconds) as client:
            self._request_with_retry(client, "POST", url, json=payload)

    def post_comment_direct(self, issue_key: str, body: str) -> None:
        """Posta comentario interno independentemente da flag JIRA_POST_COMMENTS."""
        if not self.is_configured():
            raise RuntimeError("Jira client nao configurado")

        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/comment"
        lines = [line.strip() for line in body.split("\n") if line.strip()]
        content = [{"type": "paragraph", "content": [{"type": "text", "text": line}]} for line in lines]
        payload = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": content,
            },
            "properties": [
                {
                    "key": "sd.public.comment",
                    "value": {"internal": True},
                }
            ],
        }
        with httpx.Client(timeout=settings.external_timeout_seconds) as client:
            self._request_with_retry(client, "POST", url, json=payload)

    @external_retry()
    def _request_with_retry(self, client: httpx.Client, method: str, url: str, **kwargs: Any) -> httpx.Response:
        response = client.request(method, url, auth=self.auth, headers=self.headers, **kwargs)
        if response.status_code == 404:
            raise JiraIssueNotFoundError(f"Recurso Jira nao encontrado: {url}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise JiraClientError(f"Falha ao chamar Jira: {exc.response.status_code}") from exc
        return response


def normalize_issue(issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields", {})
    comments_data = fields.get("comment", {}).get("comments", [])
    comments = []

    for comment in comments_data:
        body_text = _extract_text_from_adf(comment.get("body"))
        if body_text:
            comments.append(body_text)

    created = _parse_dt(fields.get("created"))
    resolved = _parse_dt(fields.get("resolutiondate"))

    return {
        "chave_jira": issue.get("key", ""),
        "resumo": fields.get("summary", ""),
        "descricao": _extract_text_from_adf(fields.get("description")),
        "comentarios": "\n".join(comments),
        "produto": _extract_product_field(fields),
        "tema_chamado": _extract_theme_field(fields),
        "status": fields.get("status", {}).get("name", ""),
        "data_criacao": created,
        "data_fechamento": resolved,
    }


def _extract_text_from_adf(node: Any) -> str:
    if node is None:
        return ""

    if isinstance(node, str):
        return node

    if isinstance(node, list):
        return " ".join(_extract_text_from_adf(item) for item in node).strip()

    if isinstance(node, dict):
        text = node.get("text", "")
        content = _extract_text_from_adf(node.get("content", []))
        joined = " ".join(p for p in [text, content] if p).strip()
        return joined

    return ""


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return date_parser.parse(value)


# Known product names to detect from custom fields (lowercased)
_KNOWN_PRODUCTS = [
    "avatax",
    "tax compliance",
    "taxcompliance",
    "taxdocs",
    "tax docs",
    "tax central",
    "taxcentral",
]

_THEME_HINT_TERMS = [
    "tax docs",
    "taxdocs",
    "tax compliance",
    "avatax",
    "tax central",
    "relatorio",
    "integracao",
    "obrigacao",
    "captura",
]


def _extract_product_field(fields: dict[str, Any]) -> str:
    """Extrai o nome do produto a partir dos campos do Jira.

    Tenta, em ordem:
    1. Campo explicitamente configurado via JIRA_PRODUCT_FIELD.
    2. Varredura de campos customizados cujo valor contenha um produto conhecido.
    """
    explicit_field = settings.jira_product_field.strip()
    if explicit_field:
        val = _field_text_value(fields.get(explicit_field))
        if val:
            return val

    # Auto-detect: scan custom fields
    for key, val in fields.items():
        if not key.startswith("customfield_"):
            continue
        text = _field_text_value(val).lower()
        if not text:
            continue
        for product in _KNOWN_PRODUCTS:
            if product in text:
                return _field_text_value(val)

    return ""


def _extract_theme_field(fields: dict[str, Any]) -> str:
    """Extrai o tema do chamado a partir dos campos Jira.

    Tenta, em ordem:
    1. Campo explicitamente configurado via JIRA_THEME_FIELD.
    2. Heuristica textual em campos customizados.
    """
    explicit_field = settings.jira_theme_field.strip()
    if explicit_field:
        val = _field_text_value(fields.get(explicit_field))
        if val:
            return val

    for key, val in fields.items():
        if not key.startswith("customfield_"):
            continue
        text = _field_text_value(val)
        if not text:
            continue
        text_norm = text.lower()
        if any(term in text_norm for term in _THEME_HINT_TERMS) and len(text) >= 8:
            return text

    return ""


def _field_text_value(val: Any) -> str:
    """Extrai texto plano de um campo Jira (string, dict com 'value', lista, etc)."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, dict):
        for key in ("value", "name", "displayName"):
            if val.get(key):
                return str(val[key]).strip()
    if isinstance(val, list) and val:
        texts = [_field_text_value(item) for item in val if item]
        return ", ".join(t for t in texts if t)
    return ""


def _normalize_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(ascii_text.lower().split())
