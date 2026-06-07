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
PRICE_HISTORY_FILE   = BASE_DIR / "price_history.json"

# Schnäppchen-Score: ab welcher Abweichung gilt etwas als Schnäppchen?
DEAL_THRESHOLD_PCT = 30   # 30% unter Median = 🔥 Schnäppchen
DEAL_MIN_SAMPLES   = 5    # mindestens 5 Daten brauchen wir, um einen Median zu trauen

# Sniper-Konfiguration: Auktion endet in 5-15 Minuten + 0 Gebote → benachrichtigen
SNIPER_WINDOW_MIN_LO = 5
SNIPER_WINDOW_MIN_HI = 15

# E-Mail-Versand (per env-Var EMAIL_ENABLED=1 wieder aktivierbar)
EMAIL_ENABLED   = os.environ.get("EMAIL_ENABLED", "0") == "1"
SENDER_EMAIL    = os.environ.get("SENDER_EMAIL", "")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD", "")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "")

# Telegram (optional - leer wenn nicht gesetzt)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")


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


def _tg_call(method: str, params: dict) -> bool:
    import urllib.request, urllib.parse, json as _j
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    try:
        data = urllib.parse.urlencode(params).encode("utf-8")
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as resp:
            return _j.loads(resp.read()).get("ok", False)
    except Exception as e:
        log(f"  Telegram-Fehler ({method}): {e}")
        return False


def send_telegram(text: str, urgent: bool = False) -> bool:
    """Sendet eine reine Textnachricht via Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    ok = _tg_call("sendMessage", {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
        "disable_notification": "false" if urgent else "false",
    })
    if ok:
        log(f"  → Telegram gesendet")
    return ok


def send_telegram_photo(photo_url: str, caption: str, urgent: bool = False) -> bool:
    """Schickt ein Bild mit Caption (max 1024 Zeichen)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not photo_url:
        return send_telegram(caption, urgent=urgent)
    # Telegram braucht http(s) URLs
    if not photo_url.startswith("http"):
        return send_telegram(caption, urgent=urgent)
    ok = _tg_call("sendPhoto", {
        "chat_id": TELEGRAM_CHAT_ID,
        "photo": photo_url,
        "caption": caption[:1020],
        "parse_mode": "HTML",
        "disable_notification": "false" if urgent else "false",
    })
    if ok:
        log(f"  → Telegram-Photo gesendet")
        return True
    # Fallback nur wenn echt fehlgeschlagen
    return send_telegram(caption, urgent=urgent)


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
        score = item.get("deal_score") or 0
        fire = " 🔥 SCHNÄPPCHEN!" if score >= DEAL_THRESHOLD_PCT else ""
        lines.append(f"• {item['title']}{fire}")
        if item.get("auction_price") is not None:
            lines.append(f"  Aktuelles Gebot:  {item['auction_price']:.2f} €")
        if item.get("sofortkauf_price") is not None:
            lines.append(f"  Sofortkauf:       {item['sofortkauf_price']:.2f} €")
        if not item.get("auction_price") and not item.get("sofortkauf_price"):
            p = item.get("price")
            lines.append(f"  Preis: {f'{p:.2f} €' if p else 'nicht angegeben'}")
        if item.get("median_price") and score >= DEAL_THRESHOLD_PCT:
            lines.append(f"  Markt-Median:     {item['median_price']:.2f} €  (-{score:.0f}% Schnäppchen)")
        elif item.get("median_price"):
            lines.append(f"  Markt-Median:     {item['median_price']:.2f} €")
        lines += [f"  Link:  {item['url']}", ""]
    lines += [
        f"\nGefunden am: {datetime.now().strftime('%d.%m.%Y um %H:%M Uhr')}",
    ]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText("\n".join(lines), "plain", "utf-8"))

    if EMAIL_ENABLED and SENDER_EMAIL and SENDER_PASSWORD and RECIPIENT_EMAIL:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(SENDER_EMAIL, SENDER_PASSWORD)
            s.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
        log(f"  → E-Mail gesendet: {subject}")

    # Telegram-Push: pro Item ein Bild-Push (max 5 um nicht zu spammen)
    header_sent = False
    items_with_image = [it for it in new_items if it.get("image_url")]
    items_without    = [it for it in new_items if not it.get("image_url")]

    # Erst die mit Bildern (max 5)
    for item in items_with_image[:5]:
        score = item.get("deal_score") or 0
        is_deal = score >= DEAL_THRESHOLD_PCT
        fire = " 🔥 SCHNÄPPCHEN" if is_deal else ""
        caption = f"🔔 <b>{monitor_name}</b>{fire}\n\n<b>{item['title'][:200]}</b>\n"
        if item.get("auction_price"):
            caption += f"  Gebot: {item['auction_price']:.2f} €\n"
        if item.get("sofortkauf_price"):
            caption += f"  Sofortkauf: {item['sofortkauf_price']:.2f} €\n"
        elif item.get("price") and not item.get("auction_price"):
            caption += f"  Preis: {item['price']:.2f} €\n"
        if is_deal and item.get("median_price"):
            caption += f"  📊 Markt: {item['median_price']:.0f} € (<b>-{score:.0f}%</b>)\n"
        caption += f'\n<a href="{item["url"]}">Anzeigen</a>'
        send_telegram_photo(item["image_url"], caption, urgent=is_deal)
        header_sent = True

    # Restliche als Text-Sammelnachricht
    rest = items_with_image[5:] + items_without
    if rest:
        tg_lines = [f"🔔 <b>{monitor_name}</b>{price_hint} · {len(rest)} weitere"] if header_sent else \
                   [f"🔔 <b>{monitor_name}</b> · {count} neues Inserat{'e' if count > 1 else ''}{price_hint}"]
        for item in rest[:10]:
            tg_lines.append(f"\n<b>{item['title'][:80]}</b>")
            p = item.get("sofortkauf_price") or item.get("auction_price") or item.get("price")
            if p:
                tg_lines.append(f"  {p:.2f} €")
            tg_lines.append(f'  <a href="{item["url"]}">Anzeigen</a>')
        if len(rest) > 10:
            tg_lines.append(f"\n…und {len(rest)-10} weitere.")
        send_telegram("\n".join(tg_lines), urgent=False)


def get_listings(monitor: dict) -> list[dict]:
    from parsers import get_listings as _get
    return _get(monitor)


def matches(item: dict, monitor: dict) -> bool:
    keywords         = monitor.get("keywords", [])
    exclude_keywords = monitor.get("exclude_keywords", [])
    min_price        = monitor.get("min_price", 0)
    max_price        = monitor.get("max_price", 0)   # 0 = kein Limit
    sofort_only      = monitor.get("sofortkauf_only", False)

    title_lower = item["title"].lower()

    if keywords:
        if not any(kw.lower() in title_lower for kw in keywords):
            return False

    # Negativ-Filter: wenn eines der Wörter im Titel → raus
    if exclude_keywords:
        if any(kw.strip().lower() in title_lower for kw in exclude_keywords if kw.strip()):
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


def load_price_history() -> dict:
    if not PRICE_HISTORY_FILE.exists():
        return {}
    with open(PRICE_HISTORY_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_price_history(hist: dict):
    # Pro Bucket nur die letzten 200 Datenpunkte behalten
    for bucket in hist.values():
        if isinstance(bucket, dict) and "samples" in bucket and len(bucket["samples"]) > 200:
            bucket["samples"] = bucket["samples"][-200:]
    with open(PRICE_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _bucket_for_item(base_key: str, title: str, keywords: list[str]) -> str:
    """
    Bestimmt den Preis-Bucket für ein Item.
    - Wenn keywords definiert: bucket = base::keyword (erstes Keyword im Titel)
    - Sonst: bucket = base::_all_
    """
    title_lower = title.lower()
    for kw in keywords:
        kw_clean = kw.strip().lower()
        if kw_clean and kw_clean in title_lower:
            return f"{base_key}::{kw_clean}"
    return f"{base_key}::_all_"


def update_history_and_score(base_key: str, items: list[dict], hist: dict,
                             keywords: list[str] = None) -> list[dict]:
    """
    Fügt Preise zum passenden Bucket (pro Keyword) hinzu, gibt items mit 'deal_score' zurück.
    base_key z.B. 'monitor::abc' oder 'sniper::xyz'.
    keywords-Liste bestimmt die Gruppierung.
    """
    keywords = keywords or []

    # Pro Item den richtigen Bucket finden + Preis hinzufügen
    item_buckets = {}   # item_id → bucket_key
    for it in items:
        b = _bucket_for_item(base_key, it.get("title", ""), keywords)
        item_buckets[id(it)] = b
        bucket = hist.setdefault(b, {"samples": [], "median": 0.0})
        p = it.get("sofortkauf_price") or it.get("auction_price") or it.get("price")
        if p and p > 0:
            bucket["samples"].append(p)

    # Mediane neu berechnen (für alle berührten Buckets)
    touched = set(item_buckets.values())
    for b in touched:
        bucket = hist[b]
        if len(bucket["samples"]) >= DEAL_MIN_SAMPLES:
            bucket["median"] = _median(bucket["samples"])

    # Score pro Item
    for it in items:
        b = item_buckets[id(it)]
        median = hist[b].get("median", 0)
        p = it.get("sofortkauf_price") or it.get("auction_price") or it.get("price") or 0
        if median > 0 and p > 0:
            it["deal_score"] = round((1 - p / median) * 100, 1)
            it["median_price"] = round(median, 2)
            it["bucket"] = b
    return items


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

    if EMAIL_ENABLED and SENDER_EMAIL and SENDER_PASSWORD and RECIPIENT_EMAIL:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(SENDER_EMAIL, SENDER_PASSWORD)
            s.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
        log(f"  → Sniper-Mail gesendet: {subject}")

    # Telegram-Push: pro Auktion 1 Bild-Push (zeitkritisch!)
    for a in alerts[:5]:    # max 5 Bilder pro Lauf um nicht zu spammen
        p = a.get("auction_price") or a.get("price")
        caption = (
            f"🔨 <b>{plat_label} ENDET BALD</b> · {watch_name}\n\n"
            f"<b>{a['title'][:200]}</b>\n"
        )
        if p:
            caption += f"💰 {p:.2f} €  ·  {a.get('bids',0)} Gebote\n"
        caption += f"⏱ endet in ~{a['time_left_min']} Min\n\n"
        # Gixen-Link bei eBay-Items
        if platform == "ebay":
            caption += f'<a href="{a["url"]}">JETZT BIETEN</a>  ·  <a href="https://www.gixen.com/index.php?go=mainform&item={a["id"]}">Snipe bei Gixen</a>'
        else:
            caption += f'<a href="{a["url"]}">JETZT BIETEN</a>'

        if a.get("image_url"):
            send_telegram_photo(a["image_url"], caption, urgent=True)
        else:
            send_telegram(caption, urgent=True)


def run_sniper(history: dict = None):
    from parsers import fetch, parse_ebay_auctions, parse_egun
    if history is None:
        history = {}
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
        auctions = []
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
                # eBay: Original-Suchbegriff + alle Tippfehler-Varianten in 1 Watch
                keyword = w.get("keyword", "").strip()
                if not keyword:
                    log(f"[{name}] kein Suchbegriff – übersprungen.")
                    continue
                typo_variants = [v.strip() for v in w.get("typo_variants", []) if v.strip()]
                search_terms = [keyword] + typo_variants
                seen_ids = set()
                for term in search_terms:
                    try:
                        url = f"https://www.ebay.de/sch/i.html?_nkw={term.replace(' ', '+')}&LH_Auction=1&_sop=1"
                        log(f"[{name}] (eBay) suche: {term}")
                        soup = fetch(url)
                        for a in parse_ebay_auctions(soup):
                            if a["id"] not in seen_ids:
                                seen_ids.add(a["id"])
                                auctions.append(a)
                    except Exception as e:
                        log(f"[{name}] FEHLER bei '{term}': {e}")
        except Exception as e:
            log(f"[{name}] FEHLER: {e}")
            continue

        # Optionale Schlagwort-Filter (leer = alle Auktionen)
        keywords         = [k.strip().lower() for k in w.get("keywords", []) if k.strip()]
        exclude_keywords = [k.strip().lower() for k in w.get("exclude_keywords", []) if k.strip()]

        log(f"[{name}] {len(auctions)} Auktionen gefunden"
            + (f" (Filter: {keywords})" if keywords else "")
            + (f" (Negativ: {exclude_keywords})" if exclude_keywords else "") + ".")
        # Preishistorie pflegen für diese Sniper-Suche (pro Keyword bei eGun;
        # bei eBay nutzen wir den Suchbegriff selbst als 1 Keyword)
        sniper_base = f"sniper::{w.get('id', name)}"
        bucket_kws = keywords if keywords else ([w.get("keyword","").strip()] if w.get("keyword") else [])
        auctions = update_history_and_score(sniper_base, auctions, history, bucket_kws)
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
            title_lower = a["title"].lower()
            if keywords and not any(kw in title_lower for kw in keywords):
                continue
            if exclude_keywords and any(kw in title_lower for kw in exclude_keywords):
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
    history  = load_price_history()
    log(f"{len(monitors)} Monitor(e) geladen, {len(seen)} bekannte Einträge, "
        f"{len(history)} Preis-Buckets.")

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
        # Preishistorie pflegen + Score berechnen (Bucket pro Keyword!)
        base = f"monitor::{monitor['id']}"
        listings = update_history_and_score(base, listings, history, monitor.get("keywords", []))

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
                    score = item.get("deal_score") or 0
                    fire = " 🔥" if score >= DEAL_THRESHOLD_PCT else ""
                    score_str = f" ({score:+.0f}% vs. Median)" if score else ""
                    log(f"  NEU{fire}: {item['title'][:55]}  {item.get('price','-')}EUR{score_str}")

        if new_items:
            try:
                send_email(monitor["name"], new_items, monitor.get("min_price", 0), monitor.get("max_price", 0))
            except Exception as e:
                log(f"  E-Mail Fehler: {e}")
        else:
            log(f"[{monitor['name']}] keine neuen Treffer.")

    save_seen(seen)
    save_price_history(history)

    # eBay-Auktions-Sniper
    try:
        run_sniper(history)
    except Exception as e:
        log(f"Sniper Fehler: {e}")

    save_price_history(history)
    log("=== Lauf beendet ===")


if __name__ == "__main__":
    main()
