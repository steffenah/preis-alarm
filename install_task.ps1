# Windows Task Scheduler Aufgabe einrichten
# Ausfuehren mit: Rechtsklick -> "Mit PowerShell ausfuehren" (als Administrator)

$TaskName   = "eGun_Monitor_Kat492"
$PythonExe  = (Get-Command python).Source
$ScriptPath = Join-Path $PSScriptRoot "monitor.py"

# Bestehende Aufgabe entfernen, falls vorhanden
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Alte Aufgabe entfernt."
}

$action   = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ScriptPath`""
$trigger  = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 10) -Once -At (Get-Date)
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -RunOnlyIfNetworkAvailable $true

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "Aufgabe '$TaskName' erfolgreich eingerichtet."
Write-Host "Monitor laeuft jetzt alle 10 Minuten."
Write-Host ""
Write-Host "Verwalten unter: Aufgabenplanung -> Aufgabenplanungsbibliothek -> $TaskName"
Write-Host "Log-Datei: $(Join-Path $PSScriptRoot 'monitor.log')"

# Ersten Testlauf starten
Write-Host ""
Write-Host "Starte ersten Testlauf..."
& $PythonExe $ScriptPath
