"""
Consumer SQS — fica em loop com long polling na fila (sem ocupar CPU).

Antes: `alembic upgrade head`, .env com DATABASE_URL, Jira, LLM, SQS_QUEUE_URL, credenciais AWS.
Opcional: .env com WORKER_LOG_FORMAT=text (padrao) ou json.

Encerra com Ctrl+C (SIGINT) ou SIGTERM.

Cada corpo de mensagem deve conter {"chave_jira": "PROJ-123"}.
Reutiliza JiraFlowService.process_issue (mesma logica de process-flow).

Uso: na pasta `project`, com venv: `python -m worker.sqs_consumer`
"""

import json
import logging
import signal
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.config import Settings, get_settings
from utils.sqs_diagnostics import sqs_url_diagnostic
from utils.logging import compact_error_message, configure_logging, set_correlation_id
from models.database import SessionLocal, init_db
from embeddings.service import EmbeddingService
from ingestion.service import IngestionService
from jira.client import JiraClient
from jira.flow_service import JiraFlowService
from llm.service import LLMService
from retrieval.service import RetrievalService
from vector.factory import build_vector_store
from exceptions import (
    EmbeddingError,
    IngestionError,
    JiraClientError,
    JiraIssueNotFoundError,
    LLMError,
    RetrievalError,
)

logger = logging.getLogger(__name__)
# Linhas "de capa" do processo; modulos internos (jira, llm, etc.) usam o proprio name.
slog = logging.getLogger("worker.sqs")


def _make_sqs_client(settings: Settings):
    """
    Cria o cliente SQS. Se AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY estiverem
    no .env (pydantic), usa sessao explicita; senao, cadeia padrao (IAM role, env do SO, ~/.aws).
    """
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        k = settings.aws_access_key_id.get_secret_value().strip()
        s = settings.aws_secret_access_key.get_secret_value().strip()
        if k and s:
            session = boto3.Session(
                aws_access_key_id=k,
                aws_secret_access_key=s,
                region_name=settings.sqs_region,
            )
            return session.client("sqs")
    return boto3.client("sqs", region_name=settings.sqs_region)



class _ShutdownFlag:
    __slots__ = ("active",)

    def __init__(self) -> None:
        self.active = True

    def request_stop(self, signum, _frame) -> None:
        slog.info("Encerrando (sinal %s) apos a mensagem atual", signum)
        self.active = False


_shutdown = _ShutdownFlag()


def _build_flow_service() -> JiraFlowService:
    settings = get_settings()
    jira_client = JiraClient()
    embedding_service = EmbeddingService()
    vector_store = build_vector_store()
    llm_service = LLMService()
    retrieval_service = RetrievalService(
        top_k=settings.top_k_similar,
        min_score=settings.min_similarity_score,
        vector_store=vector_store,
    )
    ingestion_service = IngestionService(
        jira_client=jira_client,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )
    knowledge_statuses = settings.knowledge_base_statuses_list()

    return JiraFlowService(
        jira_client=jira_client,
        ingestion_service=ingestion_service,
        embedding_service=embedding_service,
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        allowed_statuses=knowledge_statuses,
    )


def _process_message(flow_service: JiraFlowService, body: dict) -> dict:
    chave_jira = body.get("chave_jira", "").strip()
    if not chave_jira:
        raise ValueError("Mensagem sem campo 'chave_jira'")

    set_correlation_id(chave_jira)

    db = SessionLocal()
    try:
        result = flow_service.process_issue(
            db,
            chave_jira,
            saudacao_publica=body.get("saudacao_publica", True),
            transicionar=body.get("transicionar", True),
            atribuir=body.get("atribuir", True),
            comentario_interno=body.get("comentario_interno", True),
            responsavel_account_id=body.get("responsavel_account_id", ""),
            nome_transicao=body.get("nome_transicao", ""),
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        set_correlation_id(None)


def _short_sqs_id(message_id: str) -> str:
    return (message_id[:12] + "...") if len(message_id) > 12 else message_id


def run() -> None:
    settings = get_settings()
    configure_logging(
        settings.log_level,
        settings.worker_log_format,
        for_worker=True,
    )

    if not settings.sqs_queue_url:
        slog.critical("SQS_QUEUE_URL nao definida. Encerrando.")
        sys.exit(1)

    if settings.auto_init_db:
        init_db()

    flow_service = _build_flow_service()

    sqs = _make_sqs_client(settings)
    use_explicit_aws = bool(
        settings.aws_access_key_id
        and settings.aws_secret_access_key
        and settings.aws_access_key_id.get_secret_value().strip()
        and settings.aws_secret_access_key.get_secret_value().strip()
    )
    queue_url = settings.sqs_queue_url

    slog.info(
        "Worker pronto | long polling %ss | regiao=%s | %s | credenciais=%s",
        settings.sqs_wait_time_seconds,
        settings.sqs_region,
        sqs_url_diagnostic(queue_url) if queue_url else "fila=?",
        "arquivo_ou_env" if use_explicit_aws else "cadeia_padrao_aws",
    )
    slog.info("Fila SQS (URL exata do ReceiveMessage): %s", queue_url)

    signal.signal(signal.SIGINT, _shutdown.request_stop)
    signal.signal(signal.SIGTERM, _shutdown.request_stop)

    consecutive_errors = 0
    max_backoff = 60

    # Loop continuo: escuta a fila ate SIGINT/SIGTERM (long polling, sem spin em CPU).
    while _shutdown.active:
        try:
            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=settings.sqs_max_messages,
                WaitTimeSeconds=settings.sqs_wait_time_seconds,
                VisibilityTimeout=settings.sqs_visibility_timeout,
            )
        except ClientError:
            consecutive_errors += 1
            wait = min(2**consecutive_errors, max_backoff)
            slog.error("Falha ao receber da fila; nova tentativa em %ss", wait, exc_info=True)
            time.sleep(wait)
            continue

        messages = response.get("Messages", [])
        if not messages:
            consecutive_errors = 0
            continue

        for message in messages:
            receipt_handle = message["ReceiptHandle"]
            message_id = message.get("MessageId", "?")

            try:
                body = json.loads(message["Body"])
            except (json.JSONDecodeError, KeyError):
                slog.error("JSON invalido, descartando | id=%s", _short_sqs_id(message_id))
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                continue

            chave = body.get("chave_jira", "?")
            slog.info(
                ">> %s | id=%s",
                chave,
                _short_sqs_id(message_id),
            )

            try:
                result = _process_message(flow_service, body)
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                slog.info(
                    "<< %s | fallback=%s | comentario=%s | saudacao=%s | trans=%s | atrib=%s | status=%s | id=%s",
                    chave,
                    result.get("fallback"),
                    result.get("comentario_interno"),
                    result.get("saudacao_publica"),
                    result.get("transicao_realizada"),
                    result.get("atribuicao_realizada"),
                    result.get("status_final", ""),
                    _short_sqs_id(message_id),
                )
                consecutive_errors = 0

            except JiraIssueNotFoundError:
                slog.warning(
                    "Ticket inexistente no Jira, descartando | %s | id=%s",
                    body.get("chave_jira", "?"),
                    _short_sqs_id(message_id),
                )
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)

            except ValueError:
                slog.exception("Mensagem invalida, descartando | id=%s", _short_sqs_id(message_id))
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)

            except (EmbeddingError, LLMError, IngestionError, RetrievalError, JiraClientError) as exc:
                consecutive_errors += 1
                ch = body.get("chave_jira", "?")
                if slog.isEnabledFor(logging.DEBUG):
                    slog.exception(
                        "Falha no fluxo; mensagem volta a fila | %s | id=%s",
                        ch,
                        _short_sqs_id(message_id),
                    )
                else:
                    slog.error(
                        "Falha no fluxo; mensagem volta a fila | %s | id=%s | %s",
                        ch,
                        _short_sqs_id(message_id),
                        compact_error_message(exc, max_len=280),
                    )

    slog.info("Worker encerrado.")


if __name__ == "__main__":
    run()
