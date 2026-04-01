import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.schemas import AnalyzeRequest, ChatQueryRequest, ChatQueryResponse, GenericResponse, HealthResponse, IngestRequest, JiraCommentPreviewResponse, JiraWebhookPayload
from exceptions import EmbeddingError, IngestionError, JiraClientError, JiraIssueNotFoundError, LLMError, RetrievalError
from embeddings.service import EmbeddingService
from ingestion.service import IngestionService
from jira.client import JiraClient
from llm.service import LLMService
from models.database import get_db
from retrieval.service import RetrievalService
from utils.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

jira_client = JiraClient()
embedding_service = EmbeddingService()
llm_service = LLMService()
retrieval_service = RetrievalService(
    top_k=settings.top_k_similar,
    min_score=settings.min_similarity_score,
)
ingestion_service = IngestionService(jira_client=jira_client, embedding_service=embedding_service)
knowledge_statuses = settings.knowledge_base_statuses_list()


@router.get("/health", response_model=HealthResponse)
def healthcheck() -> HealthResponse:
    return HealthResponse(status="ok", version=settings.app_version, timestamp=datetime.now(timezone.utc))


@router.post("/jira/webhook", response_model=GenericResponse)
def jira_webhook(payload: JiraWebhookPayload, db: Session = Depends(get_db)) -> GenericResponse:
    try:
        ticket_id = ingestion_service.process_ticket_data(db, payload.model_dump())

        consolidated = "\n\n".join([payload.resumo, payload.descricao, payload.comentarios]).strip()
        query_vector = embedding_service.embed(consolidated)
        similares = retrieval_service.find_similar(
            db,
            query_vector,
            top_k=settings.top_k_similar,
            exclude_ticket_key=payload.chave_jira,
            allowed_statuses=knowledge_statuses,
            query_text=f"{payload.resumo} {payload.descricao}",
            query_produto=payload.produto,
        )

        comentario, _fallback = llm_service.generate_jira_analysis_comment(
            resumo=payload.resumo,
            descricao=payload.descricao,
            similares=similares,
            produto=payload.produto,
        )

        jira_client.create_internal_comment(payload.chave_jira, comentario)
        db.commit()

        return GenericResponse(
            status="ok",
            message=f"Ticket processado com sucesso (ticket_id={ticket_id})",
        )
    except (EmbeddingError, LLMError, IngestionError, RetrievalError, JiraClientError) as exc:
        db.rollback()
        logger.exception("Erro ao processar webhook Jira")
        raise HTTPException(status_code=500, detail=f"Erro interno: {exc}") from exc


@router.post("/chat/query", response_model=ChatQueryResponse)
def chat_query(payload: ChatQueryRequest, db: Session = Depends(get_db)) -> ChatQueryResponse:
    try:
        resposta, tickets, fallback = llm_service.chat_query(
            db,
            payload.pergunta,
            embedding_service,
            retrieval_service,
            knowledge_statuses,
        )
        return ChatQueryResponse(resposta=resposta, tickets_relacionados=tickets, fallback=fallback)
    except (EmbeddingError, LLMError, RetrievalError) as exc:
        logger.exception("Erro ao consultar chatbot")
        raise HTTPException(status_code=500, detail=f"Erro interno: {exc}") from exc


@router.get("/jira/analyze-preview", response_model=JiraCommentPreviewResponse)
def analyze_preview(
    payload: Annotated[AnalyzeRequest, Depends()],
    db: Session = Depends(get_db),
) -> JiraCommentPreviewResponse:
    """Gera a nota de triagem para um ticket existente no Jira sem postar o comentario."""
    if not jira_client.is_configured():
        raise HTTPException(status_code=503, detail="Jira client nao configurado")

    try:
        comentario, tickets_ref, fallback = llm_service.generate_triage_comment(
            db,
            payload.chave_jira,
            jira_client,
            embedding_service,
            retrieval_service,
            knowledge_statuses,
            post=False,
        )
    except JiraIssueNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (JiraClientError, LLMError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JiraCommentPreviewResponse(chave_jira=payload.chave_jira, comentario=comentario, tickets_relacionados=tickets_ref, fallback=fallback)


@router.post("/jira/analyze-and-post", response_model=JiraCommentPreviewResponse)
def analyze_and_post(
    payload: Annotated[AnalyzeRequest, Depends()],
    db: Session = Depends(get_db),
) -> JiraCommentPreviewResponse:
    """Gera a nota de triagem e posta como comentario interno no ticket Jira."""
    if not jira_client.is_configured():
        raise HTTPException(status_code=503, detail="Jira client nao configurado")

    try:
        comentario, tickets_ref, fallback = llm_service.generate_triage_comment(
            db,
            payload.chave_jira,
            jira_client,
            embedding_service,
            retrieval_service,
            knowledge_statuses,
            post=True,
        )
        logger.info("Comentario postado em %s", payload.chave_jira)
    except JiraIssueNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (JiraClientError, LLMError) as exc:
        logger.exception("Falha ao postar comentario em %s", payload.chave_jira)
        raise HTTPException(status_code=502, detail=f"Comentario gerado, mas falha ao postar: {exc}") from exc

    return JiraCommentPreviewResponse(chave_jira=payload.chave_jira, comentario=comentario, tickets_relacionados=tickets_ref, fallback=fallback)


@router.post("/jira/ingest", response_model=GenericResponse)
def ingest_historical(payload: IngestRequest, db: Session = Depends(get_db)) -> GenericResponse:
    try:
        effective_jql = payload.jql.strip() or settings.knowledge_base_jql.strip()
        if not effective_jql:
            raise HTTPException(status_code=400, detail="Informe jql ou configure KNOWLEDGE_BASE_JQL")

        result = ingestion_service.ingest_historical(db, jql=effective_jql, max_results=payload.max_results)
        return GenericResponse(
            status="ok",
            message=(
                f"Ingestao concluida: processados={result.processed}, "
                f"falhas={result.failed}, ignorados={result.ignored}"
            ),
        )
    except (IngestionError, JiraClientError, EmbeddingError) as exc:
        db.rollback()
        logger.exception("Erro na ingestao historica")
        raise HTTPException(status_code=500, detail=f"Erro interno: {exc}") from exc
