# Sistema de Inteligencia de Conhecimento com Jira (MVP)

Backend em FastAPI para:
- Automacao N1 via webhook Jira com comentario interno sugerido
- Chatbot de consulta baseado em historico de chamados

## Stack
- Python + FastAPI
- PostgreSQL + pgvector
- Jira REST API
- OpenAI (embeddings + LLM)
- Docker

## Estrutura

```text
project/
├── ingestion/
├── processing/
├── embeddings/
├── retrieval/
├── llm/
├── jira/
├── api/
├── models/
├── utils/
├── main.py
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## Configuracao
1. Copie `.env.example` para `.env`
2. Preencha credenciais Jira e OpenAI

## Execucao com Docker

```bash
docker compose up --build
```

API disponivel em `http://localhost:8000`.

## Endpoints

### 1) Webhook Jira
`POST /jira/webhook`

Exemplo de payload:

```json
{
  "chave_jira": "SUP-123",
  "resumo": "Erro ao fechar pedido",
  "descricao": "Usuario informa falha ao finalizar.",
  "comentarios": "Logs indicam timeout no servico X",
  "status": "Aberto"
}
```

### 2) Chatbot
`POST /chat/query`

Entrada:

```json
{
  "pergunta": "Como resolver erro de timeout no fechamento de pedido?"
}
```

Saida:

```json
{
  "resposta": "texto formatado",
  "tickets_relacionados": ["SUP-10", "SUP-22"]
}
```

### 3) Ingestao historica
`POST /jira/ingest?jql=project=SUP ORDER BY created DESC&max_results=100`

## Regras implementadas no MVP
- Consolidacao textual: resumo + descricao + comentarios
- Extracao heuristica de problema e solucao
- Similaridade vetorial via pgvector
- Comentario interno Jira gerado por LLM com fallback
- Chatbot com resposta estruturada e tickets de referencia

## Observacoes
- O sistema nao responde cliente final automaticamente
- As sugestoes sao apoio ao analista N1
- Sem chave OpenAI, o sistema usa fallback local para desenvolvimento
