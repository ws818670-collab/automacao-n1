from utils.sqs_diagnostics import sqs_url_diagnostic


def test_sqs_url_diagnostic_parses_standard_queue_url() -> None:
    url = "https://sqs.us-east-1.amazonaws.com/123456789012/JiraAutomation"
    assert sqs_url_diagnostic(url) == "account_id=123456789012 | fila=JiraAutomation"


def test_sqs_url_diagnostic_invalid_returns_fallback() -> None:
    assert sqs_url_diagnostic("") == "fila=?"
