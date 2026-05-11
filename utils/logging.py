import logging
import re
from contextvars import ContextVar

import httpx

try:
    from pythonjsonlogger.json import JsonFormatter
except ImportError:  # Compatibility fallback for older package layouts
    from pythonjsonlogger.jsonlogger import JsonFormatter

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_SENSITIVE_URL = re.compile(r"([?&](?:key|api_key|token|access_token|password)=)([^&\s\"']+)", re.IGNORECASE)


def redact_sensitive_text(text: str) -> str:
    """Remove segredos comuns de URLs em strings de log."""
    return _SENSITIVE_URL.sub(r"\1***", text)


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get() or ""
        return True


class RedactSecretsFilter(logging.Filter):
    """Evita vazamento de chaves em query string (ex.: Gemini key=) se algum logger escapar."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        redacted = redact_sensitive_text(msg)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def _quiet_noisy_loggers(*, for_worker: bool = False) -> None:
    """httpx/httpcore em INFO geram muito ruido; boto3 anuncia credenciais em INFO."""
    names = [
        "httpx",
        "httpcore",
        "urllib3",
        "openai",
        "sentence_transformers",
        "transformers",
    ]
    if for_worker:
        names.extend(
            [
                "boto3",
                "botocore",
                "s3transfer",
            ]
        )
    for name in names:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_correlation_id() -> str | None:
    return correlation_id_var.get()


def set_correlation_id(value: str | None) -> None:
    correlation_id_var.set(value)


def compact_error_message(exc: BaseException, max_len: int = 220) -> str:
    """
    Uma linha legivel, sem stack trace; evita vazar chaves de URL.
    Usado no lugar de logger.exception() em operacoes de LLM/HTTP comuns.
    """
    e: BaseException | None = exc
    for _ in range(6):
        if e is None:
            break
        if isinstance(e, httpx.HTTPStatusError):
            try:
                url = str(e.request.url) if e.request else ""
            except Exception:  # noqa: BLE001
                url = ""
            red = redact_sensitive_text(url) if url else ""
            if not red:
                red = "?"
            out = f"HTTP {e.response.status_code} {red}"[: max_len - 0]
            return out[:max_len]
        if isinstance(e, httpx.RequestError) and not isinstance(e, httpx.HTTPStatusError):
            return redact_sensitive_text(
                f"{e.__class__.__name__}: {str(e)[: min(150, max_len - 20)]}"
            )[:max_len]
        e = e.__cause__
    e = exc
    return redact_sensitive_text(f"{e.__class__.__name__}: {str(e)[: max_len - 20]}")[:max_len]


def configure_logging(
    level: str = "INFO",
    log_format: str = "json",
    *,
    for_worker: bool = False,
) -> None:
    """
    log_format:
      - json: uma linha JSON por evento (bom para agregadores)
      - text: linha legivel
    for_worker: colunas e nomes alinhados; reduz ainda mais ruido (boto3, etc.)
    """
    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler()
    handler.addFilter(CorrelationIdFilter())
    handler.addFilter(RedactSecretsFilter())

    fmt = (log_format or "json").strip().lower()
    if fmt == "text":
        if for_worker:
            handler.setFormatter(
                logging.Formatter(
                    fmt=(
                        "%(asctime)s  %(levelname)-5s  [%(correlation_id)-20s]  "
                        "%(short_logger)-22s| %(message)s"
                    ),
                    datefmt="%H:%M:%S",
                )
            )
            handler.addFilter(_ShortLoggerNameFilter())
        else:
            handler.setFormatter(
                logging.Formatter(
                    fmt="%(asctime)s | %(levelname)-5s | %(correlation_id)-16s | %(name)s | %(message)s",
                    datefmt="%H:%M:%S",
                )
            )
    else:
        handler.setFormatter(
            JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s %(correlation_id)s",
                rename_fields={
                    "asctime": "timestamp",
                    "levelname": "level",
                    "name": "module",
                },
            )
        )

    root.setLevel(level)
    root.addHandler(handler)
    _quiet_noisy_loggers(for_worker=for_worker)


class _ShortLoggerNameFilter(logging.Filter):
    """Encurta o nome do logger para o layout do worker (ultimo segmento)."""

    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name
        if name == "__main__":
            short = "sqs"
        elif name == "worker.sqs_consumer" or name.startswith("worker."):
            short = "sqs"
        else:
            short = name.rsplit(".", 1)[-1]
        if len(short) > 18:
            short = short[:17] + "..."
        record.short_logger = short  # type: ignore[attr-defined]
        return True

