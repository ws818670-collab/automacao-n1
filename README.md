# Sistema de Inteligencia de Conhecimento com Jira (MVP)

Worker Python que consome **AWS SQS** e executa o fluxo de automacao N1 no Jira (triagem, comentario interno sugerido via LLM, etc.). Nao ha servidor HTTP neste repositorio.

Tambem inclui um worker de **retorno por e-mail (IMAP)** para capturar respostas da Avalara e atualizar chamados automaticamente no Jira.

## Quick start

1. **Python 3.11 ou 3.12 (64 bits)** — veja [Versao do Python](#versao-do-python-importante-no-windows) se precisar de detalhes no Windows.
2. No terminal, entre na pasta **`project`** (onde estao `worker/`, `requirements.txt` e o `.env`).
3. `cp` / copie `.env.example` para `.env` e preencha Jira, LLM, SQS e AWS (minimo: `SQS_QUEUE_URL` e acesso a fila).
4. Crie o venv, instale dependencias e aplique migracoes:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python -m alembic upgrade head
   ```
5. Inicie o worker: `python -m worker.sqs_consumer` (ou `.\scripts\run-sqs-worker.ps1` no Windows). Encerre com `Ctrl+C`.

Detalhes de banco, agendador na EC2 e testes: secoes [Configuracao](#configuracao-uma-vez), [Inicializacao](#inicializacao-padrao-windows--ec2) e [Rodar o consumer SQS](#rodar-o-consumer-sqs).

## Stack
- Python
- SQLite (arquivo local; vetores em JSON, similaridade calculada em Python)
- Jira REST API
- Amazon Bedrock (LLM de triagem) e embeddings locais (sentence-transformers) ou OpenAI quando configurado
- AWS SQS (consumer dedicado)

## Versao do Python (importante no Windows)

Use **Python 3.12.x ou 3.11.x, 64 bits** (instalador em [python.org](https://www.python.org/downloads/)).

- **Evite Python 3.14** (ou “latest”) na EC2 com Windows: `numpy`, `torch`, `psycopg2-binary` costumam **nao ter wheel** ainda; o `pip` tenta compilar e exige **Visual Studio Build Tools** e varios percalcos.
- Se voce ja criou a `.venv` com 3.14, instale 3.12, apague a pasta `.venv`, recrie o venv e rode `pip install -r requirements.txt` de novo.

Verifique: `python --version` → deve mostrar 3.12.x ou 3.11.x.

## Estrutura

```text
project/
├── ingestion/
├── processing/
├── embeddings/
├── retrieval/
├── llm/
├── jira/
├── worker/              # consumer SQS (recebe chave do chamado)
├── models/
├── utils/
├── requirements.txt
└── requirements-postgres.txt  # so se usar PostgreSQL
```

## Configuracao (uma vez)

1. Copie `.env.example` para `.env`.
2. Ajuste `DATABASE_URL` (veja abaixo).
3. Preencha credenciais **Jira**, **LLM Bedrock** (`BEDROCK_MODEL` + modelo habilitado no console), **SQS** (`SQS_QUEUE_URL`, `SQS_REGION`, etc.) e **AWS** (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, IAM Role na EC2 ou `aws configure`).

**Banco local (recomendado, sem servidor de banco):**

```env
DATABASE_URL=sqlite:///./knowledge.db
```

O arquivo `knowledge.db` e criado na pasta `project` apos as migracoes.

**PostgreSQL (opcional):** use `DATABASE_URL=postgresql+psycopg2://...` e instale o driver: `pip install -r requirements-postgres.txt`. O `psycopg2-binary` nao entra no `requirements.txt` principal (evita falha de build no Windows com Python 3.14 quando so se usa SQLite). Com Python 3.11/3.12 costuma instalar via wheel sem compilar. O esquema e o mesmo; nao e necessario extensao `vector` no servidor.

## Inicializacao (padrao: Windows / EC2)

Use o terminal na pasta `project` (onde estao `worker/` e o `.env`). Crie e ative um venv, depois instale dependencias e aplique migracoes.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m alembic upgrade head
```

No Windows, prefira `python -m alembic` em vez de `alembic` sozinho: o executavel costuma ficar fora do `PATH` ate voce ativar o venv (`.\.venv\Scripts\Activate.ps1`).

### Rodar o consumer SQS

```bash
python -m worker.sqs_consumer
```

O processo fica em loop (long polling) ate `Ctrl+C`. Requer `SQS_QUEUE_URL`, regiao e permissao na fila (ex.: `ReceiveMessage`, `DeleteMessage`).

No Windows pode usar: `.\scripts\run-sqs-worker.ps1`.

### Rodar o worker de e-mail (retorno Avalara)

Esse worker monitora a caixa IMAP configurada, extrai a chave do chamado Jira do assunto/corpo do e-mail (ex.: `JDMSN1-2720`), publica um comentario interno no chamado e transiciona para `Analise JDMS`.

Configurar no `.env`:

```env
EMAIL_IMAP_HOST=imap.seudominio.com
EMAIL_IMAP_PORT=993
EMAIL_IMAP_USERNAME=seu.usuario@dominio.com
EMAIL_IMAP_PASSWORD=sua-senha-ou-app-password
EMAIL_IMAP_FOLDER=INBOX
EMAIL_ALLOWED_SENDERS=suporte@avalara.com|noreply@avalara.com
EMAIL_POLL_INTERVAL_SECONDS=30
EMAIL_MAX_MESSAGES_PER_POLL=20
EMAIL_MARK_AS_SEEN=true
EMAIL_TRIAGE_TRANSITION_NAME=Analise JDMS
```

Executar:

```bash
python -m worker.email_consumer
```

No Windows tambem pode usar: `.\scripts\run-email-worker.ps1`.

**Logs:** o worker usa `WORKER_LOG_FORMAT` (padrao `text`, colunas alinhadas). Para JSON (agregadores), defina `WORKER_LOG_FORMAT=json`.

**Testes:** `python -m pytest tests/ -q`

### Agendador de Tarefas (EC2 / Windows) — worker sempre rodando e apos reinicio

Nao e necessario um unico `.exe` (com torch/embeddings fica inviavel). O padrao e **tarefa agendada** + **Python do venv** + pasta fixa com `.env` e `knowledge.db`.

**1) Preparar (uma vez)**  
Na maquina: `alembic upgrade head`, `pip install -r requirements.txt` no venv, `.env` com `SQS_QUEUE_URL` e o resto. Anote o caminho absoluto da pasta `project` (se tiver acentos/espacos, use o caminho exato, entre aspas quando precisar).

**2) Criar a tarefa (automatico, recomendado)**  
PowerShell **como o mesmo usuario** que usara a VM (dono do projeto, na pasta `project`):

```powershell
# Opcao A — apos fazer logon (simples: ao abrir RDP, inicia o worker)
.\scripts\Register-SqsWorkerTask.ps1

# Opcao B — na inicializacao do computador (com 60s de atraso para rede subir)
.\scripts\Register-SqsWorkerTask.ps1 -Trigger Startup -StartupDelaySeconds 60
```

Teste manual: `Start-ScheduledTask -TaskName "JiraKnowledge-SqsWorker"`. Acompanhe no Agendador de Tarefas se o estado fica "Em execucao".

**3) Criar a tarefa (manual, interface grafica)**  
- Abra **Agendador de Tarefas** (taskschd.msc) → Criar Tarefa (nao apenas “basica”).  
- **Geral:** nome ex. `JiraKnowledge-SqsWorker`; marque *Executar com as privilegios mais altos* apenas se a politica exigir.  
- **Gatilhos:** *Ao iniciar o computador* (ou *Ao fazer logon*); opcional: atraso 1 minuto.  
- **Acoes:** Iniciar programa  
  - Programa: `powershell.exe`  
  - Argumentos: `-NoProfile -ExecutionPolicy Bypass -File "C:\CAMINHO\COMPLETO\project\scripts\run-sqs-worker.ps1"` (aspas se o caminho tiver espacos)  
  - Iniciar em: `C:\CAMINHO\COMPLETO\project` (pasta que contem `worker/` e `.env`)  
- **Condicoes:** desative “Iniciar somente se o computador estiver ligado a energia CA” se for notebook (na EC2 costuma nao incomodar).  
- **Configuracoes:** *Se a tarefa falhar, reiniciar a cada: 1 minuto*, tentar ate N vezes; *se a tarefa em execucao nao for encerrada ao exigir, forcar encerrar* nao e necessario para processo de longa duracao.  
- Se precisar de **arquivo de log** (recomendado sem console): em Variaveis de ambiente da tarefa, crie `SQS_WORKER_LOG` = ex. `C:\Logs\sqs-worker.log`, ou adicione redirecionamento em **Propriedades > Acoes > Editar** (alguns usam `cmd /c` com `>>`).

**4) “Rodar mesmo sem logon” (servidor 24/7 sem RDP aberto)**  
Use **Executar se o usuario estiver conectado ou nao** e informe a **senha** do usuario dono do projeto, ou crie um usuario de serviço com acesso a pasta do projeto, credenciais AWS (IAM Role na instancia e recomendada) e rede. *Executar so quando o usuario fizer logon* e mais simples, mas o worker so sobe depois de um logon; para boot sem sessao, use a opcao com senha / NSSM (servico) como evolucao.

**5) Apos reiniciar a EC2**  
Com gatilho *Ao iniciar o computador* (ou tarefa com logon + login automatico, se a politica permitir) o worker sobe de novo. Confirme a **IAM Role** (SQS) e o caminho se voce **mover** a pasta do projeto.

### Integracao com um `.bat` mestre (varios `start` no boot)

Se voce ja tem um script no estilo `D:\...\start-todos.bat` com varias linhas `start D:\SERVICOS\...\AlgumServico.bat`, use o mesmo padrao:

1. Copie `scripts\JiraKnowledgeSqsWorker.bat` para uma pasta em `D:\SERVICOS\` (ex.: `33SERVICE.JIRA_KNOWLEDGE_SQS\`).
2. Abra o `.bat` e ajuste **`set PROJECT_ROOT=...`** para o caminho absoluto da pasta **`project`** (onde estao `worker/`, `.env`, `.venv`).
3. No mestre, adicione uma linha entre as outras:
   `start D:\SERVICOS\33SERVICE.JIRA_KNOWLEDGE_SQS\JiraKnowledgeSqsWorker.bat`
4. Cada `start` abre uma janela; o worker fica em loop ate fechar a janela ou matar o processo. Nao use `pause` no final do `.bat` do worker (os servicos devem rodar continuos).

## Fila SQS

Corpo minimo da mensagem (fluxo completo de triagem):

```json
{"chave_jira": "PROJ-123"}
```

Retorno Avalara por e-mail (comentario interno + transicao para `Analise JDMS`, sem LLM):

```json
{
  "chave_jira": "JDMSN1-2222",
  "bodyDoEmail": "Testando automação"
}
```

Campos opcionais do fluxo completo alinham-se aos argumentos de `JiraFlowService.process_issue` (ex.: `saudacao_publica`, `transicionar`, `comentario_interno`).

## Regras implementadas no MVP
- Consolidacao textual: resumo + descricao + comentarios
- Extracao heuristica de problema e solucao
- Similaridade vetorial (armazenamento no banco; busca por distancia coseno no processo)
- Comentario interno Jira gerado por LLM com fallback
- Ingestao de tickets ocorre no fluxo do worker ao processar cada chamado; para carga em lote da base historica use os scripts em `tools/` se necessario

## Observacoes
- O sistema nao responde cliente final automaticamente
- As sugestoes sao apoio ao analista N1
- LLM de triagem usa somente Bedrock; credenciais AWS e modelo habilitado na regiao — veja `.env.example`
- `EMBEDDING_PROVIDER=local` usa modelos sentence-transformers (pode exigir mais tempo na primeira carga do modelo)
