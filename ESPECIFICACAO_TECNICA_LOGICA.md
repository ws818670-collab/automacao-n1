# Especificação Técnica e Lógica

## 1. Objetivo do Sistema

Este projeto implementa um backend de Inteligência de Conhecimento para operação N1 com foco em:

- Triagem automática de chamados Jira (acionada pelo consumer SQS).
- Sugestão de comentário interno para atendentes N1.
- Recuperação de conhecimento por similaridade semântica e sinais léxicos/taxonômicos.
- Ingestão de histórico por JQL (ferramentas em `tools/`) e importação de bases curadas.

Escopo atual: MVP funcional orientado a operação assistida (não resposta automática ao cliente final).

## 2. Visão Arquitetural

Arquitetura em camadas, com separação por domínio técnico:

- Worker (`worker/sqs_consumer.py`): consome AWS SQS e executa o fluxo Jira (`JiraFlowService`).
- Ingestion: processa tickets e persiste dados derivados.
- Processing: consolidação textual, heurísticas de problema/solução, classificação de tema.
- Embeddings: geração vetorial local/OpenAI e adaptação de dimensão.
- Retrieval: ranking híbrido (vetorial + léxico + taxonomia + intenção + título + produto).
- LLM: geração de comentário de triagem via Amazon Bedrock com fallback heurístico.
- Jira: integração REST para leitura de issues e postagem de comentário interno.
- Models: persistência SQLAlchemy; PostgreSQL opcional com extensão `vector` quando aplicável.
- Tools: scripts operacionais para exportação e importação de bases.

## 3. Estrutura de Módulos e Responsabilidades

### 3.1 Inicialização e Configuração

- worker/sqs_consumer.py
  - Long polling na fila SQS.
  - Monta serviços (Jira, embeddings, retrieval, LLM, ingestion) e chama `JiraFlowService.process_issue`.
  - Opcional: `init_db()` quando `AUTO_INIT_DB=true`.
  - Logging via `utils.logging` (`WORKER_LOG_FORMAT`).

- utils/config.py
  - Define Settings via pydantic-settings.
  - Centraliza variáveis de ambiente e defaults.

- utils/logging.py
  - Configuração base de logging e `correlation_id` por mensagem (chave Jira).

### 3.2 Persistência

- models/database.py
  - Engine SQLAlchemy.
  - Sessão DB.
  - CREATE EXTENSION vector.
  - create_all das entidades.
  - Migração simples para coluna produto.

- models/entities.py
  - Entidades:
    - tickets
    - embeddings
    - analises

- models/repositories.py
  - Upsert de ticket, embedding e análise.
  - Busca de similares por distância coseno.
  - Sincronização de escopo com remoção de tickets fora da base selecionada.

### 3.3 Ingestão e Processamento

- ingestion/service.py
  - ingest_historical por JQL.
  - process_ticket_data com pipeline completo.

- processing/text_processing.py
  - clean_text e consolidate_ticket_text.
  - extract_problem_solution_context (heurística).
  - classify_ticket_theme e infer_query_theme.

### 3.4 Similaridade e Geração de Conteúdo

- embeddings/service.py
  - Embedding local com sentence-transformers.
  - Embedding OpenAI.
  - Fallback determinístico lexical (desenvolvimento).
  - Adaptação de dimensão para 1536.

- retrieval/service.py
  - Busca híbrida e threshold dinâmico.
  - Filtragem de ruído e priorização taxonômica.

- llm/service.py
  - Geração de comentário de triagem (análise Jira).
  - Amazon Bedrock (Converse API).
  - Fallback estruturado quando LLM indisponível.

### 3.5 Integração Jira

- jira/client.py
  - Busca paginada de issues (estratégia moderna + fallback legado).
  - Leitura de issue por chave.
  - Postagem de comentário interno em ADF.
  - Normalização de issue para modelo interno.
  - Extração de campo produto configurável ou autodetectado.

### 3.6 Ferramentas Operacionais

- tools/export_jql_to_csv.py
  - Exporta base Jira para CSV de curadoria.
  - Pode gerar resumo via Gemini ou heurística.

- tools/import_curated_xlsx.py
  - Importa chave curada de planilha XLSX.
  - Reingere tickets e sincroniza escopo.

- tools/import_ai_curated_csv.py
  - Importa CSV com resumo IA como texto-base de conhecimento.

## 4. Modelo de Dados

### 4.1 Entidades

1. tickets
- id: PK
- chave_jira: único
- resumo, descricao, comentarios
- produto
- status
- data_criacao, data_fechamento

2. embeddings
- ticket_id: PK e FK para tickets
- embedding_vector: vector(1536)

3. analises
- ticket_id: PK e FK para tickets
- problema
- solucao
- categoria (tema|subtema)
- confianca

### 4.2 Relacionamentos

- Ticket 1:1 Embedding
- Ticket 1:1 Analise

### 4.3 Estratégia de Persistência

- Upsert lógico por chave_jira.
- Flush em etapas para garantir IDs antes de dependências.
- Commit no nível de caso de uso.

## 5. Fluxos Lógicos Principais

### 5.1 Mensagem SQS → Fluxo Jira (`JiraFlowService.process_issue`)

1. Worker recebe mensagem JSON da fila (mínimo: `chave_jira`).
2. Busca a issue no Jira; normaliza e ingere (`process_ticket_data`: texto, problema/solução, tema, embedding, análise).
3. Opcional: comentário público de saudação (Service Desk), transição de workflow, atribuição — conforme flags da mensagem e `.env`.
4. Se `comentario_interno`: retrieval de similares, geração de nota de triagem (LLM ou fallback), postagem de comentário **interno** no Jira.
5. Commit (ou rollback em erro); mensagem deletada da fila em sucesso; erros recuperáveis devolvem a mensagem à fila após o visibility timeout.

### 5.2 Ingestão histórica em lote

- Realizada por `ingestion/service.py` (JQL) acionada pelos scripts em `tools/`, não pelo worker SQS.

## 6. Contrato da fila (SQS)

Corpo JSON mínimo (fluxo completo de triagem):

```json
{"chave_jira": "PROJ-123"}
```

Perfil de retorno Avalara (comentário interno + transição para `Analise JDMS`, sem LLM/ingestão):

```json
{
  "chave_jira": "JDMSN1-2222",
  "bodyDoEmail": "Testando automação"
}
```

Quando `bodyDoEmail` está presente e não vazio, o worker publica comentário interno prefixado com `Comentário Avalara` e transiciona o chamado; saudação, atribuição e triagem LLM não são executadas.

Campos opcionais do fluxo completo (alinhados ao `process_issue`): por exemplo `saudacao_publica`, `transicionar`, `atribuir`, `comentario_interno`, `responsavel_account_id`, `nome_transicao`.

Permissões AWS típicas do consumidor: `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes` (conforme política da conta).

## 7. Configuração e Execução

### 7.1 Dependências

- SQLAlchemy, Alembic; `psycopg2-binary` opcional (PostgreSQL).
- boto3 (SQS), OpenAI SDK, httpx.
- sentence-transformers + torch para embedding local.
- openpyxl para planilhas (tools).

### 7.2 Variáveis de Ambiente Críticas

- DATABASE_URL
- JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN
- Credenciais AWS (Bedrock) e OPENAI_API_KEY se EMBEDDING_PROVIDER=openai
- EMBEDDING_PROVIDER e LLM_PROVIDER
- KNOWLEDGE_BASE_JQL e KNOWLEDGE_BASE_STATUSES
- JIRA_POST_COMMENTS
- SQS_QUEUE_URL, SQS_REGION e credenciais/IAM para a fila

### 7.3 Implantacao

- Worker Python na VM (venv, Agendador de Tarefas Windows ou equivalente); o repositorio nao inclui Dockerfile nem compose.
- Banco: SQLite em arquivo local ou PostgreSQL instalado/gerenciado fora deste projeto, conforme `DATABASE_URL`.

## 8. Segurança e Governança Técnica

### 8.1 Pontos positivos

- Segredos via variáveis de ambiente.
- Comentários no Jira marcados como internos.
- Queries SQL via ORM.

### 8.2 Riscos e lacunas

1. Superficie de ataque concentrada na VM (`.env`, IAM da instância, acesso à fila SQS); não há API HTTP no produto.
2. Sem rate limiting explícito nas integrações Jira/LLM.
3. Validação do corpo da mensagem SQS é mínima (JSON e campos esperados).
4. Tratamento amplo de exceções pode esconder causa raiz.
5. Sem política explícita de mascaramento de dados sensíveis nos logs.

## 9. Observabilidade

Estado atual:
- Logging básico centralizado.
- Sem métricas técnicas nativas (latência, taxa de erro, uso de tokens).
- Sem tracing distribuído.

Recomendado:
- Logs estruturados em JSON (`WORKER_LOG_FORMAT=json`).
- Métricas e alertas no processo worker (CloudWatch ou agente local), se necessário.
- Correlation-id por mensagem (chave Jira) já propagado nos logs.
- SLI/SLO definidos para tempo de processamento por mensagem e taxa de erro na fila (DLQ).

## 10. Avaliação de Melhores Práticas

### 10.1 Aderências observadas

1. Boa separação de responsabilidades por módulo.
2. Configuração centralizada em settings.
3. Modelo de dados simples e coeso para RAG.
4. Fallbacks definidos para LLM e embedding.
5. Integração Jira com estratégia de fallback de paginação.

### 10.2 Não conformidades / oportunidades

Prioridade Alta:
1. Proteger superfície operacional (acesso à VM, rotação de segredos, política IAM mínima na fila).
2. Expandir testes automatizados (unitário e integração dos serviços usados pelo worker).
3. Validar e limitar tamanho/complexidade do JSON da mensagem SQS onde fizer sentido.

Prioridade Média:
1. Melhorar resiliência externa (retry com backoff e circuit breaker para Jira/LLM).
2. Parametrizar timeouts e pool de conexão DB por ambiente.
3. Introduzir migrações formais (Alembic) no lugar de migração ad-hoc.

Prioridade Baixa:
1. Versionamento semântico do pacote worker e changelog.
2. Padronizar linters/formatters e pipeline CI.
3. DLQ e alarmes na fila SQS para mensagens problemáticas.

## 11. Checklist de Conformidade para Validação

Use este checklist para validar se o projeto está alinhado com melhores práticas:

Arquitetura
- [ ] Módulos com responsabilidade única.
- [ ] Dependências entre camadas sem acoplamento cíclico.

Segurança
- [ ] Acesso à VM e ao `.env` restrito; IAM com permissão mínima na fila.
- [ ] Segredos não expostos em logs.

Dados
- [ ] Migrações versionadas (Alembic).
- [ ] Índices adequados para consultas críticas.
- [ ] Estratégia de backup e restore documentada.

Confiabilidade
- [ ] Retry/backoff para Jira e LLM.
- [ ] Timeouts configuráveis por ambiente.
- [ ] Política de degradação graciosa documentada.

Qualidade
- [ ] Testes unitários cobrindo regras de negócio centrais.
- [ ] Testes de integração para persistência e fluxos sem Jira real (mocks).
- [ ] Validação do payload SQS e contratos internos entre serviços.

Operação
- [ ] Logs estruturados e centralizados.
- [ ] Métricas e alertas para disponibilidade e erro.
- [ ] Runbook operacional para incidentes comuns.

## 12. Roadmap de Melhoria Recomendado

Fase 1 (curto prazo)
1. Testes automatizados e CI.
2. Validação de payload SQS e política IAM mínima.
3. Logs estruturados com correlação por `chave_jira`.

Fase 2 (médio prazo)
1. Alembic + estratégia de versionamento de schema.
2. Observabilidade com métricas e tracing.
3. Hardening de integração externa com circuit breaker.

Fase 3 (evolução)
1. Filas assíncronas para ingestão massiva.
2. Estratégias de avaliação offline de qualidade do retrieval.
3. Governança de prompts e versionamento de modelos.

---

## Conclusão

O projeto está bem estruturado para um MVP de assistência N1 orientado a fila, com modularização clara e pipeline de ingestão, retrieval e geração de texto. Para produção, priorizar segurança da VM e da fila, testes automatizados, observabilidade do worker e governança de schema (Alembic) e integrações externas (Jira/LLM).