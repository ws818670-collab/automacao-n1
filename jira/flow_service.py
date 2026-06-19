import logging
from typing import Any

from sqlalchemy.orm import Session

from embeddings.service import EmbeddingService
from exceptions import JiraIssueNotFoundError
from ingestion.service import IngestionService
from jira.client import JiraClient, normalize_issue
from llm.service import LLMService
from retrieval.service import RetrievalService
from utils.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_EMAIL_BODY_COMMENT_PREFIX = "Comentário Avalara"
_EMAIL_BODY_MAX_CHARS = 9000


class JiraFlowService:
    def __init__(
        self,
        jira_client: JiraClient,
        ingestion_service: IngestionService,
        embedding_service: EmbeddingService,
        retrieval_service: RetrievalService,
        llm_service: LLMService,
        allowed_statuses: list[str],
    ) -> None:
        self.jira_client = jira_client
        self.ingestion_service = ingestion_service
        self.embedding_service = embedding_service
        self.retrieval_service = retrieval_service
        self.llm_service = llm_service
        self.allowed_statuses = allowed_statuses

    def process_email_body_reply(self, issue_key: str, body_do_email: str) -> dict[str, Any]:
        """Comentario interno com retorno Avalara e transicao para Analise JDMS (sem LLM/ingestao)."""
        issue_key = issue_key.strip()
        raw_issue = self.jira_client.get_issue(issue_key)
        if raw_issue is None:
            raise JiraIssueNotFoundError(f"Ticket {issue_key} nao encontrado no Jira")

        comment_body = self._build_email_body_comment(body_do_email)
        self.jira_client.post_comment_direct(issue_key, comment_body)

        transition_name = (settings.jira_triage_transition_name or "").strip() or "Analise JDMS"
        transition_done = self.jira_client.transition_issue(issue_key, transition_name=transition_name)
        transition_motive = "realizada" if transition_done else "ja_no_status"

        refreshed_issue = self.jira_client.get_issue(issue_key) or raw_issue
        fields = refreshed_issue.get("fields", {})
        status = fields.get("status") or {}

        return {
            "chave_jira": issue_key,
            "saudacao_publica": False,
            "saudacao_motivo": "desativada",
            "transicao_realizada": transition_done,
            "transicao_motivo": transition_motive,
            "transicao_destino": transition_name,
            "atribuicao_realizada": False,
            "atribuicao_motivo": "desativada",
            "comentario_interno": True,
            "comentario_motivo": "realizada",
            "status_final": status.get("name", ""),
            "responsavel_final": (fields.get("assignee") or {}).get("displayName", ""),
            "tickets_relacionados": [],
            "fallback": False,
        }

    def process_issue(
        self,
        db: Session,
        issue_key: str,
        *,
        saudacao_publica: bool = True,
        transicionar: bool = True,
        atribuir: bool = True,
        comentario_interno: bool = True,
        responsavel_account_id: str = "",
        nome_transicao: str | None = "",
    ) -> dict[str, Any]:
        issue_key = issue_key.strip()
        raw_issue = self.jira_client.get_issue(issue_key)
        if raw_issue is None:
            raise JiraIssueNotFoundError(f"Ticket {issue_key} nao encontrado no Jira")

        normalized = normalize_issue(raw_issue)
        self.ingestion_service.process_ticket_data(db, normalized)

        request_id = self.jira_client.extract_request_id(raw_issue)
        reporter_name = self.jira_client.extract_reporter_first_name(raw_issue)
        public_comment_done = False
        public_comment_motive = "desativada"

        if saudacao_publica and request_id:
            public_message = self._build_public_greeting(issue_key, reporter_name)
            self.jira_client.post_public_comment(request_id, public_message)
            public_comment_done = True
            public_comment_motive = "realizada"
        elif saudacao_publica:
            public_comment_motive = "request_id_ausente"
            logger.warning(
                "jira_public_comment_skipped",
                extra={"chave_jira": issue_key, "reason": "request_id_not_found"},
            )

        transition_name = (
            (nome_transicao or "").strip()
            or (settings.jira_triage_transition_name or "").strip()
            or "Analise JDMS"
        )
        transition_done = False
        transition_motive = "desativada"
        if transicionar and transition_name:
            transition_done = self.jira_client.transition_issue(issue_key, transition_name=transition_name)
            transition_motive = "realizada" if transition_done else "ja_no_status"
        elif transicionar:
            transition_motive = "sem_nome_transicao"

        effective_assignee_id = (
            (responsavel_account_id or "").strip()
            or (settings.jira_default_assignee_id or "").strip()
        )
        assignment_done = False
        assignment_motive = "desativada"
        if atribuir and effective_assignee_id:
            self.jira_client.assign_issue(issue_key, effective_assignee_id)
            assignment_done = True
            assignment_motive = "realizada"
        elif atribuir:
            assignment_motive = "responsavel_nao_configurado"
            logger.warning(
                "jira_assignment_skipped",
                extra={"chave_jira": issue_key, "reason": "assignee_not_configured"},
            )

        referenced_tickets: list[str] = []
        fallback_used = False
        internal_comment_done = False
        internal_comment_motive = "desativada"
        if comentario_interno:
            _comment, referenced_tickets, fallback_used = self.llm_service.generate_triage_comment(
                db,
                issue_key,
                self.jira_client,
                self.embedding_service,
                self.retrieval_service,
                self.allowed_statuses,
                post=True,
            )
            internal_comment_done = True
            internal_comment_motive = "realizada"

        refreshed_issue = self.jira_client.get_issue(issue_key) or raw_issue
        fields = refreshed_issue.get("fields", {})
        assignee = fields.get("assignee") or {}
        status = fields.get("status") or {}

        return {
            "chave_jira": issue_key,
            "saudacao_publica": public_comment_done,
            "saudacao_motivo": public_comment_motive,
            "transicao_realizada": transition_done,
            "transicao_motivo": transition_motive,
            "transicao_destino": transition_name if transicionar else "",
            "atribuicao_realizada": assignment_done,
            "atribuicao_motivo": assignment_motive,
            "comentario_interno": internal_comment_done,
            "comentario_motivo": internal_comment_motive,
            "status_final": status.get("name", ""),
            "responsavel_final": assignee.get("displayName", ""),
            "tickets_relacionados": referenced_tickets,
            "fallback": fallback_used,
        }

    @staticmethod
    def _build_public_greeting(issue_key: str, reporter_name: str) -> str:
        first_name = (reporter_name or "Equipe").strip().split()[0]
        templates = [
            "Olá, {nome}!\n\nTudo certo?\n\nJá recebi seu chamado por aqui e o time já está avaliando. Aviso assim que tiver novidades!",
            "Olá, {nome}?\n\nTudo bem?\n\nPassando para avisar que seu chamado já está sendo analisado pelo nosso time.",
            "Olá, {nome}! Tudo bem por aí?\n\nJá estamos com seu chamado e vamos verificar, daremos um retorno em breve.",
            "Tudo bem, {nome}?\n\nRecebemos seu chamado!\n\nJá estamos investigando os detalhes para te ajudar o quanto antes.",
            "Oi, {nome}!\n\nPassando para dizer que já iniciamos a análise do seu chamado. Em breve daremos retorno!",
            "Olá, {nome}!\n\nTudo certinho?\n\nSeu chamado foi registrado e já está na nossa fila de análise.\n\nFalamos em breve!",
            "Oi, {nome}!\n\nObrigado por entrar em contato.\n\nJá estamos analisando tudo para resolver sua questão.",
            "Tudo certo, {nome}?\n\nJá estamos conferindo seu chamado. Logo traremos atualizações!",
            "Oi, {nome}!\n\nRecebido!\n\nVamos dar uma olhada no que está acontecendo e te posicionamos sobre os próximos passos.",
            "Olá, {nome}!\n\nComo vão as coisas?\n\nJá iniciamos a análise do seu chamado, logo daremos retorno.",
            "Olá, {nome}!\n\nValeu por reportar.\n\nJá estamos verificando os pontos que você mandou e logo te respondo.",
            "Oi, {nome}!\n\nTudo bem?\n\nSeu chamado já entrou em triagem por aqui. Retornamos em breve!",
            "Tudo bem, {nome}?\n\nPassando para confirmar que já estamos analisando seu caso. Até já!",
            "Oi, {nome}!\n\nO time já está analisando seu chamado para te dar um retorno em breve.",
            "Olá, {nome}!\n\nTudo bem?\n\nJá estamos com seu chamado e a equipe já está acompanhando, logo daremos retorno.",
        ]
        template = templates[sum(ord(ch) for ch in issue_key) % len(templates)]
        return template.format(nome=first_name)

    @staticmethod
    def _build_email_body_comment(body_do_email: str) -> str:
        body = (body_do_email or "").strip()
        if len(body) > _EMAIL_BODY_MAX_CHARS:
            body = body[:_EMAIL_BODY_MAX_CHARS].rstrip() + "\n\n[texto truncado]"
        return f"{_EMAIL_BODY_COMMENT_PREFIX}\n\n{body or '[sem conteudo textual]'}"
