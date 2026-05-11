"""Cliente SQS: credenciais explicitas (Settings) vs cadeia padrao boto3."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from utils.config import Settings, get_settings
from worker.sqs_consumer import _make_sqs_client


def _min_settings(overrides: dict) -> Settings:
    base = {
        "DATABASE_URL": "sqlite:///:memory:",
        "JIRA_BASE_URL": "https://x.atlassian.net",
        "JIRA_EMAIL": "a@b.com",
        "JIRA_API_TOKEN": "t",
    }
    return Settings(**{**base, **overrides})


def test_make_sqs_client_uses_boto3_client_without_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Env do SO (e, em alguns testes, o .env do disco) vence; zerar evita Sessao explicita.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "")
    s = _min_settings({"SQS_REGION": "sa-east-1"})
    with patch("worker.sqs_consumer.boto3") as mock_boto3:
        mock_boto3.client.return_value = MagicMock()
        c = _make_sqs_client(s)
        mock_boto3.client.assert_called_once_with("sqs", region_name="sa-east-1")
        mock_boto3.Session.assert_not_called()
        assert c is mock_boto3.client.return_value


def test_make_sqs_client_uses_session_when_both_secrets_set() -> None:
    s = _min_settings(
        {
            "SQS_REGION": "us-east-1",
            "AWS_ACCESS_KEY_ID": SecretStr("AKIA123"),
            "AWS_SECRET_ACCESS_KEY": SecretStr("shhh"),
        }
    )
    with patch("worker.sqs_consumer.boto3") as mock_boto3:
        session_instance = mock_boto3.Session.return_value
        session_instance.client.return_value = MagicMock()
        c = _make_sqs_client(s)
        mock_boto3.Session.assert_called_once_with(
            aws_access_key_id="AKIA123",
            aws_secret_access_key="shhh",
            region_name="us-east-1",
        )
        session_instance.client.assert_called_once_with("sqs")
        assert c is session_instance.client.return_value


def test_settings_loads_aws_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("JIRA_BASE_URL", "https://x.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "a@b.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "t")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "from-env")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "from-env-secret")
    get_settings.cache_clear()
    st = get_settings()
    assert st.aws_access_key_id is not None
    assert st.aws_access_key_id.get_secret_value() == "from-env"
    get_settings.cache_clear()
