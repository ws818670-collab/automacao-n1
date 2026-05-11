@echo off
REM Jira N1 SQS consumer - edit PROJECT_ROOT (folder with worker/, .env, .venv).
REM
REM If the first line shows '∩╗┐' or '  @echo' is not recognized: UTF-8 WITH BOM.
REM   Run once in PowerShell (folder scripts):
REM   powershell -NoProfile -ExecutionPolicy Bypass -File "Remove-BomFromBat.ps1" -Path "JiraKnowledgeSqsWorker.bat"
REM   Or Notepad: Save As -> Encoding: ANSI, or "UTF-8" (not UTF-8 with BOM).
REM   In VS Code: bottom bar UTF-8 -> "Save with Encoding" -> UTF-8 (without BOM).
REM
REM If the path has accents (c cedilha, til) and the folder is not found:
REM   - Save this file as Encoding ANSI (Notepad) on the same Windows that runs it, OR
REM   - Rename the folder to ASCII only, OR
REM   - Use 8.3 short name:  dir /x D:\SERVICOS
REM
REM Double-click: on error, PAUSE so you can read. Or run from an open cmd.
REM
REM 1) Copy to e.g. D:\SERVICOS\33SERVICE.JIRA_KNOWLEDGE_SQS\JiraKnowledgeSqsWorker.bat
REM 2) Edit set PROJECT_ROOT below
REM 3) Master .bat:  start "JiraKnowledge SQS" "D:\...\JiraKnowledgeSqsWorker.bat"

set "PROJECT_ROOT=D:\SERVICOS\JIRA_KNOWLEDGE_N1\project"
cd /d "%PROJECT_ROOT%"
if errorlevel 1 (
    echo [JiraKnowledgeSqs] ERRO: nao foi possivel acessar a pasta: %PROJECT_ROOT%
    echo Ajuste PROJECT_ROOT, encoding ANSI do .bat, ou use caminho 8.3 ^(dir /x^).
    pause
    exit /b 1
)
if not exist "%PROJECT_ROOT%\worker\sqs_consumer.py" (
    echo [JiraKnowledgeSqs] ERRO: pasta do projeto nao encontrada: %PROJECT_ROOT%
    echo Ajuste PROJECT_ROOT no topo de JiraKnowledgeSqsWorker.bat
    pause
    exit /b 1
)
if not exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    echo [JiraKnowledgeSqs] ERRO: venv nao encontrada em .venv\Scripts\python.exe
    pause
    exit /b 1
)

"%PROJECT_ROOT%\.venv\Scripts\python.exe" -m worker.sqs_consumer
set "WORKER_EXIT=%ERRORLEVEL%"
if not "%WORKER_EXIT%"=="0" (
    echo.
    echo [JiraKnowledgeSqs] Worker encerrou com codigo de erro. Veja a mensagem acima.
    pause
)
exit /b %WORKER_EXIT%
