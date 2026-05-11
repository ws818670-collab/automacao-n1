import logging
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from exceptions import EmbeddingError, JiraClientError, LLMError
from utils.config import get_settings
from utils.logging import compact_error_message

settings = get_settings()
logger = logging.getLogger(__name__)


def _before_sleep(retry_state: Any) -> None:
    if not retry_state.outcome or not retry_state.outcome.failed:
        return
    exc = retry_state.outcome.exception()
    if exc is None:
        return
    sleep = float(getattr(retry_state, "upcoming_sleep", 0.0) or 0.0)
    logger.info(
        "Proxima tentativa em %ss (tentativa %s/%s): %s",
        round(sleep, 1),
        retry_state.attempt_number,
        settings.retry_max_attempts,
        compact_error_message(exc, max_len=180),
    )


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, (JiraClientError, LLMError, EmbeddingError)) and exc.__cause__ is not None:
        return _should_retry(exc.__cause__)
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


def external_retry():
    return retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(multiplier=settings.retry_backoff_seconds, min=1, max=30),
        retry=retry_if_exception(_should_retry),
        before_sleep=_before_sleep,
        reraise=True,
    )