import logging
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
        params = {"fields": "*navigable"}
        with httpx.Client(timeout=settings.external_timeout_seconds) as client:
            try:
                response = self._request_with_retry(client, "GET", url, params=params)
            except JiraIssueNotFoundError:
                return None
            return response.json()

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
