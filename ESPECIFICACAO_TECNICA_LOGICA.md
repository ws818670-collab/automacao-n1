# Especificação Técnica e Lógica

## 1. Objetivo do Sistema

Este projeto implementa um backend de Inteligência de Conhecimento para operação N1 com foco em:

- Triagem automática de chamados Jira.
- Sugestão de comentário interno para atendentes N1.
- Recuperação de conhecimento por similaridade semântica e sinais léxicos/taxonômicos.
- Consulta de base histórica por chatbot.
- Ingestão de histórico por JQL e importação de bases curadas.

Escopo atual: MVP funcional orientado a operação assistida (não resposta automática ao cliente final).

## 2. Visão Arquitetural

Arquitetura em camadas, com separação por domínio técnico:

- API: expõe endpoints FastAPI e coordena casos de uso.
- Ingestion: processa tickets e persiste dados derivados.
- Processing: consolidação textual, heurísticas de problema/solução, classificação de tema.
- Embeddings: geração vetorial local/OpenAI e adaptação de dimensão.
- Retrieval: ranking híbrido (vetorial + léxico + taxonomia + intenção + título + produto).
- LLM: geração de análise e resposta de chat com fallback heurístico.
- Jira: integração REST para leitura de issues e postagem de comentário interno.
- Models: persistência SQLAlchemy e consultas vetoriais via pgvector.
- Tools: scripts operacionais para exportação e importação de bases.

## 3. Estrutura de Módulos e Responsabilidades

### 3.1 Inicialização e Configuração

- main.py
  - Inicializa aplicação FastAPI.
  - Registra rotas.
  - Configura logging.
  - Executa init_db no startup.

- utils/config.py
  - Define Settings via pydantic-settings.
  - Centraliza variáveis de ambiente e defaults.

- utils/logging.py
  - Configuração base de logging.

### 3.2 API

- api/routes.py
  - GET /health
  - POST /jira/webhook
  - POST /chat/query
  - GET /jira/analyze-preview
  - POST /jira/analyze-and-post
  - POST /jira/ingest

- api/schemas.py
  - Schemas de request/response com Pydantic.

### 3.3 Persistência

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

### 3.4 Ingestão e Processamento

- ingestion/service.py
  - ingest_historical por JQL.
  - process_ticket_data com pipeline completo.

- processing/text_processing.py
  - clean_text e consolidate_ticket_text.
  - extract_problem_solution_context (heurística).
  - classify_ticket_theme e infer_query_theme.

### 3.5 Similaridade e Geração de Conteúdo

- embeddings/service.py
  - Embedding local com sentence-transformers.
  - Embedding OpenAI.
  - Fallback determinístico lexical (desenvolvimento).
  - Adaptação de dimensão para 1536.

- retrieval/service.py
  - Busca híbrida e threshold dinâmico.
  - Filtragem de ruído e priorização taxonômica.

- llm/service.py
  - Geração de comentário de triagem e resposta de chat.
  - Suporte a Gemini/OpenAI/auto.
  - Fallback estruturado quando LLM indisponível.

### 3.6 Integração Jira

- jira/client.py
  - Busca paginada de issues (estratégia moderna + fallback legado).
  - Leitura de issue por chave.
  - Postagem de comentário interno em ADF.
  - Normalização de issue para modelo interno.
  - Extração de campo produto configurável ou autodetectado.

### 3.7 Ferramentas Operacionais

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

### 5.1 Webhook Jira para Triagem

1. Recebe payload em POST /jira/webhook.
2. Consolida texto, extrai problema/solução/contexto.
3. Classifica tema/subtema.
4. Upsert ticket + embedding + análise.
5. Executa retrieval de similares.
6. Gera comentário de triagem (LLM ou fallback).
7. Publica comentário interno no Jira (se habilitado).
8. Commit da transação.

### 5.2 Consulta de Chat

1. Recebe pergunta em POST /chat/query.
2. Gera embedding da pergunta.
3. Busca similares no retrieval híbrido.
4. Gera resposta sintetizada por LLM/fallback.
5. Retorna resposta e tickets relacionados.

### 5.3 Preview de Análise sem Postagem

1. GET /jira/analyze-preview com chave_jira.
2. Busca issue atual no Jira.
3. Normaliza campos e gera embedding.
4. Recupera similares.
5. Gera texto de triagem e retorna preview.

### 5.4 Análise com Postagem

1. POST /jira/analyze-and-post com chave_jira.
2. Executa pipeline de preview.
3. Posta comentário interno via API Jira.
4. Retorna comentário e referências.

### 5.5 Ingestão Histórica

1. POST /jira/ingest com JQL (query ou configuração).
2. Busca issues paginadas.
3. Processa cada issue.
4. Sincroniza escopo (remove fora da seleção).
5. Commit e retorno de contagem.

## 6. API (Contrato Funcional)

1. GET /health
- Objetivo: saúde do serviço.
- Resposta: status e mensagem.

2. POST /jira/webhook
- Objetivo: ingestão incremental + triagem.
- Entrada: chave, resumo, descrição, comentários, produto, status, datas.
- Saída: confirmação de processamento.

3. POST /chat/query
- Objetivo: consulta semântica com resposta textual.
- Entrada: pergunta.
- Saída: resposta + lista de tickets relacionados.

4. GET /jira/analyze-preview
- Objetivo: gerar nota sem publicar.
- Entrada: chave_jira.
- Saída: comentário proposto + referências.

5. POST /jira/analyze-and-post
- Objetivo: gerar e publicar comentário interno.
- Entrada: chave_jira.
- Saída: comentário publicado + referências.

6. POST /jira/ingest
- Objetivo: ingestão em lote por JQL.
- Entrada: jql, max_results.
- Saída: total processado.

## 7. Configuração e Execução

### 7.1 Dependências

- FastAPI, Uvicorn, SQLAlchemy, pgvector, psycopg2.
- OpenAI SDK.
- sentence-transformers + torch para embedding local.
- openpyxl para planilhas.

### 7.2 Variáveis de Ambiente Críticas

- DATABASE_URL
- JIRA_BASE_URL
- JIRA_EMAIL
- JIRA_API_TOKEN
- GEMINI_API_KEY e/ou OPENAI_API_KEY
- EMBEDDING_PROVIDER e LLM_PROVIDER
- KNOWLEDGE_BASE_JQL e KNOWLEDGE_BASE_STATUSES
- JIRA_POST_COMMENTS

### 7.3 Docker

- Dockerfile para API Python 3.11.
- docker-compose com:
  - db: pgvector/pg16
  - api: FastAPI

## 8. Segurança e Governança Técnica

### 8.1 Pontos positivos

- Segredos via variáveis de ambiente.
- Comentários no Jira marcados como internos.
- Queries SQL via ORM.

### 8.2 Riscos e lacunas

1. Ausência de autenticação/autorização na API.
2. Sem rate limiting.
3. Sem validação de tamanho de payloads.
4. Tratamento amplo de exceções pode esconder causa raiz.
5. Sem política explícita de mascaramento de dados sensíveis nos logs.

## 9. Observabilidade

Estado atual:
- Logging básico centralizado.
- Sem métricas técnicas nativas (latência, taxa de erro, uso de tokens).
- Sem tracing distribuído.

Recomendado:
- Logs estruturados em JSON.
- Métricas Prometheus.
- Correlation-id por request.
- Dashboard de SLI/SLO para endpoints críticos.

## 10. Avaliação de Melhores Práticas

### 10.1 Aderências observadas

1. Boa separação de responsabilidades por módulo.
2. Configuração centralizada em settings.
3. Modelo de dados simples e coeso para RAG.
4. Fallbacks definidos para LLM e embedding.
5. Integração Jira com estratégia de fallback de paginação.

### 10.2 Não conformidades / oportunidades

Prioridade Alta:
1. Implementar autenticação na API e proteção de endpoints administrativos.
2. Criar suíte de testes automatizados (unitário, integração e contrato).
3. Implementar limites e validações de entrada (tamanho, campos obrigatórios contextuais).

Prioridade Média:
1. Melhorar resiliência externa (retry com backoff e circuit breaker para Jira/LLM).
2. Parametrizar timeouts e pool de conexão DB por ambiente.
3. Introduzir migrações formais (Alembic) no lugar de migração ad-hoc.

Prioridade Baixa:
1. Definir versionamento semântico da API.
2. Incluir documentação OpenAPI com exemplos de erro/sucesso reais.
3. Padronizar linters/formatters e pipeline CI.

## 11. Checklist de Conformidade para Validação

Use este checklist para validar se o projeto está alinhado com melhores práticas:

Arquitetura
- [ ] Módulos com responsabilidade única.
- [ ] Dependências entre camadas sem acoplamento cíclico.

Segurança
- [ ] Endpoints protegidos por autenticação.
- [ ] Limite de requisições por cliente.
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
- [ ] Testes de integração para endpoints críticos.
- [ ] Validação de schemas de entrada e saída.

Operação
- [ ] Logs estruturados e centralizados.
- [ ] Métricas e alertas para disponibilidade e erro.
- [ ] Runbook operacional para incidentes comuns.

## 12. Roadmap de Melhoria Recomendado

Fase 1 (curto prazo)
1. Testes automatizados e CI.
2. Autenticação, rate limiting e validação de payload.
3. Logs estruturados com correlação de request.

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

O projeto está bem estruturado para um MVP de assistência N1, com boas decisões de modularização e pipeline funcional de ingestão, retrieval e geração de texto. Para aderência robusta a melhores práticas de produção, os principais avanços devem focar em segurança de API, testes automatizados, observabilidade e governança de mudanças de banco e integrações externas.