"""
Einmaliges Setup: Konfiguration speichern und Windows-Aufgabe anlegen.
Ausführen mit: python setup.py
"""

import getpass
import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
MONITOR_SCRIPT = BASE_DIR / "monitor.py"
TASK_NAME = "eGun_Monitor_Kat492"

RECIPIENT = "Steffen.Ahlers90@gmail.com"


def main():
    print("=" * 60)
    print("  eGun Monitor – Setup")
    print("=" * 60)
    print()
    print("Benachrichtigungen werden gesendet an:")
    print(f"  {RECIPIENT}")
    print()
    print("Als Absender wird ein Gmail-Konto verwendet.")
    print("Empfohlen: Ein separates Gmail-Konto nur zum Senden.")
    print()
    print("Anleitung Gmail App-Passwort:")
    print("  1. Öffne: https://myaccount.google.com/apppasswords")
    print("  2. Klicke auf 'App-Passwort erstellen'")
    print("  3. Wähle 'Mail' und 'Windows-Computer'")
    print("  4. Kopiere das 16-stellige Passwort")
    print()

    sender = input("Absender Gmail-Adresse (z.B. monitor@gmail.com): ").strip()
    if not sender:
        print("Abbruch: Keine E-Mail-Adresse eingegeben.")
        sys.exit(1)

    password = getpass.getpass("Gmail App-Passwort (16 Zeichen, wird nicht angezeigt): ")
    if not password:
        print("Abbruch: Kein Passwort eingegeben.")
        sys.exit(1)

    config = {
        "sender_email": sender,
        "sender_password": password,
        "recipient_email": RECIPIENT,
    }

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"\nKonfiguration gespeichert: {CONFIG_FILE}")

    # Windows Task Scheduler einrichten
    python_exe = sys.executable
    script_path = str(MONITOR_SCRIPT)

    ps_script = f"""
$action = New-ScheduledTaskAction -Execute "{python_exe}" -Argument '"{script_path}"'
$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 10) -Once -At (Get-Date)
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "{TASK_NAME}" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force
"""

    result = subprocess.run(
        ["powershell", "-NonInteractive", "-Command", ps_script],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print(f"Windows-Aufgabe '{TASK_NAME}' erfolgreich erstellt.")
        print("Der Monitor läuft jetzt alle 10 Minuten im Hintergrund.")
    else:
        print("WARNUNG: Aufgabe konnte nicht automatisch erstellt werden.")
        print(result.stderr)
        print()
        print("Manuell erstellen:")
        print(f'  python "{MONITOR_SCRIPT}"')

    print()
    print("Erster Test-Lauf wird gestartet...")
    result2 = subprocess.run([python_exe, script_path], capture_output=True, text=True)
    print(result2.stdout)
    if result2.stderr:
        print("Fehler:", result2.stderr)

    print()
    print("Setup abgeschlossen!")
    print(f"Logs: {BASE_DIR / 'monitor.log'}")


if __name__ == "__main__":
    main()
