import re, requests
from bs4 import BeautifulSoup

URL = "https://www.airsoft-verzeichnis.de/index.php?status=forum&sp=28"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
soup = BeautifulSoup(requests.get(URL, headers=headers, timeout=30).text, "html.parser")

links = soup.find_all("a", href=re.compile(r"threadnummer=\d+"))

for link in links[:3]:
    title = link.get_text(strip=True)
    thread_id = re.search(r"threadnummer=(\d+)", link["href"]).group(1)
    print(f"=== {title[:60]} [ID: {thread_id}] ===")
    parent = link.parent
    for level in range(6):
        if parent is None: break
        txt = parent.get_text(" ", strip=True)
        tag = parent.name
        cls = parent.get("class","")
        print(f"  L{level} <{tag} class={cls}>: {txt[:100]!r}")
        parent = parent.parent
    print()
