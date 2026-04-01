import logging
from contextvars import ContextVar

try:
    from pythonjsonlogger.json import JsonFormatter
except ImportError:  # Compatibility fallback for older package layouts
    from pythonjsonlogger.jsonlogger import JsonFormatter

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get() or ""
        return True


def get_correlation_id() -> str | None:
    return correlation_id_var.get()


def set_correlation_id(value: str | None) -> None:
    correlation_id_var.set(value)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(CorrelationIdFilter())
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

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)
