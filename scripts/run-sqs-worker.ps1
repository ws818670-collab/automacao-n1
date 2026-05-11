# Inicia o consumer SQS (fila) na pasta do projeto, usando o venv.
# Uso manual:  .\scripts\run-sqs-worker.ps1
# Uso tarefa agendada: ver README "Agendador de Tarefas (EC2 / Windows)").
#
# Requisitos: project\.env com SQS_*, Jira, LLM, DATABASE_URL; venv e pip install; alembic feito.
# Opcional: variavel de ambiente SQS_WORKER_LOG (caminho de arquivo) para redirecionar saida
#   (a propria tarefa no Agendador tambem pode redirecionar).

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
Set-Location -LiteralPath $projectRoot

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Error "Nao encontrado: $venvPython. Crie o venv: python -m venv .venv  e  pip install -r requirements.txt"
    exit 1
}

# Opcional: log em arquivo (variavel SQS_WORKER_LOG — configure na tarefa do Agendador)
$log = $env:SQS_WORKER_LOG
if ($log) {
    try {
        Add-Content -LiteralPath $log -Value "===== $(Get-Date -Format o) inicio worker =====" -Encoding utf8
    } catch {
        Write-Warning "Nao foi possivel escrever no log ($log): $_"
    }
    & $venvPython -m worker.sqs_consumer *>> $log
    exit $LASTEXITCODE
}

& $venvPython -m worker.sqs_consumer
exit $LASTEXITCODE
