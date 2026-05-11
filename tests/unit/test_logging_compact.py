import httpx

from utils.logging import compact_error_message, redact_sensitive_text


def test_redact_api_key_in_url() -> None:
    t = "https://example.com/v1?key=SECRET123&other=1"
    assert "SECRET" not in redact_sensitive_text(t)
    assert "key=***" in redact_sensitive_text(t)


def test_compact_httpstatus_redacts() -> None:
    req = httpx.Request("GET", "https://x.com/api?key=ABC123")
    resp = httpx.Response(503, request=req)
    err = httpx.HTTPStatusError("u", request=req, response=resp)
    out = compact_error_message(err)
    assert "ABC123" not in out
    assert "503" in out


def test_compact_generic() -> None:
    out = compact_error_message(ValueError("algo deu errado"), max_len=100)
    assert "ValueError" in out
    assert "algo" in out
