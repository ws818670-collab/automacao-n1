from functools import lru_cache
from pathlib import Path
from typing import Literal
from typing_extensions import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Caminho fixo: nao depender do CWD (Task Scheduler, NSSM, etc. comecam em System32).
_PROJECT_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE_PATH = _PROJECT_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_ENV_FILE_PATH),),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="dev", alias="APP_ENV")
    auto_init_db: bool = Field(default=True, alias="AUTO_INIT_DB")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    # Worker SQS: padrao `text` (legivel). `json` = uma linha JSON por evento.
    worker_log_format: Literal["json", "text"] = Field(default="text", alias="WORKER_LOG_FORMAT")

    database_url: str = Field(alias="DATABASE_URL")
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    qdrant_url: str = Field(default="", alias="QDRANT_URL")
    qdrant_api_key: SecretStr | None = Field(default=None, alias="QDRANT_API_KEY")
    qdrant_collection: str = Field(default="jira_ticket_embeddings", alias="QDRANT_COLLECTION")
    embedding_dimension: int = Field(default=1536, alias="EMBEDDING_DIMENSION")
    top_k_similar: int = Field(default=5, alias="TOP_K_SIMILAR")
    min_similarity_score: float = Field(default=0.75, alias="MIN_SIMILARITY_SCORE")
    knowledge_base_jql: str = Field(default="", alias="KNOWLEDGE_BASE_JQL")
    knowledge_base_statuses: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="KNOWLEDGE_BASE_STATUSES")

    jira_base_url: str = Field(alias="JIRA_BASE_URL")
    jira_email: str = Field(alias="JIRA_EMAIL")
    jira_api_token: SecretStr = Field(alias="JIRA_API_TOKEN")
    jira_project_key: str = Field(default="", alias="JIRA_PROJECT_KEY")
    jira_post_comments: bool = Field(default=False, alias="JIRA_POST_COMMENTS")
    # ID do campo customizado "produto" no Jira (ex: customfield_10200).
    # Deixe vazio para deteccao automatica por varredura de campos.
    jira_product_field: str = Field(default="", alias="JIRA_PRODUCT_FIELD")
    # ID do campo customizado "tema do chamado" no Jira (ex: customfield_10201).
    # Deixe vazio para deteccao automatica por heuristica textual.
    jira_theme_field: str = Field(default="", alias="JIRA_THEME_FIELD")
    jira_default_assignee_id: str = Field(default="", alias="JIRA_DEFAULT_ASSIGNEE_ID")
    jira_triage_transition_name: str = Field(default="Analise JDMS", alias="JIRA_TRIAGE_TRANSITION_NAME")

    email_imap_host: str = Field(default="", alias="EMAIL_IMAP_HOST")
    email_imap_port: int = Field(default=993, alias="EMAIL_IMAP_PORT")
    email_imap_username: str = Field(default="", alias="EMAIL_IMAP_USERNAME")
    email_imap_password: SecretStr | None = Field(default=None, alias="EMAIL_IMAP_PASSWORD")
    email_imap_folder: str = Field(default="INBOX", alias="EMAIL_IMAP_FOLDER")
    email_allowed_senders: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="EMAIL_ALLOWED_SENDERS")
    email_poll_interval_seconds: int = Field(default=30, alias="EMAIL_POLL_INTERVAL_SECONDS")
    email_max_messages_per_poll: int = Field(default=20, alias="EMAIL_MAX_MESSAGES_PER_POLL")
    email_mark_as_seen: bool = Field(default=True, alias="EMAIL_MARK_AS_SEEN")
    email_triage_transition_name: str = Field(default="Analise JDMS", alias="EMAIL_TRIAGE_TRANSITION_NAME")

    # Microsoft Graph API (substitui IMAP — Auth Delegada via Device Code Flow)
    graph_tenant_id: str = Field(default="", alias="GRAPH_TENANT_ID")
    graph_client_id: str = Field(default="", alias="GRAPH_CLIENT_ID")
    graph_mailbox: str = Field(default="", alias="GRAPH_MAILBOX")
    graph_refresh_token: str = Field(default="", alias="GRAPH_REFRESH_TOKEN")

    sqs_queue_url: str = Field(default="", alias="SQS_QUEUE_URL")
    sqs_region: str = Field(default="us-east-1", alias="SQS_REGION")
    sqs_wait_time_seconds: int = Field(default=20, alias="SQS_WAIT_TIME_SECONDS")
    sqs_max_messages: int = Field(default=1, alias="SQS_MAX_MESSAGES")
    sqs_visibility_timeout: int = Field(default=300, alias="SQS_VISIBILITY_TIMEOUT")
    # Opcional: mesmas chaves que apps .NET costumam usar. Se vazias, boto3 usa IAM Role da instancia ou ~/.aws.
    aws_access_key_id: SecretStr | None = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: SecretStr | None = Field(default=None, alias="AWS_SECRET_ACCESS_KEY")

    llm_provider: Literal["bedrock"] = Field(default="bedrock", alias="LLM_PROVIDER")
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    bedrock_model: str = Field(default="amazon.nova-lite-v1:0", alias="BEDROCK_MODEL")
    bedrock_region: str = Field(default="", alias="BEDROCK_REGION")
    embedding_provider: Literal["local", "openai"] = Field(default="local", alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    local_embedding_model: str = Field(
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        alias="LOCAL_EMBEDDING_MODEL",
    )
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    external_timeout_seconds: int = Field(default=30, alias="EXTERNAL_TIMEOUT_SECONDS")
    retry_max_attempts: int = Field(default=3, alias="RETRY_MAX_ATTEMPTS")
    retry_backoff_seconds: float = Field(default=1.0, alias="RETRY_BACKOFF_SECONDS")
    retrieval_vector_weight: float = Field(default=0.20, alias="RETRIEVAL_VECTOR_WEIGHT")
    retrieval_lexical_weight: float = Field(default=0.20, alias="RETRIEVAL_LEXICAL_WEIGHT")
    retrieval_taxonomy_weight: float = Field(default=0.20, alias="RETRIEVAL_TAXONOMY_WEIGHT")
    retrieval_intent_weight: float = Field(default=0.15, alias="RETRIEVAL_INTENT_WEIGHT")
    retrieval_title_weight: float = Field(default=0.10, alias="RETRIEVAL_TITLE_WEIGHT")
    retrieval_product_weight: float = Field(default=0.15, alias="RETRIEVAL_PRODUCT_WEIGHT")
    n1_role_description: str = Field(
        default=(
            "Voce atua como assistente do time N1 de suporte Avalara/JDMS. "
            "O N1 e responsavel pelo primeiro nivel de atendimento dos produtos: "
            "Avatax BR (calculo e mensageria fiscal), "
            "Tax Compliance (relatorios, obrigacoes acessorias, auditorias, integracoes), "
            "Taxdocs Monitor (captura de NF-e, CT-e, NFS-e) e "
            "Tax Central (calendario de obrigacoes e tributos). "
            "Responsabilidades do N1: "
            "(1) Triagem — classificar o chamado como duvida funcional, erro de operacao, problema tecnico ou configuracao; "
            "(2) Duvidas funcionais — responder diretamente sem acionar N2; "
            "(3) Reproducao — solicitar logs, prints, XML, parametros e reproduzir o cenario antes de escalar; "
            "(4) Escalonamento qualificado — escalar ao N2 somente quando confirmado bug, falha sistemica ou necessidade de engenharia, "
            "sempre enviando: cenario reproduzido, evidencias, logs, passos realizados, impacto e ambiente/versao; "
            "(5) Postura investigativa — o N1 nao e repassador de chamados; pergunta, investiga, reproduz, valida e documenta. "
            "Criterio de indicacao: "
            "'Resolver no N1' quando ha solucao clara na base e e possivel orientar o cliente diretamente; "
            "'Avaliar com especialista' quando o cenario e parcialmente conhecido ou requer validacao adicional; "
            "'Encaminhar N2' quando confirmado bug, falha sistemica, sem precedente na base ou cliente ja seguiu orientacoes sem sucesso."
        ),
        alias="N1_ROLE_DESCRIPTION",
    )

    @field_validator("knowledge_base_statuses", mode="before")
    @classmethod
    def _parse_statuses(cls, value: object) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value).strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
            return [item.strip().strip('"\'') for item in text.split(",") if item.strip().strip('"\'')]
        return [item.strip() for item in text.split("|") if item.strip()]

    @field_validator("email_allowed_senders", mode="before")
    @classmethod
    def _parse_email_senders(cls, value: object) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        text = str(value).strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
            return [item.strip().strip('"\'').lower() for item in text.split(",") if item.strip().strip('"\'')]
        return [item.strip().lower() for item in text.split("|") if item.strip()]

    @model_validator(mode="after")
    def _validate_provider_configuration(self) -> "Settings":
        has_openai = bool(self.openai_api_key and self.openai_api_key.get_secret_value().strip())

        if self.embedding_provider == "openai" and not has_openai:
            raise ValueError("OPENAI_API_KEY obrigatoria quando EMBEDDING_PROVIDER=openai")

        if self.uses_qdrant() and not self.qdrant_api_key_value():
            raise ValueError("QDRANT_API_KEY obrigatoria quando QDRANT_URL estiver definida")

        total_weight = (
            self.retrieval_vector_weight
            + self.retrieval_lexical_weight
            + self.retrieval_taxonomy_weight
            + self.retrieval_intent_weight
            + self.retrieval_title_weight
            + self.retrieval_product_weight
        )
        if total_weight <= 0:
            raise ValueError("Os pesos de retrieval devem somar valor positivo")

        return self

    def knowledge_base_statuses_list(self) -> list[str]:
        return list(self.knowledge_base_statuses)

    def jira_api_token_value(self) -> str:
        return self.jira_api_token.get_secret_value()

    def email_imap_password_value(self) -> str:
        return self.email_imap_password.get_secret_value() if self.email_imap_password else ""

    def openai_api_key_value(self) -> str:
        return self.openai_api_key.get_secret_value() if self.openai_api_key else ""

    def qdrant_api_key_value(self) -> str:
        return self.qdrant_api_key.get_secret_value() if self.qdrant_api_key else ""

    def uses_qdrant(self) -> bool:
        return bool(self.qdrant_url.strip())

    def gemini_api_key_value(self) -> str:
        return self.gemini_api_key.get_secret_value() if self.gemini_api_key else ""

    def has_aws_credentials(self) -> bool:
        if not self.aws_access_key_id or not self.aws_secret_access_key:
            return False
        return bool(
            self.aws_access_key_id.get_secret_value().strip()
            and self.aws_secret_access_key.get_secret_value().strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
