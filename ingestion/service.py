import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy.orm import Session

from exceptions import IngestionError
from embeddings.service import EmbeddingService
from jira.client import JiraClient, normalize_issue
from models.repositories import sync_ticket_scope, upsert_analise, upsert_embedding, upsert_ticket
from processing.text_processing import classify_ticket_theme, consolidate_ticket_text, extract_problem_solution_context

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    processed: int = 0
    failed: int = 0
    ignored: int = 0


class IngestionService:
    def __init__(
        self,
        jira_client: JiraClient,
        embedding_service: EmbeddingService,
    ) -> None:
        self.jira_client = jira_client
        self.embedding_service = embedding_service

    def ingest_historical(self, db: Session, jql: str, max_results: int = 0) -> IngestionResult:
        issues = self.jira_client.search_issues(jql, max_results=max_results)
        normalized_issues = [normalize_issue(issue) for issue in issues]
        sync_ticket_scope(
            db,
            {issue.get("chave_jira", "") for issue in normalized_issues if issue.get("chave_jira")},
        )
        result = IngestionResult()
        for normalized in normalized_issues:
            if not normalized.get("chave_jira"):
                result.ignored += 1
                continue
            try:
                with db.begin_nested():
                    self.process_ticket_data(db, normalized)
                result.processed += 1
            except Exception:
                result.failed += 1
                logger.exception(
                    "ingestion_ticket_failed",
                    extra={"chave_jira": normalized.get("chave_jira", "")},
                )
                continue

        db.commit()
        logger.info(
            "Ingestao finalizada. processados=%s falhas=%s ignorados=%s",
            result.processed,
            result.failed,
            result.ignored,
        )
        return result

    def process_ticket_data(self, db: Session, ticket_data: dict) -> int:
        try:
            started_at = perf_counter()
            consolidated = consolidate_ticket_text(
                ticket_data.get("resumo", ""),
                ticket_data.get("descricao", ""),
                ticket_data.get("comentarios", ""),
                ticket_data.get("tema_chamado", ""),
            )
            consolidation_ms = round((perf_counter() - started_at) * 1000, 2)

            analysis_started = perf_counter()
            query_context = " ".join(
                part for part in [ticket_data.get("resumo", ""), ticket_data.get("descricao", ""), ticket_data.get("tema_chamado", "")] if part
            )
            problema, solucao, contexto = extract_problem_solution_context(consolidated)
            tema, subtema = classify_ticket_theme(
                query_context,
                query_context,
                ticket_data.get("comentarios", ""),
                ticket_data.get("produto", ""),
            )
            analysis_ms = round((perf_counter() - analysis_started) * 1000, 2)

            persistence_started = perf_counter()
            ticket = upsert_ticket(
                db,
                chave_jira=ticket_data.get("chave_jira", ""),
                resumo=ticket_data.get("resumo", ""),
                descricao=ticket_data.get("descricao", ""),
                comentarios=ticket_data.get("comentarios", ""),
                produto=ticket_data.get("produto", ""),
                status=ticket_data.get("status", ""),
                data_criacao=ticket_data.get("data_criacao") or datetime.now(timezone.utc),
                data_fechamento=ticket_data.get("data_fechamento"),
            )
            persistence_ms = round((perf_counter() - persistence_started) * 1000, 2)

            embedding_started = perf_counter()
            vector = self.embedding_service.embed(consolidated)
            upsert_embedding(db, ticket_id=ticket.id, vector=vector)
            embedding_ms = round((perf_counter() - embedding_started) * 1000, 2)

            upsert_analise(
                db,
                ticket_id=ticket.id,
                problema=problema,
                solucao=solucao,
                categoria=f"{tema}|{subtema}",
                confianca=0.7 if "resolvido" in contexto.lower() else 0.5,
            )

            db.flush()
            logger.info(
                "ingestion_ticket_processed",
                extra={
                    "chave_jira": ticket_data.get("chave_jira", ""),
                    "consolidation_ms": consolidation_ms,
                    "analysis_ms": analysis_ms,
                    "persistence_ms": persistence_ms,
                    "embedding_ms": embedding_ms,
                },
            )
            return ticket.id
        except Exception as exc:
            raise IngestionError(f"Falha ao processar ticket {ticket_data.get('chave_jira', '')}") from exc
