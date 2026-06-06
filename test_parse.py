"""Schnelltest: Seite abrufen und Inserate parsen (kein E-Mail-Versand)."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))

from monitor import fetch_listings, MIN_PRICE

listings = fetch_listings()
print(f"\n{len(listings)} Inserate gefunden:\n")
over_threshold = [l for l in listings if l["price"] and l["price"] > MIN_PRICE]
under = [l for l in listings if not l["price"] or l["price"] <= MIN_PRICE]

print(f"=== Über {MIN_PRICE:.0f}€ ({len(over_threshold)} Stück) ===")
for item in over_threshold:
    print(f"  [{item['id']}] {item['title'][:55]:55s} {item['price']:>8.2f}€")

print(f"\n=== Unter/gleich {MIN_PRICE:.0f}€ oder ohne Preis ({len(under)} Stück) ===")
for item in under:
    price_str = f"{item['price']:.2f}€" if item["price"] else "   ???  "
    print(f"  [{item['id']}] {item['title'][:55]:55s} {price_str:>8}")
