from datetime import datetime

from pydantic import BaseModel, Field, field_validator

ISSUE_KEY_PATTERN = r"^[A-Z][A-Z0-9_]*-\d+$"


class JiraWebhookPayload(BaseModel):
    chave_jira: str = Field(..., description="Chave do ticket no Jira", max_length=50, pattern=ISSUE_KEY_PATTERN)
    resumo: str = Field(default="", max_length=500)
    descricao: str = Field(default="", max_length=10000)
    comentarios: str = Field(default="", max_length=10000)
    produto: str = Field(default="", max_length=255)
    status: str = Field(default="", max_length=255)
    data_criacao: datetime | None = None
    data_fechamento: datetime | None = None

    @field_validator("chave_jira", "resumo", "descricao", "comentarios", "produto", "status", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ChatQueryRequest(BaseModel):
    pergunta: str = Field(min_length=3, max_length=1000)

    @field_validator("pergunta")
    @classmethod
    def _validate_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("pergunta nao pode ser vazia")
        return cleaned


class AnalyzeRequest(BaseModel):
    chave_jira: str = Field(..., max_length=50, pattern=ISSUE_KEY_PATTERN)

    @field_validator("chave_jira")
    @classmethod
    def _validate_issue_key(cls, value: str) -> str:
        return value.strip()


class IngestRequest(BaseModel):
    jql: str = Field(default="", max_length=2000)
    max_results: int = Field(default=100, ge=1, le=500)

    @field_validator("jql")
    @classmethod
    def _validate_jql(cls, value: str) -> str:
        return value.strip()


class ChatQueryResponse(BaseModel):
    resposta: str
    tickets_relacionados: list[str]
    fallback: bool = False


class GenericResponse(BaseModel):
    status: str
    message: str


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: datetime


class JiraCommentPreviewResponse(BaseModel):
    chave_jira: str
    comentario: str
    tickets_relacionados: list[str]
    fallback: bool = False
