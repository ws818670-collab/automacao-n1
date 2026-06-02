"""Cliente Bedrock Runtime: credenciais explicitas vs cadeia padrao boto3."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from utils.bedrock_client import bedrock_region, make_bedrock_runtime_client
from utils.config import Settings


def _min_settings(overrides: dict) -> Settings:
    base = {
        "DATABASE_URL": "sqlite:///:memory:",
        "JIRA_BASE_URL": "https://x.atlassian.net",
        "JIRA_EMAIL": "a@b.com",
        "JIRA_API_TOKEN": "t",
    }
    return Settings(**{**base, **overrides})


def test_bedrock_region_prefers_explicit() -> None:
    s = _min_settings({"BEDROCK_REGION": "eu-west-1", "SQS_REGION": "us-east-1"})
    assert bedrock_region(s) == "eu-west-1"


def test_bedrock_region_falls_back_to_sqs() -> None:
    s = _min_settings({"SQS_REGION": "sa-east-1"})
    assert bedrock_region(s) == "sa-east-1"


def test_make_bedrock_client_without_explicit_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "")
    s = _min_settings({"SQS_REGION": "us-east-1"})
    with patch("utils.bedrock_client.boto3") as mock_boto3:
        mock_boto3.client.return_value = MagicMock()
        client = make_bedrock_runtime_client(s)
        mock_boto3.client.assert_called_once_with("bedrock-runtime", region_name="us-east-1")
        assert client is mock_boto3.client.return_value


def test_make_bedrock_client_uses_session_when_keys_set() -> None:
    s = _min_settings(
        {
            "SQS_REGION": "us-east-1",
            "AWS_ACCESS_KEY_ID": SecretStr("AKIA123"),
            "AWS_SECRET_ACCESS_KEY": SecretStr("shhh"),
        }
    )
    with patch("utils.bedrock_client.boto3") as mock_boto3:
        session_instance = mock_boto3.Session.return_value
        session_instance.client.return_value = MagicMock()
        client = make_bedrock_runtime_client(s)
        mock_boto3.Session.assert_called_once_with(
            aws_access_key_id="AKIA123",
            aws_secret_access_key="shhh",
            region_name="us-east-1",
        )
        session_instance.client.assert_called_once_with("bedrock-runtime")
        assert client is session_instance.client.return_value
