"""Debug: Rohe HTML-Struktur einer Inseratszeile ausgeben."""
import re
import requests
from bs4 import BeautifulSoup

URL = "https://egun.de/market/list_items.php?cat=492"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

resp = requests.get(URL, headers=headers, timeout=30)
soup = BeautifulSoup(resp.text, "html.parser")

# Suche alle Links zu Inseraten
links = soup.find_all("a", href=re.compile(r"item\.php\?id=\d+"))
print(f"Gefunden: {len(links)} Links\n")

# Zeige die ersten 3 Links mit ihrem HTML-Kontext
for link in links[:3]:
    print("=== LINK ===")
    print(f"Text: {link.get_text(strip=True)!r}")
    print(f"Href: {link['href']}")

    # Zeige den Elternkontext
    parent = link.parent
    for level in range(5):
        if parent is None:
            break
        text = parent.get_text(" ", strip=True)
        tag = parent.name
        classes = parent.get("class", [])
        print(f"  Level {level}: <{tag} class={classes}> text={text[:120]!r}")

        # Preis gefunden?
        if re.search(r'\d+[.,]\d{1,2}\s*\xe2\x82\xac|\d+\s*EUR|\d+[.,]\d{1,2}\s*Euro', text, re.I):
            print(f"    --> Preis-Pattern gefunden!")
        parent = parent.parent
    print()

# Suche nach Preis-Mustern im gesamten HTML
price_patterns = re.findall(r'.{0,30}\d+[.,]\d{1,2}.{0,10}(?:EUR|euro|Euro|€|\xe2\x82\xac).{0,20}', resp.text[:5000])
print("\n=== PREIS-MUSTER IM HTML ===")
for p in price_patterns[:10]:
    print(repr(p))
