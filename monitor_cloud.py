"""
eGun / Kleinanzeigen Monitor – Cloud-Version für GitHub Actions.
Liest alle Monitore aus monitors.json und prüft jede Quelle.
"""

import json
import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_DIR   = Path(__file__).parent
SEEN_FILE  = BASE_DIR / "seen_items.json"
MON_FILE   = BASE_DIR / "monitors.json"
SNIPER_FILE = BASE_DIR / "sniper_watches.json"
SNIPER_NOTIFIED_FILE = BASE_DIR / "sniper_notified.json"

# Sniper-Konfiguration: Auktion endet in 5-15 Minuten + 0 Gebote → benachrichtigen
SNIPER_WINDOW_MIN_LO = 5
SNIPER_WINDOW_MIN_HI = 15

# Zugangsdaten aus GitHub Secrets
SENDER_EMAIL    = os.environ["SENDER_EMAIL"]
SENDER_PASSWORD = os.environ["SENDER_PASSWORD"]
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def load_monitors() -> list[dict]:
    with open(MON_FILE, encoding="utf-8") as f:
        return json.load(f).get("monitors", [])


def load_seen() -> dict:
    if not SEEN_FILE.exists():
        return {}
    with open(SEEN_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_seen(seen: dict):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def send_email(monitor_name: str, new_items: list[dict], min_price: float, max_price: float = 0):
    count = len(new_items)
    price_hint = ""
    if min_price and max_price:
        price_hint = f" · {min_price:.0f}–{max_price:.0f} €"
    elif min_price:
        price_hint = f" · ab {min_price:.0f} €"
    elif max_price:
        price_hint = f" · bis {max_price:.0f} €"
    subject = f"🔔 {monitor_name}: {count} neues Inserat{'e' if count > 1 else ''}{price_hint}"

    lines = [f"Neue Treffer für »{monitor_name}«:\n"]
    for item in new_items:
        lines.append(f"• {item['title']}")
        if item.get("auction_price") is not None:
            lines.append(f"  Aktuelles Gebot:  {item['auction_price']:.2f} €")
        if item.get("sofortkauf_price") is not None:
            lines.append(f"  Sofortkauf:       {item['sofortkauf_price']:.2f} €")
        if not item.get("auction_price") and not item.get("sofortkauf_price"):
            p = item.get("price")
            lines.append(f"  Preis: {f'{p:.2f} €' if p else 'nicht angegeben'}")
        lines += [f"  Link:  {item['url']}", ""]
    lines += [
        f"\nGefunden am: {datetime.now().strftime('%d.%m.%Y um %H:%M Uhr')}",
    ]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText("\n".join(lines), "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(SENDER_EMAIL, SENDER_PASSWORD)
        s.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())

    log(f"  → E-Mail gesendet: {subject}")


def get_listings(monitor: dict) -> list[dict]:
    from parsers import get_listings as _get
    return _get(monitor)


def matches(item: dict, monitor: dict) -> bool:
    keywords    = monitor.get("keywords", [])
    min_price   = monitor.get("min_price", 0)
    max_price   = monitor.get("max_price", 0)   # 0 = kein Limit
    sofort_only = monitor.get("sofortkauf_only", False)

    if keywords:
        title_lower = item["title"].lower()
        if not any(kw.lower() in title_lower for kw in keywords):
            return False

    # Relevanten Preis bestimmen (Sofortkauf bevorzugt, sonst Auktionspreis)
    relevant_price = item.get("sofortkauf_price") or item.get("auction_price") or item.get("price") or 0

    if min_price and relevant_price < min_price:
        return False
    if max_price and relevant_price > max_price:
        return False
    if sofort_only and not item.get("is_sofortkauf", True):
        return False
    return True


def load_sniper_watches() -> list[dict]:
    if not SNIPER_FILE.exists():
        return []
    with open(SNIPER_FILE, encoding="utf-8") as f:
        return json.load(f).get("watches", [])


def load_sniper_notified() -> dict:
    if not SNIPER_NOTIFIED_FILE.exists():
        return {}
    with open(SNIPER_NOTIFIED_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_sniper_notified(notified: dict):
    # Alte Einträge (> 24h) löschen
    now = datetime.now()
    pruned = {}
    for key, ts in notified.items():
        try:
            old = datetime.fromisoformat(ts)
            if (now - old).total_seconds() < 24 * 3600:
                pruned[key] = ts
        except Exception:
            pass
    with open(SNIPER_NOTIFIED_FILE, "w", encoding="utf-8") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=2)


def send_sniper_email(watch_name: str, alerts: list[dict], platform: str = "ebay"):
    count = len(alerts)
    plat_label = "eGun" if platform == "egun" else "eBay"
    subject = f"🔨 {plat_label} AUKTION ENDET BALD · {watch_name} ({count})"
    lines = [f"Diese {plat_label}-Auktionen für »{watch_name}« enden bald OHNE Gebote:\n"]
    for a in alerts:
        lines.append(f"• {a['title']}")
        p = a.get("auction_price") or a.get("price")
        lines.append(f"  Aktueller Preis: {p:.2f} €" if p else "  Preis unbekannt")
        lines.append(f"  Endet in:        ~{a['time_left_min']} Min")
        lines.append(f"  Gebote:          {a.get('bids', 0)}")
        lines.append(f"  Link:            {a['url']}")
        lines.append("")
    lines += [f"\nGefunden am: {datetime.now().strftime('%d.%m.%Y um %H:%M Uhr')}"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECIPIENT_EMAIL
    msg["X-Priority"] = "1"
    msg["Importance"] = "high"
    msg.attach(MIMEText("\n".join(lines), "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(SENDER_EMAIL, SENDER_PASSWORD)
        s.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
    log(f"  → Sniper-Mail gesendet: {subject}")


def run_sniper():
    from parsers import fetch, parse_ebay_auctions, parse_egun
    watches = load_sniper_watches()
    if not watches:
        return
    notified = load_sniper_notified()
    log(f"=== Sniper: {len(watches)} Suche(n) ===")

    for w in watches:
        if not w.get("enabled", True):
            continue
        name = w.get("name", "Sniper")
        platform = w.get("platform", "ebay")
        max_price = w.get("max_price", 0)

        # URL + Parser je nach Plattform
        try:
            if platform == "egun":
                url = w.get("url", "").strip()
                if not url:
                    log(f"[{name}] keine URL – übersprungen.")
                    continue
                log(f"[{name}] (eGun) prüfe {url}")
                soup = fetch(url)
                items = parse_egun(soup)
                # Nur Auktionen (mit Gebotsstand) behalten
                auctions = [i for i in items if i.get("bids") is not None]
            else:
                keyword = w.get("keyword", "").strip()
                if not keyword:
                    log(f"[{name}] kein Suchbegriff – übersprungen.")
                    continue
                url = f"https://www.ebay.de/sch/i.html?_nkw={keyword.replace(' ', '+')}&LH_Auction=1&_sop=1"
                log(f"[{name}] (eBay) suche: {keyword}")
                soup = fetch(url)
                auctions = parse_ebay_auctions(soup)
        except Exception as e:
            log(f"[{name}] FEHLER: {e}")
            continue

        # Optionale Schlagwort-Filter (leer = alle Auktionen)
        keywords = [k.strip().lower() for k in w.get("keywords", []) if k.strip()]

        log(f"[{name}] {len(auctions)} Auktionen gefunden"
            + (f" (Filter: {keywords})" if keywords else "") + ".")
        alerts = []
        for a in auctions:
            tl = a.get("time_left_min")
            if tl is None:
                continue
            if not (SNIPER_WINDOW_MIN_LO <= tl <= SNIPER_WINDOW_MIN_HI):
                continue
            if a.get("bids", 0) > 0:
                continue
            # Preis-Check: eGun = auction_price, eBay = price
            chk_price = a.get("auction_price") or a.get("price")
            if max_price and chk_price and chk_price > max_price:
                continue
            # Schlagwort-Filter (nur wenn welche definiert)
            if keywords:
                title_lower = a["title"].lower()
                if not any(kw in title_lower for kw in keywords):
                    continue
            # Schon benachrichtigt?
            key = f"{w.get('id', name)}::{a['id']}"
            if key in notified:
                continue
            notified[key] = datetime.now().isoformat()
            alerts.append(a)

        if alerts:
            try:
                send_sniper_email(name, alerts, platform)
            except Exception as e:
                log(f"[{name}] Mail-Fehler: {e}")
        else:
            log(f"[{name}] keine Schnäppchen-Auktionen.")

    save_sniper_notified(notified)


def main():
    log("=== Monitor Cloud-Lauf gestartet ===")
    monitors = load_monitors()
    seen     = load_seen()
    log(f"{len(monitors)} Monitor(e) geladen, {len(seen)} bekannte Einträge.")

    for monitor in monitors:
        if not monitor.get("enabled", True):
            log(f"[{monitor['name']}] deaktiviert – übersprungen.")
            continue

        log(f"[{monitor['name']}] prüfe {monitor['url']}")
        try:
            listings = get_listings(monitor)
        except Exception as e:
            log(f"[{monitor['name']}] FEHLER: {e}")
            continue

        log(f"[{monitor['name']}] {len(listings)} Einträge gefunden.")
        new_items = []
        for item in listings:
            key = f"{monitor['id']}::{item['id']}"
            if key not in seen:
                seen[key] = {
                    "title":      item["title"],
                    "price":      item.get("price"),
                    "first_seen": datetime.now().isoformat(),
                }
                if matches(item, monitor):
                    new_items.append(item)
                    log(f"  NEU: {item['title'][:60]}  {item.get('price','–')}€")

        if new_items:
            try:
                send_email(monitor["name"], new_items, monitor.get("min_price", 0), monitor.get("max_price", 0))
            except Exception as e:
                log(f"  E-Mail Fehler: {e}")
        else:
            log(f"[{monitor['name']}] keine neuen Treffer.")

    save_seen(seen)

    # eBay-Auktions-Sniper
    try:
        run_sniper()
    except Exception as e:
        log(f"Sniper Fehler: {e}")

    log("=== Lauf beendet ===")


if __name__ == "__main__":
    main()
