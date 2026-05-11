from utils.logging import redact_sensitive_text


def test_redact_strips_key_query_param() -> None:
    url = "https://example.com/v1?key=SECRET123&other=1"
    assert "SECRET123" not in redact_sensitive_text(url)
    assert "key=***" in redact_sensitive_text(url)


def test_redact_unchanged_when_no_secrets() -> None:
    s = "https://jira.net/rest/api/3/issue/ABC-1"
    assert redact_sensitive_text(s) == s
