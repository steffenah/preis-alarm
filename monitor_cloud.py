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
TELEGRAM_STATE_FILE  = BASE_DIR / "telegram_state.json"

# Schnäppchen-Score: ab welcher Abweichung gilt etwas als Schnäppchen?
DEAL_THRESHOLD_PCT = 30   # 30% unter Median = 🔥 Schnäppchen
DEAL_MIN_SAMPLES   = 5    # mindestens 5 Daten brauchen wir, um einen Median zu trauen

# Sniper-Konfiguration: Auktion endet in 5-30 Minuten + 0 Gebote → benachrichtigen
SNIPER_WINDOW_MIN_LO = 5
SNIPER_WINDOW_MIN_HI = 30

# Auto-Tippfehler-Vorschläge (nervig? Per env AUTO_LEARN_TYPOS=1 anschalten)
AUTO_LEARN_TYPOS = os.environ.get("AUTO_LEARN_TYPOS", "0") == "1"

# Nachtruhe (Telegram still zwischen QUIET_HOURS_START und QUIET_HOURS_END)
# Sniper-Alarme sind IMMER laut (zeitkritisch).
QUIET_HOURS_START = 23   # 23 Uhr
QUIET_HOURS_END   = 7    # bis 7 Uhr morgens


def _is_quiet_now() -> bool:
    h = datetime.now().hour
    if QUIET_HOURS_START < QUIET_HOURS_END:
        return QUIET_HOURS_START <= h < QUIET_HOURS_END
    return h >= QUIET_HOURS_START or h < QUIET_HOURS_END

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
    """Sendet eine reine Textnachricht via Telegram. Nachtruhe: still wenn nicht urgent."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    silent = (not urgent) and _is_quiet_now()
    ok = _tg_call("sendMessage", {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
        "disable_notification": "true" if silent else "false",
    })
    if ok:
        log(f"  → Telegram gesendet" + (" (still)" if silent else ""))
    return ok


def send_telegram_photo(photo_url: str, caption: str, urgent: bool = False) -> bool:
    """Schickt ein Bild mit Caption (max 1024 Zeichen)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not photo_url:
        return send_telegram(caption, urgent=urgent)
    # Telegram braucht http(s) URLs
    if not photo_url.startswith("http"):
        return send_telegram(caption, urgent=urgent)
    silent = (not urgent) and _is_quiet_now()
    ok = _tg_call("sendPhoto", {
        "chat_id": TELEGRAM_CHAT_ID,
        "photo": photo_url,
        "caption": caption[:1020],
        "parse_mode": "HTML",
        "disable_notification": "true" if silent else "false",
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


def _match_advanced(title_lower: str, expressions: list[str]) -> bool:
    """
    Advanced Keyword-Matching:
      - Liste = OR (mind. 1 Element matched)
      - In einem Element '&' = AND (alle Teile müssen vorkommen)
      - In Anführungszeichen "..." = exakte Phrase
    Beispiel: ['"iphone 15 pro" & 256gb', '"samsung s24"']
      → (iPhone 15 Pro UND 256gb) ODER (Samsung S24)
    """
    if not expressions:
        return True
    for expr in expressions:
        if not expr or not expr.strip():
            continue
        # AND-Teile splitten
        parts = [p.strip() for p in expr.split("&")]
        all_matched = True
        for part in parts:
            if not part:
                continue
            # Phrase entpacken
            if (part.startswith('"') and part.endswith('"')) or \
               (part.startswith("'") and part.endswith("'")):
                term = part[1:-1].lower()
            else:
                term = part.lower()
            if term and term not in title_lower:
                all_matched = False
                break
        if all_matched:
            return True
    return False


def matches(item: dict, monitor: dict) -> bool:
    keywords         = monitor.get("keywords", [])
    exclude_keywords = monitor.get("exclude_keywords", [])
    exclude_sellers  = monitor.get("exclude_sellers", [])
    min_price        = monitor.get("min_price", 0)
    max_price        = monitor.get("max_price", 0)   # 0 = kein Limit
    sofort_only      = monitor.get("sofortkauf_only", False)

    title_lower = item["title"].lower()

    # OR/AND/Phrasen-Matching für Keywords
    if keywords and not _match_advanced(title_lower, keywords):
        return False

    # Negativ-Filter: wenn eines der Wörter im Titel → raus (unterstützt auch Phrasen)
    if exclude_keywords and _match_advanced(title_lower, exclude_keywords):
        return False

    # Verkäufer-Filter (case-insensitive)
    if exclude_sellers and item.get("seller"):
        seller_lower = item["seller"].lower()
        if any(s.strip().lower() in seller_lower for s in exclude_sellers if s.strip()):
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


# ── Telegram-Befehle ────────────────────────────────────────────────────────

def _tg_state() -> dict:
    if not TELEGRAM_STATE_FILE.exists():
        return {"last_update_id": 0}
    with open(TELEGRAM_STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def _tg_state_save(state: dict):
    with open(TELEGRAM_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _save_monitors_to_disk(monitors_list: list[dict]):
    """Schreibt monitors.json zurück (für /pause / /resume Commands)."""
    with open(MON_FILE, "w", encoding="utf-8") as f:
        json.dump({"monitors": monitors_list}, f, ensure_ascii=False, indent=2)


def _save_sniper_to_disk(watches: list[dict]):
    with open(SNIPER_FILE, "w", encoding="utf-8") as f:
        json.dump({"watches": watches}, f, ensure_ascii=False, indent=2)


def _find_by_name(name: str, items: list[dict]) -> int:
    """Findet Index in items per (substring, case-insensitive) Name-Suche."""
    name_lower = name.lower().strip()
    for i, it in enumerate(items):
        if name_lower in it.get("name", "").lower():
            return i
    return -1


def handle_telegram_command(text: str) -> str:
    """Verarbeitet einen /-Befehl und gibt die Antwort als String zurück."""
    text = text.strip()
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/help", "/start"):
        return (
            "🤖 <b>Preis-Alarm Bot</b>\n\n"
            "/list  – alle aktiven Monitore + Sniper\n"
            "/stats  – kurze Statistik\n"
            "/pause &lt;name&gt;  – Watch pausieren\n"
            "/resume &lt;name&gt;  – Watch wieder aktivieren\n"
            "/typoadd &lt;name&gt; &lt;variante&gt;  – Tippfehler hinzufügen\n"
            "/now  – sofort jetzt prüfen\n"
            "/help  – diese Hilfe"
        )

    if cmd == "/list":
        mons = load_monitors()
        wch  = load_sniper_watches()
        lines = ["📋 <b>Monitore</b>"]
        for m in mons:
            ic = "🟢" if m.get("enabled", True) else "⏸️"
            lines.append(f"  {ic} {m.get('name','?')} [{m.get('site_type','?')}]")
        lines.append("\n🔨 <b>Sniper</b>")
        for w in wch:
            ic = "🟢" if w.get("enabled", True) else "⏸️"
            plat = w.get("platform","ebay")
            sub = w.get("keyword") if plat=="ebay" else (w.get("url","")[:30]+"...")
            lines.append(f"  {ic} {w.get('name','?')} ({plat}) – {sub}")
        return "\n".join(lines)

    if cmd == "/stats":
        seen = load_seen()
        hist = load_price_history()
        return (
            "📊 <b>Statistik</b>\n"
            f"Bekannte Inserate: <b>{len(seen)}</b>\n"
            f"Preis-Buckets: <b>{len(hist)}</b>\n"
            f"Letzter Lauf: jetzt"
        )

    if cmd == "/pause":
        if not arg:
            return "❌ Nutzung: <code>/pause &lt;name&gt;</code>"
        mons = load_monitors()
        wch  = load_sniper_watches()
        idx_m = _find_by_name(arg, mons)
        idx_w = _find_by_name(arg, wch)
        if idx_m >= 0:
            mons[idx_m]["enabled"] = False
            _save_monitors_to_disk(mons)
            return f"⏸️ Monitor »{mons[idx_m]['name']}« pausiert."
        if idx_w >= 0:
            wch[idx_w]["enabled"] = False
            _save_sniper_to_disk(wch)
            return f"⏸️ Sniper »{wch[idx_w]['name']}« pausiert."
        return f"❌ Nichts mit »{arg}« gefunden."

    if cmd == "/resume":
        if not arg:
            return "❌ Nutzung: <code>/resume &lt;name&gt;</code>"
        mons = load_monitors()
        wch  = load_sniper_watches()
        idx_m = _find_by_name(arg, mons)
        idx_w = _find_by_name(arg, wch)
        if idx_m >= 0:
            mons[idx_m]["enabled"] = True
            _save_monitors_to_disk(mons)
            return f"▶️ Monitor »{mons[idx_m]['name']}« aktiviert."
        if idx_w >= 0:
            wch[idx_w]["enabled"] = True
            _save_sniper_to_disk(wch)
            return f"▶️ Sniper »{wch[idx_w]['name']}« aktiviert."
        return f"❌ Nichts mit »{arg}« gefunden."

    if cmd == "/now":
        return "🔄 OK – läuft schon jetzt 😉"

    if cmd == "/typoadd":
        # /typoadd <name> <variante>
        a = arg.split()
        if len(a) < 2:
            return "❌ Nutzung: <code>/typoadd &lt;watch-name&gt; &lt;variante&gt;</code>"
        # Letztes Wort = Variante, Rest = Name
        variant = a[-1]
        wname   = " ".join(a[:-1])
        wch = load_sniper_watches()
        idx = _find_by_name(wname, wch)
        if idx < 0:
            return f"❌ Sniper »{wname}« nicht gefunden."
        if wch[idx].get("platform") != "ebay":
            return "❌ Tippfehler-Varianten gibt's nur bei eBay-Sniper."
        wch[idx].setdefault("typo_variants", [])
        if variant in wch[idx]["typo_variants"]:
            return f"ℹ️ »{variant}« ist bereits drin."
        wch[idx]["typo_variants"].append(variant)
        _save_sniper_to_disk(wch)
        return f"✅ »{variant}« zu »{wch[idx]['name']}« hinzugefügt."

    return f"❓ Unbekannter Befehl: <code>{cmd}</code>\nTipp: /help"


def process_telegram_commands():
    """Holt neue Telegram-Updates (Commands) ab und beantwortet sie."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    state = _tg_state()
    last_id = state.get("last_update_id", 0)
    try:
        import urllib.request, urllib.parse, json as _j
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = urllib.parse.urlencode({"offset": last_id + 1, "timeout": 0})
        with urllib.request.urlopen(f"{url}?{params}", timeout=10) as resp:
            data = _j.loads(resp.read())
    except Exception as e:
        log(f"Telegram-Polling Fehler: {e}")
        return

    updates = data.get("result", [])
    if not updates:
        return

    log(f"📲 {len(updates)} Telegram-Command(s) erhalten")
    new_last = last_id
    for u in updates:
        new_last = max(new_last, u.get("update_id", 0))
        msg = u.get("message") or {}
        text = (msg.get("text") or "").strip()
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        # Nur unsere eigene Chat-ID akzeptieren!
        if chat_id != str(TELEGRAM_CHAT_ID):
            continue
        if not text.startswith("/"):
            continue
        try:
            reply = handle_telegram_command(text)
            send_telegram(reply, urgent=True)
        except Exception as e:
            log(f"Command-Fehler: {e}")
            send_telegram(f"❌ Fehler: {e}", urgent=True)

    state["last_update_id"] = new_last
    _tg_state_save(state)


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
        caption += f"⏱ endet in ~{a['time_left_min']} Min\n"
        # Markt-Median + Score (mit Quellen-Label)
        if a.get("median_price"):
            src = a.get("median_source", "geschätzt")
            score = a.get("deal_score", 0)
            caption += f"📊 Markt ({src}): {a['median_price']:.0f} € ({score:+.0f}%)\n"
        caption += "\n"
        # Gixen-Link bei eBay-Items
        if platform == "ebay":
            caption += f'<a href="{a["url"]}">JETZT BIETEN</a>  ·  <a href="https://www.gixen.com/index.php?go=mainform&item={a["id"]}">Snipe bei Gixen</a>'
        else:
            caption += f'<a href="{a["url"]}">JETZT BIETEN</a>'

        if a.get("image_url"):
            send_telegram_photo(a["image_url"], caption, urgent=True)
        else:
            send_telegram(caption, urgent=True)


def _levenshtein(a: str, b: str) -> int:
    """Iterative Levenshtein-Distanz."""
    if a == b: return 0
    if not a: return len(b)
    if not b: return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j-1] + 1, prev[j] + 1, prev[j-1] + cost)
        prev = curr
    return prev[-1]


def auto_learn_typos(watch: dict, found_items: list[dict]) -> list[str]:
    """
    Analysiert gefundene Item-Titel und schlägt neue Tippfehler-Varianten vor.
    Pro Wort im Suchbegriff: finde ähnliche Wörter in Titeln (Distanz 1-2).
    Liefert max 3 Vorschläge, die noch nicht in typo_variants sind.
    """
    keyword = (watch.get("keyword") or "").strip().lower()
    if not keyword or len(keyword) < 4:
        return []
    existing = set(v.lower() for v in (watch.get("typo_variants") or [])) | {keyword}

    # Wörter aus dem Suchbegriff einzeln betrachten (für jedes Wort eigene Varianten)
    kw_parts = keyword.split()
    candidates = {}   # variant_word → count

    import re as _re
    for item in found_items:
        title = (item.get("title") or "").lower()
        title_words = _re.findall(r"[a-zäöüß0-9]{3,}", title)
        for kw in kw_parts:
            for tw in title_words:
                if tw == kw:
                    continue
                # Distanz 1 oder 2 zum Schlüsselwort + nicht zu kurz
                if abs(len(tw) - len(kw)) <= 2 and _levenshtein(tw, kw) in (1, 2):
                    candidates[tw] = candidates.get(tw, 0) + 1

    # Mindestens 3 unterschiedliche Items + nicht schon vorhanden
    suggestions = []
    for word, count in sorted(candidates.items(), key=lambda x: -x[1]):
        if count < 3:
            continue
        # Ersetze das ähnliche Wort im Suchbegriff
        for kw in kw_parts:
            if word in existing:
                continue
            if _levenshtein(word, kw) in (1, 2):
                variant = keyword.replace(kw, word, 1)
                if variant not in existing and variant not in suggestions:
                    suggestions.append(variant)
                    existing.add(variant)
                    if len(suggestions) >= 3:
                        return suggestions
    return suggestions


def fetch_ebay_sold_median(keyword: str, history: dict) -> float:
    """
    Holt verkaufte eBay-Items für 'keyword' und speichert/aktualisiert den Sold-Median.
    Wird höchstens alle 6h pro Keyword refreshed.
    """
    from parsers import fetch, parse_ebay_sold
    bucket_key = f"ebay_sold::{keyword.lower()}"
    bucket = history.setdefault(bucket_key, {"samples": [], "median": 0.0, "last_refresh": ""})

    # Refresh nur alle 6h
    now = datetime.now()
    try:
        last = datetime.fromisoformat(bucket.get("last_refresh", "1970-01-01"))
        if (now - last).total_seconds() < 6 * 3600:
            return bucket.get("median", 0.0)
    except Exception:
        pass

    try:
        url = f"https://www.ebay.de/sch/i.html?_nkw={keyword.replace(' ', '+')}&LH_Sold=1&LH_Complete=1"
        log(f"  ↻ Sold-Refresh: {keyword}")
        soup = fetch(url)
        sold = parse_ebay_sold(soup)
        if sold:
            # Letzte 50 verkaufte Preise behalten
            bucket["samples"] = [s["price"] for s in sold[:50]]
            if len(bucket["samples"]) >= 5:
                bucket["median"] = _median(bucket["samples"])
            bucket["last_refresh"] = now.isoformat()
            log(f"  ↻ Sold-Median für »{keyword}«: {bucket['median']:.2f} € aus {len(bucket['samples'])} Verkäufen")
    except Exception as e:
        log(f"  Sold-Fehler: {e}")

    return bucket.get("median", 0.0)


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
        exclude_sellers  = [s.strip().lower() for s in w.get("exclude_sellers", []) if s.strip()]

        log(f"[{name}] {len(auctions)} Auktionen gefunden"
            + (f" (Filter: {keywords})" if keywords else "")
            + (f" (Negativ: {exclude_keywords})" if exclude_keywords else "") + ".")
        # Preishistorie pflegen für diese Sniper-Suche (pro Keyword bei eGun;
        # bei eBay nutzen wir den Suchbegriff selbst als 1 Keyword)
        sniper_base = f"sniper::{w.get('id', name)}"
        bucket_kws = keywords if keywords else ([w.get("keyword","").strip()] if w.get("keyword") else [])
        auctions = update_history_and_score(sniper_base, auctions, history, bucket_kws)

        # Bei eBay: ECHTEN Marktwert (Sold-Listings) holen und Score überschreiben
        if platform == "ebay" and w.get("keyword"):
            sold_median = fetch_ebay_sold_median(w["keyword"], history)
            if sold_median > 0:
                for a in auctions:
                    p = a.get("auction_price") or a.get("price")
                    if p and p > 0:
                        a["deal_score"] = round((1 - p / sold_median) * 100, 1)
                        a["median_price"] = round(sold_median, 2)
                        a["median_source"] = "verkauft"   # für Email/Telegram
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
            # Schlagwort-Filter (OR/AND/Phrasen)
            title_lower = a["title"].lower()
            if keywords and not _match_advanced(title_lower, keywords):
                continue
            if exclude_keywords and _match_advanced(title_lower, exclude_keywords):
                continue
            # Verkäufer-Filter
            if exclude_sellers and a.get("seller"):
                if any(s in a["seller"].lower() for s in exclude_sellers):
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

        # Auto-Tippfehler-Lernen (max 1x pro 24h pro Watch)
        if AUTO_LEARN_TYPOS and platform == "ebay" and auctions:
            last_learn = w.get("_last_typo_learn", "1970-01-01")
            try:
                last_dt = datetime.fromisoformat(last_learn)
                if (datetime.now() - last_dt).total_seconds() < 24 * 3600:
                    continue
            except Exception:
                pass
            suggestions = auto_learn_typos(w, auctions)
            if suggestions:
                # Im Watch speichern, dass wir gelernt haben (Datum)
                w["_last_typo_learn"] = datetime.now().isoformat()
                msg = (
                    f"💡 <b>Tippfehler-Vorschlag</b> für »{name}«\n\n"
                    f"In den Treffern habe ich {len(suggestions)} neue Varianten entdeckt, "
                    f"die noch nicht in deiner Suche sind:\n\n"
                    + "\n".join(f"• <code>{s}</code>" for s in suggestions) +
                    f"\n\nMit <code>/typoadd {name} {suggestions[0]}</code> hinzufügen, "
                    f"oder per Web-App im Tippfehler-Feld."
                )
                send_telegram(msg, urgent=False)
                # Watch-Liste persistieren (Lerndatum)
                all_w = load_sniper_watches()
                for x in all_w:
                    if x.get("id") == w.get("id"):
                        x["_last_typo_learn"] = w["_last_typo_learn"]
                _save_sniper_to_disk(all_w)

    save_sniper_notified(notified)


def main():
    log("=== Monitor Cloud-Lauf gestartet ===")
    # Telegram-Commands abarbeiten (kann monitors.json/sniper_watches.json modifizieren!)
    try:
        process_telegram_commands()
    except Exception as e:
        log(f"Telegram-Command-Fehler: {e}")

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
