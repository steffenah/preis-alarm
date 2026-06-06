from parsers import fetch, parse_kleinanzeigen
soup = fetch("https://www.kleinanzeigen.de/s-oldenburg/monitor/k0")
items = parse_kleinanzeigen(soup)
print(f"{len(items)} Inserate gefunden")
for i in items[:5]:
    print(f"  {i['title'][:60]}  Preis: {i['price']}")
