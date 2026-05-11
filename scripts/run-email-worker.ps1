# Inicia o worker de e-mail (IMAP) na pasta do projeto, usando o venv.
# Uso manual:  .\scripts\run-email-worker.ps1
# Requisitos: project\.env com EMAIL_*, Jira e venv pronto.

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
Set-Location -LiteralPath $projectRoot

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Error "Nao encontrado: $venvPython. Crie o venv: python -m venv .venv  e  pip install -r requirements.txt"
    exit 1
}

$log = $env:EMAIL_WORKER_LOG
if ($log) {
    try {
        Add-Content -LiteralPath $log -Value "===== $(Get-Date -Format o) inicio email worker =====" -Encoding utf8
    } catch {
        Write-Warning "Nao foi possivel escrever no log ($log): $_"
    }
    & $venvPython -m worker.email_consumer *>> $log
    exit $LASTEXITCODE
}

& $venvPython -m worker.email_consumer
exit $LASTEXITCODE
