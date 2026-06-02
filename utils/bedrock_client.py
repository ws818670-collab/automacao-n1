"""Cliente Amazon Bedrock Runtime (mesma cadeia de credenciais do SQS)."""

from __future__ import annotations

import boto3

from utils.config import Settings


def bedrock_region(settings: Settings) -> str:
    explicit = (settings.bedrock_region or "").strip()
    if explicit:
        return explicit
    return (settings.sqs_region or "us-east-1").strip() or "us-east-1"


def make_bedrock_runtime_client(settings: Settings):
    region = bedrock_region(settings)
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        access_key = settings.aws_access_key_id.get_secret_value().strip()
        secret_key = settings.aws_secret_access_key.get_secret_value().strip()
        if access_key and secret_key:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
            )
            return session.client("bedrock-runtime")
    return boto3.client("bedrock-runtime", region_name=region)
