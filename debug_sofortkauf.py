"""Debug: Sofortkauf vs. Auktion unterscheiden."""
import re
import requests
from bs4 import BeautifulSoup

URL = "https://egun.de/market/list_items.php?cat=492"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

resp = requests.get(URL, headers=headers, timeout=30)
soup = BeautifulSoup(resp.text, "html.parser")

links = [l for l in soup.find_all("a", href=re.compile(r"item\.php\?id=\d+")) if l.get_text(strip=True)]

for link in links[:10]:
    row = link.find_parent("tr")
    if not row:
        continue
    text = row.get_text(" ", strip=True)
    print(f"Titel: {link.get_text(strip=True)[:50]}")
    print(f"Zeilentext: {text[:150]}")
    print(f"Row HTML: {str(row)[:400]}")
    print()
