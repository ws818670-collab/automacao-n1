class ProjectError(Exception):
    """Base para erros de dominio do projeto."""


class ConfigurationError(ProjectError):
    """Erro de configuracao obrigatoria ausente ou invalida."""


class JiraClientError(ProjectError):
    """Falha na comunicacao com o Jira."""


class JiraIssueNotFoundError(JiraClientError):
    """Issue nao localizada no Jira."""


class EmbeddingError(ProjectError):
    """Falha ao gerar embedding."""


class LLMError(ProjectError):
    """Falha na chamada ao provedor de LLM."""


class IngestionError(ProjectError):
    """Falha no pipeline de ingestao."""


class RetrievalError(ProjectError):
    """Falha na busca de similares."""