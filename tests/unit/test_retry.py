"""Unit tests for utils/retry.py — verifies _should_retry() decisions and that
external_retry() causes tenacity to re-invoke the decorated function on transient
errors while giving up on permanent ones."""

import sys
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# _should_retry predicate
# ---------------------------------------------------------------------------

def test_should_retry_on_timeout(configured_env):
    from utils.retry import _should_retry

    assert _should_retry(httpx.ConnectTimeout("timeout")) is True
    assert _should_retry(httpx.ReadTimeout("timeout")) is True


def test_should_retry_on_429(configured_env):
    from utils.retry import _should_retry

    response = httpx.Response(429, request=httpx.Request("GET", "http://x"))
    exc = httpx.HTTPStatusError("429", request=response.request, response=response)
    assert _should_retry(exc) is True


def test_should_retry_on_503(configured_env):
    from utils.retry import _should_retry

    response = httpx.Response(503, request=httpx.Request("GET", "http://x"))
    exc = httpx.HTTPStatusError("503", request=response.request, response=response)
    assert _should_retry(exc) is True


def test_no_retry_on_404(configured_env):
    from utils.retry import _should_retry

    response = httpx.Response(404, request=httpx.Request("GET", "http://x"))
    exc = httpx.HTTPStatusError("404", request=response.request, response=response)
    assert _should_retry(exc) is False


def test_no_retry_on_400(configured_env):
    from utils.retry import _should_retry

    response = httpx.Response(400, request=httpx.Request("GET", "http://x"))
    exc = httpx.HTTPStatusError("400", request=response.request, response=response)
    assert _should_retry(exc) is False


def test_should_retry_wrapped_in_domain_error(configured_env):
    """Transient cause wrapped in a domain error should still trigger retry."""
    from exceptions import LLMError
    from utils.retry import _should_retry

    timeout = httpx.ReadTimeout("timeout")
    wrapped = LLMError("llm fail")
    wrapped.__cause__ = timeout

    assert _should_retry(wrapped) is True


# ---------------------------------------------------------------------------
# Decorator behaviour: counts that tenacity retries on transient errors
# ---------------------------------------------------------------------------

def test_external_retry_retries_n_times_on_timeout(configured_env, monkeypatch):
    """external_retry() should invoke the decorated function RETRY_MAX_ATTEMPTS times
    before re-raising the exception.  We patch settings to keep the test fast."""
    import utils.retry as retry_mod
    from utils.config import get_settings

    settings = get_settings()
    # Override max attempts via monkeypatch to 3 (default may differ)
    monkeypatch.setattr(settings, "retry_max_attempts", 3)
    monkeypatch.setattr(settings, "retry_backoff_seconds", 0)
    monkeypatch.setattr(retry_mod, "settings", settings)

    call_count = 0

    @retry_mod.external_retry()
    def always_timeout():
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("timeout")

    with pytest.raises(httpx.ReadTimeout):
        always_timeout()

    assert call_count == 3


def test_external_retry_does_not_retry_on_permanent_error(configured_env, monkeypatch):
    """external_retry() must NOT retry on 400 Bad Request."""
    import utils.retry as retry_mod
    from utils.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "retry_max_attempts", 3)
    monkeypatch.setattr(settings, "retry_backoff_seconds", 0)
    monkeypatch.setattr(retry_mod, "settings", settings)

    call_count = 0
    response = httpx.Response(400, request=httpx.Request("GET", "http://x"))

    @retry_mod.external_retry()
    def bad_request():
        nonlocal call_count
        call_count += 1
        raise httpx.HTTPStatusError("400", request=response.request, response=response)

    with pytest.raises(httpx.HTTPStatusError):
        bad_request()

    assert call_count == 1  # no retry
