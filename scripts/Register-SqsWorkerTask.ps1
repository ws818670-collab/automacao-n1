# Cria ou atualiza uma tarefa no Agendador de Tarefas do Windows para o consumer SQS.
# Execute no PowerShell (idealmente como o MESMO usuario dono do projeto, como Administrador
#   se a politica de tarefa exigir).
#
# Exemplo (padrao: ao fazer logon, apos 30s; reinicia a cada 1 min se falhar):
#   .\scripts\Register-SqsWorkerTask.ps1
#
# Exemplo (na inicializacao do computador, com 1 min de atraso — bom para subir apos boot):
#   .\scripts\Register-SqsWorkerTask.ps1 -Trigger Startup -StartupDelaySeconds 60
#
# Ajuste o nome no Agendador se precisar de varias instancias.

[CmdletBinding()]
param(
    [string] $TaskName = "JiraKnowledge-SqsWorker",
    [ValidateSet("Logon", "Startup")]
    [string] $Trigger = "Logon",
    [int] $DelaySeconds = 30,
    [int] $StartupDelaySeconds = 60
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$ps1 = Join-Path $scriptDir "run-sqs-worker.ps1"

$args = "-NoProfile -ExecutionPolicy Bypass -File `"$ps1`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $args -WorkingDirectory $projectRoot

if ($Trigger -eq "Logon") {
    $t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    if ($DelaySeconds -gt 0) {
        $t.Delay = "PT{0}S" -f $DelaySeconds
    }
} else {
    $t = New-ScheduledTaskTrigger -AtStartup
    if ($StartupDelaySeconds -gt 0) {
        $t.Delay = "PT{0}S" -f $StartupDelaySeconds
    }
}

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

$domain = if ($env:USERDOMAIN) { $env:USERDOMAIN } else { $env:COMPUTERNAME }
$userId = "$domain\$($env:USERNAME)"
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $t -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Tarefa '$TaskName' registrada. Disparo: $Trigger. Pasta: $projectRoot"
Write-Host "Teste:  Start-ScheduledTask -TaskName '$TaskName'   |   Status:  Get-ScheduledTask -TaskName '$TaskName'"
