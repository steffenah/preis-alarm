"""
Site-Parser für den universellen Monitor.
Unterstützt: eGun, Kleinanzeigen, generische Seiten (Foren, Listen etc.)
"""

import re
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

# Kleinanzeigen braucht zusätzliche Browser-ähnliche Headers
HEADERS_KLEINANZEIGEN = {
    **HEADERS,
    "Referer": "https://www.kleinanzeigen.de/",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}


HEADERS_EBAY = {
    **HEADERS,
    "Referer": "https://www.ebay.de/",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}


def fetch(url: str) -> BeautifulSoup:
    if "kleinanzeigen.de" in url:
        headers = HEADERS_KLEINANZEIGEN
    elif "ebay.de" in url or "ebay.com" in url:
        headers = HEADERS_EBAY
    else:
        headers = HEADERS
    session = requests.Session()
    # Erst die Startseite aufrufen (Cookie holen), dann die eigentliche URL
    if "kleinanzeigen.de" in url:
        session.get("https://www.kleinanzeigen.de/", headers=headers, timeout=15)
    elif "ebay.de" in url:
        session.get("https://www.ebay.de/", headers=headers, timeout=15)
    elif "ebay.com" in url:
        session.get("https://www.ebay.com/", headers=headers, timeout=15)
    resp = session.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def detect_site_type(url: str) -> str:
    if "egun.de" in url:
        return "egun"
    if "kleinanzeigen.de" in url:
        return "kleinanzeigen"
    if "ebay.de" in url or "ebay.com" in url:
        return "ebay"
    if "airsoft-verzeichnis.de" in url:
        return "airsoft_verzeichnis"
    return "generic"


# ── eBay Auktions-Parser ──────────────────────────────────────────────────────

def _parse_ebay_time(text: str):
    """'Noch 14 Std 33 Min' / 'Noch 11 Min' → Minuten als int. None wenn nichts."""
    total_min = 0
    found = False
    mt = re.search(r"(\d+)\s*Tag", text, re.IGNORECASE)
    if mt:
        total_min += int(mt.group(1)) * 24 * 60; found = True
    mh = re.search(r"(\d+)\s*Std", text, re.IGNORECASE)
    if mh:
        total_min += int(mh.group(1)) * 60; found = True
    mm = re.search(r"(\d+)\s*Min", text, re.IGNORECASE)
    if mm:
        total_min += int(mm.group(1)); found = True
    ms = re.search(r"(\d+)\s*Sek", text, re.IGNORECASE)
    if ms and total_min == 0:
        total_min = 1; found = True
    return total_min if found else None


def parse_ebay_auctions(soup: BeautifulSoup) -> list[dict]:
    """
    Parst eBay-Suchergebnisse für Auktionen (neue s-card Struktur, 2026).
    Liefert: id, title, price, bids, time_left_min, url.
    """
    listings = []
    seen_ids: set[str] = set()

    cards = soup.find_all(class_=re.compile(r"^s-card$"))
    for card in cards:
        # Link + ID
        link = card.find("a", class_=re.compile(r"s-card__link"))
        if not link:
            continue
        href = link.get("href", "")
        m_id = re.search(r"/itm/(\d+)", href)
        if not m_id:
            continue
        item_id = m_id.group(1)
        if item_id in seen_ids:
            continue

        title_tag = card.find(class_=re.compile(r"s-card__title"))
        title = title_tag.get_text(" ", strip=True) if title_tag else ""
        title = re.sub(r"\s*Wird in neuem Fenster.*$", "", title)
        if not title or title.lower().startswith("shop on ebay"):
            continue

        # Preis aus s-card__price ("EUR 355,00")
        price = None
        price_tag = card.find(class_=re.compile(r"s-card__price"))
        if price_tag:
            raw = price_tag.get_text(" ", strip=True)
            pm = re.search(r"([\d.]+,\d{1,2}|\d+)", raw.replace(".", ""))
            if pm:
                try:
                    price = float(pm.group(1).replace(",", "."))
                except ValueError:
                    pass

        # Attribute durchsuchen für "X Gebote" + "Restzeit Noch ..."
        bids = None  # None = kein Auktion-Attribut gefunden
        time_left_min = None
        for attr in card.find_all(class_=re.compile(r"s-card__attribute")):
            atxt = attr.get_text(" ", strip=True)
            # "0 Gebote" oder "1 Gebot" oder "12 Gebote"
            bm = re.search(r"(\d+)\s*Gebot", atxt, re.IGNORECASE)
            if bm:
                bids = int(bm.group(1))
            # "Restzeit Noch 11 Min" oder "Noch 1 Tag 2 Std"
            if "Restzeit" in atxt or "Noch" in atxt:
                t = _parse_ebay_time(atxt)
                if t is not None:
                    time_left_min = t

        # Nur echte Auktionen behalten (mind. eines von beiden gefunden)
        if bids is None and time_left_min is None:
            continue
        if bids is None:
            bids = 0

        seen_ids.add(item_id)
        item_url = href.split("?")[0]
        listings.append({
            "id": item_id,
            "title": title,
            "price": price,
            "auction_price": price,
            "sofortkauf_price": None,
            "bids": bids,
            "time_left_min": time_left_min,
            "is_sofortkauf": False,
            "url": item_url,
        })

    return listings


# ── eGun ─────────────────────────────────────────────────────────────────────

def _parse_price(text: str):
    m = re.search(r"(\d+(?:[.,]\d{1,2})?)\s*EUR", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            pass
    return None


def parse_egun(soup: BeautifulSoup) -> list[dict]:
    listings = []
    seen_ids: set[str] = set()
    for link in soup.find_all("a", href=re.compile(r"item\.php\?id=\d+")):
        title = link.get_text(strip=True)
        if not title:
            continue
        m = re.search(r"id=(\d+)", link["href"])
        if not m:
            continue
        item_id = m.group(1)
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        auction_price = None
        sofortkauf_price = None
        is_sofortkauf = False
        row = link.find_parent("tr")
        if row:
            row_text = row.get_text(" ", strip=True)
            # Alle Preise in der Zeile finden
            all_prices = []
            for pm in re.finditer(r"(\d+(?:[.,]\d{1,2})?)\s*EUR", row_text, re.IGNORECASE):
                try:
                    all_prices.append(float(pm.group(1).replace(",", ".")))
                except ValueError:
                    pass

            is_auction = "Gebote" in row_text or "Gebot" in row_text
            has_buynow = bool(row.find(class_="ls-buynow") or row.find(attrs={"title": "Sofortkauf-Artikel"}))

            if is_auction:
                # Auktion: erster Preis = aktuelles Gebot, zweiter = Sofortkauf (falls vorhanden)
                if all_prices:
                    auction_price = all_prices[0]
                if len(all_prices) >= 2:
                    sofortkauf_price = all_prices[1]
                    is_sofortkauf = True
            else:
                # Nur Sofortkauf
                sofortkauf_price = all_prices[0] if all_prices else None
                is_sofortkauf = True

        listings.append({
            "id": item_id,
            "title": title,
            "price": sofortkauf_price or auction_price,  # Hauptpreis für Schwellenvergleich
            "auction_price": auction_price,
            "sofortkauf_price": sofortkauf_price,
            "is_sofortkauf": is_sofortkauf,
            "url": f"https://egun.de/market/item.php?id={item_id}",
        })
    return listings


# ── Kleinanzeigen ─────────────────────────────────────────────────────────────

def parse_kleinanzeigen(soup: BeautifulSoup, base_url: str = "https://www.kleinanzeigen.de") -> list[dict]:
    listings = []
    for article in soup.find_all("article", attrs={"data-adid": True}):
        item_id = article["data-adid"]
        title_tag = article.find(class_=re.compile(r"text-module-begin|ellipsis|title"))
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title:
            a = article.find("a", href=re.compile(r"/s-anzeige/"))
            title = a.get_text(strip=True) if a else f"Inserat #{item_id}"

        price = None
        price_tag = article.find(class_=re.compile(r"price|preis", re.I))
        if price_tag:
            raw = price_tag.get_text(strip=True)
            m = re.search(r"(\d+(?:[.,]\d{1,2})?)", raw.replace(".", "").replace(",", "."))
            if m:
                try:
                    price = float(m.group(1))
                except ValueError:
                    pass

        link_tag = article.find("a", href=re.compile(r"/s-anzeige/"))
        item_url = (base_url + link_tag["href"]) if link_tag else ""

        listings.append({
            "id": item_id,
            "title": title,
            "price": price,
            "auction_price": None,
            "sofortkauf_price": price,   # Kleinanzeigen = immer Festpreis
            "is_sofortkauf": True,
            "url": item_url,
        })
    return listings


# ── Airsoft-Verzeichnis Marktplatz ────────────────────────────────────────────

def parse_airsoft_verzeichnis(soup: BeautifulSoup, page_url: str) -> list[dict]:
    listings = []
    seen_ids: set[str] = set()

    for link in soup.find_all("a", href=re.compile(r"threadnummer=\d+")):
        title = link.get_text(strip=True)
        if not title or len(title) < 3:
            continue

        m = re.search(r"threadnummer=(\d+)", link["href"])
        if not m:
            continue
        thread_id = m.group(1)
        if thread_id in seen_ids:
            continue
        seen_ids.add(thread_id)

        # Preis im nächsten Elternelement suchen, das genau diesen einen Link enthält
        price = None
        parent = link.parent
        for _ in range(4):
            if parent is None:
                break
            thread_links_in_parent = parent.find_all("a", href=re.compile(r"threadnummer=\d+"))
            if len(thread_links_in_parent) == 1:
                txt = parent.get_text(" ", strip=True)
                pm = re.search(r"(\d+(?:[.,]\d{1,2})?)\s*EUR", txt, re.IGNORECASE)
                if pm:
                    try:
                        price = float(pm.group(1).replace(",", "."))
                    except ValueError:
                        pass
                break
            parent = parent.parent

        full_url = f"https://www.airsoft-verzeichnis.de/{link['href']}"
        listings.append({
            "id": thread_id,
            "title": title,
            "price": price,
            "auction_price": None,
            "sofortkauf_price": price,
            "is_sofortkauf": True,
            "url": full_url,
        })

    return listings


# ── Generisch (Foren, sonstige Listen) ───────────────────────────────────────

def parse_generic(soup: BeautifulSoup, page_url: str) -> list[dict]:
    """
    Extrahiert alle Links mit Text von der Seite.
    Als ID dient die href, damit neue Links erkannt werden.
    """
    from urllib.parse import urljoin
    listings = []
    seen_hrefs: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        full_url = urljoin(page_url, href)
        if full_url in seen_hrefs:
            continue
        seen_hrefs.add(full_url)

        title = a.get_text(strip=True)
        if len(title) < 5:  # Navigationselemente ignorieren
            continue

        listings.append({
            "id": full_url,
            "title": title,
            "price": None,
            "auction_price": None,
            "sofortkauf_price": None,
            "is_sofortkauf": True,
            "url": full_url,
        })
    return listings


# ── Haupt-Funktion ────────────────────────────────────────────────────────────

def get_listings(monitor: dict) -> list[dict]:
    url = monitor["url"]
    site_type = monitor.get("site_type") or detect_site_type(url)
    soup = fetch(url)

    if site_type == "egun":
        return parse_egun(soup)
    elif site_type == "kleinanzeigen":
        return parse_kleinanzeigen(soup)
    elif site_type == "ebay":
        return parse_ebay_auctions(soup)
    elif site_type == "airsoft_verzeichnis":
        return parse_airsoft_verzeichnis(soup, url)
    else:
        return parse_generic(soup, url)


def matches_keywords(title: str, keywords: list[str]) -> bool:
    """True wenn keywords leer (alles) oder mind. ein Keyword im Titel."""
    if not keywords:
        return True
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)
