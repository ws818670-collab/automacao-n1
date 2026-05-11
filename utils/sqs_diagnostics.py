"""Resumo SQS para logs (URL completa e emitida no worker)."""

from urllib.parse import urlparse


def sqs_url_diagnostic(url: str) -> str:
    """Conta + nome da fila, para cruzar com o console AWS."""
    try:
        p = urlparse(url)
        parts = [s for s in p.path.split("/") if s]
        if len(parts) >= 2:
            return f"account_id={parts[0]} | fila={parts[-1]}"
    except Exception:
        pass
    return "fila=?"
