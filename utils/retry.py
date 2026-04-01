import logging

import httpx
from tenacity import before_sleep_log, retry, retry_if_exception, stop_after_attempt, wait_exponential

from exceptions import EmbeddingError, JiraClientError, LLMError
from utils.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


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
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )