"""Erstellt ein Shopping-Cart Icon mit grünem Hintergrund."""
from PIL import Image, ImageDraw
from pathlib import Path

def create_shopping_cart_icon():
    sizes = [256, 128, 64, 48, 32, 16]
    images = []

    for size in sizes:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        # Grüner abgerundeter Hintergrund
        margin = int(size * 0.04)
        d.rounded_rectangle(
            [margin, margin, size - margin, size - margin],
            radius=int(size * 0.18),
            fill=(34, 160, 74)   # kräftiges Grün
        )

        # Farben für den Warenkorb (weiß)
        w = (255, 255, 255)
        s = size

        # --- Warenkorb-Zeichnung (skaliert auf Bildgröße) ---
        # Griff / Stange oben links
        handle_x1 = int(s * 0.10)
        handle_y1 = int(s * 0.18)
        handle_x2 = int(s * 0.22)
        handle_y2 = int(s * 0.26)
        d.ellipse([handle_x1, handle_y1, handle_x2, handle_y2], fill=w)

        # Diagonale Stange vom Griff zum Korb
        lw = max(1, int(s * 0.055))
        d.line([
            int(s * 0.18), int(s * 0.23),
            int(s * 0.30), int(s * 0.40),
        ], fill=w, width=lw)

        # Korbkörper (Trapez)
        bx1 = int(s * 0.28)
        bx2 = int(s * 0.88)
        by1 = int(s * 0.38)
        by2 = int(s * 0.68)
        offset = int(s * 0.06)
        d.polygon([
            (bx1,          by1),
            (bx2,          by1),
            (bx2 - offset, by2),
            (bx1 + offset, by2),
        ], fill=w)

        # Innenfläche (grün = "ausgehöhlt")
        inner = int(s * 0.045)
        d.polygon([
            (bx1 + inner,          by1 + inner),
            (bx2 - inner,          by1 + inner),
            (bx2 - offset - inner, by2 - inner),
            (bx1 + offset + inner, by2 - inner),
        ], fill=(34, 160, 74))

        # Obere Leiste des Korbs
        d.rectangle([bx1, by1, bx2, by1 + lw], fill=w)

        # Drei senkrechte Stäbe im Korb
        for frac in [0.42, 0.57, 0.72]:
            bx = int(s * frac)
            d.line([(bx, by1 + lw + 1), (bx - int(offset * 0.4), by2 - 2)], fill=w, width=max(1, lw - 1))

        # Griff-Bogen (Halbkreis oben)
        arc_lw = max(1, int(s * 0.055))
        arc_box = [int(s * 0.30), int(s * 0.15), int(s * 0.75), int(s * 0.48)]
        d.arc(arc_box, start=200, end=360, fill=w, width=arc_lw)

        # Zwei Räder
        r = int(s * 0.07)
        for cx in [int(s * 0.38), int(s * 0.72)]:
            cy = int(s * 0.78)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=w)
            d.ellipse([cx - r + max(1, int(r * 0.35)),
                       cy - r + max(1, int(r * 0.35)),
                       cx + r - max(1, int(r * 0.35)),
                       cy + r - max(1, int(r * 0.35))],
                      fill=(34, 160, 74))

        images.append(img)

    out = Path(__file__).parent / "icon_cart.ico"
    images[0].save(out, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[1:])
    print(f"Icon gespeichert: {out}")
    return out


if __name__ == "__main__":
    create_shopping_cart_icon()
