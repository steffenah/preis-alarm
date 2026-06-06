@echo off
echo eGun Monitor - Windows Aufgabe einrichten
echo ==========================================
echo.

set PYTHONW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe
set SCRIPT=C:\Users\steff_000\Desktop\Claude Projekte\egun_monitor\monitor.py
set TASKNAME=eGun_Monitor_Kat492

schtasks /delete /tn "%TASKNAME%" /f 2>nul

:: pythonw.exe = startet ohne Konsolenfenster, nur Tray-Icon sichtbar
schtasks /create ^
  /tn "%TASKNAME%" ^
  /tr "\"%PYTHONW%\" \"%SCRIPT%\"" ^
  /sc onstart ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /f

echo.
if %ERRORLEVEL%==0 (
    echo ERFOLG! Monitor startet ab sofort bei jedem Windows-Start automatisch.
    echo Sichtbar als Pistolen-Symbol in der Taskleiste unten rechts.
    echo.
    echo Starte Monitor jetzt sofort...
    start "" "%PYTHONW%" "%SCRIPT%"
) else (
    echo FEHLER beim Einrichten. Bitte als Administrator ausfuehren.
)
echo.
pause
