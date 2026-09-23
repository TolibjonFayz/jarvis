# JARVIS'ni Windows'ga kirganda avtomatik ishga tushiradigan vazifa yaratadi.
# Ishlatish:   powershell -ExecutionPolicy Bypass -File setup_autostart.ps1
# O'chirish:   Unregister-ScheduledTask -TaskName JARVIS -Confirm:$false

$ErrorActionPreference = "Stop"
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (Get-Command python).Source
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"

$action = New-ScheduledTaskAction -Execute $pythonw `
    -Argument "`"$base\run_forever.pyw`"" -WorkingDirectory $base
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
# Batareyada ham ishlasin, vaqt chegarasi yo'q, nazoratchi yiqilsa qayta tursin.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "JARVIS" -Action $action -Trigger $trigger `
    -Settings $settings -Description "JARVIS Telegram bot (run_forever.pyw)" -Force | Out-Null

Write-Host "Tayyor: JARVIS vazifasi yaratildi. Hozir ishga tushirish: Start-ScheduledTask -TaskName JARVIS"
