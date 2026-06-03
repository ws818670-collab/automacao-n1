@echo off

set "PROJECT_ROOT=D:\SERVICOS\automacao-n1"
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
