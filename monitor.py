"""
eGun Kategorie 492 Monitor
Prüft alle 30 Sekunden auf neue Inserate über 70€ und sendet E-Mail-Benachrichtigungen.
"""

import json
import os
import re
import smtplib
import sys
import threading
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pystray
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
SEEN_FILE = BASE_DIR / "seen_items.json"
LOG_FILE = BASE_DIR / "monitor.log"

URL = "https://egun.de/market/list_items.php?cat=492"
MIN_PRICE = 45.0
INTERVAL_SECONDS = 600  # 10 Minuten


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        log("FEHLER: config.json nicht gefunden. Bitte setup.py ausführen.")
        sys.exit(1)
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_seen() -> dict:
    if not SEEN_FILE.exists():
        return {}
    with open(SEEN_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_seen(seen: dict):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def parse_price(text: str) -> float | None:
    """Parst einen Preis aus Text der Form '117,00 EUR' oder '117.00 EUR'."""
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)\s*EUR", text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1).replace(",", "."))
        except ValueError:
            pass
    return None


def fetch_listings() -> list[dict]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(URL, headers=headers, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    listings = []
    seen_ids: set[str] = set()

    for link in soup.find_all("a", href=re.compile(r"item\.php\?id=\d+")):
        title = link.get_text(strip=True)
        if not title:
            continue  # Bild-Links ohne Text überspringen

        item_id_match = re.search(r"id=(\d+)", link["href"])
        if not item_id_match:
            continue
        item_id = item_id_match.group(1)

        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        # Preis und Typ aus dem umgebenden <tr> lesen
        price = None
        is_sofortkauf = False
        row = link.find_parent("tr")
        if row:
            row_text = row.get_text(" ", strip=True)
            price = parse_price(row_text)
            # Sofortkauf erkennen: spezielles CSS-Element oder kein "Gebote"-Text
            if row.find(class_="ls-buynow") or row.find(attrs={"title": "Sofortkauf-Artikel"}):
                is_sofortkauf = True
            elif "Gebote" not in row_text and "Gebot" not in row_text:
                # Kein Auktionshinweis → auch Sofortkauf
                is_sofortkauf = True

        listings.append({
            "id": item_id,
            "title": title,
            "price": price,
            "is_sofortkauf": is_sofortkauf,
            "url": f"https://egun.de/market/item.php?id={item_id}",
        })

    return listings


def send_email(config: dict, new_items: list[dict]):
    sender = config["sender_email"]
    password = config["sender_password"]
    recipient = config["recipient_email"]

    subject = f"eGun: {len(new_items)} neues Inserat{'e' if len(new_items) > 1 else ''} über {MIN_PRICE:.0f}€"

    body_lines = [
        f"Neue Inserate auf eGun (Kategorie 492) über {MIN_PRICE:.0f}€:\n",
    ]
    for item in new_items:
        price_str = f"{item['price']:.2f}€" if item["price"] is not None else "Preis unbekannt"
        body_lines.append(f"• {item['title']}")
        body_lines.append(f"  Preis: {price_str}")
        body_lines.append(f"  Link:  {item['url']}\n")

    body_lines.append(f"\nGefunden am: {datetime.now().strftime('%d.%m.%Y um %H:%M Uhr')}")
    body_lines.append(f"Quelle: {URL}")

    body = "\n".join(body_lines)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())

    log(f"E-Mail gesendet an {recipient}: {subject}")


def check_once(config: dict, seen: dict) -> dict:
    """Ein einzelner Prüfdurchlauf. Gibt das aktualisierte seen-Dict zurück."""
    try:
        listings = fetch_listings()
    except Exception as e:
        log(f"FEHLER beim Abrufen der Seite: {e}")
        return seen

    new_items = []
    for item in listings:
        if item["id"] not in seen:
            typ = "Sofortkauf" if item["is_sofortkauf"] else "Auktion"
            if item["is_sofortkauf"] and item["price"] is not None and item["price"] > MIN_PRICE:
                new_items.append(item)
                log(f"  NEU Sofortkauf (>{MIN_PRICE:.0f}€): {item['title']} – {item['price']:.2f}€")
            else:
                log(f"  Ignoriert ({typ}, {item['price']}€): {item['title'][:40]}")
            seen[item["id"]] = {
                "title": item["title"],
                "price": item["price"],
                "is_sofortkauf": item["is_sofortkauf"],
                "first_seen": datetime.now().isoformat(),
            }

    if new_items:
        try:
            send_email(config, new_items)
        except Exception as e:
            log(f"FEHLER beim E-Mail-Versand: {e}")
    else:
        log(f"Keine neuen Inserate über {MIN_PRICE:.0f}€. Nächste Prüfung in {INTERVAL_SECONDS}s.")

    save_seen(seen)
    return seen


def create_pistol_icon() -> Image.Image:
    """Zeichnet ein einfaches Pistolen-Silhouette-Icon (64x64 px)."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = (30, 30, 30)  # Dunkelgrau

    # Lauf (horizontal, oben)
    d.rectangle([4, 18, 46, 28], fill=c)
    # Abzugsbügel-Bogen
    d.rectangle([30, 28, 46, 44], fill=c)
    # Griff (schräg nach unten)
    d.polygon([(30, 28), (44, 28), (40, 58), (26, 58)], fill=c)
    # Abzug
    d.rectangle([35, 36, 38, 46], fill=(80, 80, 80))
    # Mündung
    d.rectangle([2, 20, 8, 26], fill=(60, 60, 60))

    return img


AUTOSTART_NAME = "eGun_Monitor"
PYTHONW = Path(sys.executable).parent / "pythonw.exe"


def autostart_is_enabled() -> bool:
    """Prüft ob der Monitor im Registry-Autostart eingetragen ist."""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run")
        winreg.QueryValueEx(key, AUTOSTART_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False


def autostart_enable():
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Run",
                         0, winreg.KEY_SET_VALUE)
    value = f'"{PYTHONW}" "{Path(__file__).resolve()}"'
    winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, value)
    winreg.CloseKey(key)
    log("Autostart aktiviert.")


def autostart_disable():
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, AUTOSTART_NAME)
        winreg.CloseKey(key)
        log("Autostart deaktiviert.")
    except FileNotFoundError:
        pass


def toggle_autostart(icon: pystray.Icon, item):
    if autostart_is_enabled():
        autostart_disable()
    else:
        autostart_enable()
    # Menü neu aufbauen damit Haken sofort aktualisiert wird
    icon.menu = build_menu(icon)
    icon.update_menu()


def monitor_loop(icon: pystray.Icon, config: dict):
    """Läuft im Hintergrund-Thread und prüft alle 10 Minuten."""
    seen = load_seen()
    log(f"=== eGun Monitor gestartet – Prüfung alle {INTERVAL_SECONDS // 60} Minuten ===")
    log(f"Bereits bekannte Inserate: {len(seen)}")

    while getattr(icon, "_running", True):
        log("--- Prüfdurchlauf ---")
        icon.title = f"eGun Monitor – zuletzt geprüft {datetime.now().strftime('%H:%M')}"
        seen = check_once(config, seen)
        for _ in range(INTERVAL_SECONDS):
            if not getattr(icon, "_running", True):
                break
            time.sleep(1)

    log("=== Monitor gestoppt ===")


def on_quit(icon: pystray.Icon, item):
    icon._running = False
    icon.stop()
    # Prozess sicher beenden
    os._exit(0)


def build_menu(icon: pystray.Icon) -> pystray.Menu:
    return pystray.Menu(
        pystray.MenuItem("eGun Monitor läuft", None, enabled=False),
        pystray.MenuItem(
            f"Alle {INTERVAL_SECONDS // 60} Min | Sofortkauf > {MIN_PRICE:.0f}€",
            None, enabled=False,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Mit Windows starten",
            toggle_autostart,
            checked=lambda item: autostart_is_enabled(),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Log öffnen", lambda i, it: os.startfile(str(LOG_FILE))),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Beenden", on_quit),
    )


def main():
    config = load_config()

    icon = pystray.Icon(
        name="egun_monitor",
        icon=create_pistol_icon(),
        title="eGun Monitor",
    )
    icon._running = True
    icon.menu = build_menu(icon)

    t = threading.Thread(target=monitor_loop, args=(icon, config), daemon=True)
    t.start()

    icon.run()


if __name__ == "__main__":
    main()
