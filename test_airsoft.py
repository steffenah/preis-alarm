import requests
from bs4 import BeautifulSoup

URL = "https://www.airsoft-verzeichnis.de/index.php?status=forum&sp=28"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
resp = requests.get(URL, headers=headers, timeout=30)
soup = BeautifulSoup(resp.text, "html.parser")
# Zeige den sichtbaren Text der Seite
print(soup.get_text(" ", strip=True)[:800])
