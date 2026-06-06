"""
Monitor Web-Interface – Streamlit App
Verwalte alle Monitore von überall über den Browser.
"""

import json
import uuid
import streamlit as st
from github import Github, GithubException

# ── Seiten-Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Preis-Alarm",
    page_icon="🛒",
    layout="wide",
)

# ── PWA-Setup: App-Manifest + Mobile-Tags injizieren ───────────────────────────
st.markdown("""
<link rel="manifest" href="data:application/manifest+json,%7B%22name%22%3A%22Preis-Alarm%22%2C%22short_name%22%3A%22Preis-Alarm%22%2C%22start_url%22%3A%22.%22%2C%22display%22%3A%22standalone%22%2C%22background_color%22%3A%22%23111111%22%2C%22theme_color%22%3A%22%2322a04a%22%2C%22icons%22%3A%5B%7B%22src%22%3A%22https%3A%2F%2Fem-content.zobj.net%2Fsource%2Fgoogle%2F387%2Fshopping-cart_1f6d2.png%22%2C%22sizes%22%3A%22192x192%22%2C%22type%22%3A%22image%2Fpng%22%7D%5D%7D">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Preis-Alarm">
<link rel="apple-touch-icon" href="https://em-content.zobj.net/source/google/387/shopping-cart_1f6d2.png">
<meta name="theme-color" content="#22a04a">
""", unsafe_allow_html=True)

# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def get_repo():
    g = Github(st.secrets["github"]["token"])
    return g.get_repo(st.secrets["github"]["repo"])


def load_monitors() -> list[dict]:
    try:
        repo = get_repo()
        f = repo.get_contents("monitors.json")
        return json.loads(f.decoded_content)["monitors"]
    except Exception as e:
        st.error(f"Fehler beim Laden: {e}")
        return []


def save_monitors(monitors: list[dict]) -> bool:
    try:
        repo = get_repo()
        f = repo.get_contents("monitors.json")
        new_content = json.dumps({"monitors": monitors}, ensure_ascii=False, indent=2)
        repo.update_file(
            "monitors.json",
            "chore: monitors via Web-UI aktualisiert [skip ci]",
            new_content,
            f.sha,
        )
        return True
    except Exception as e:
        st.error(f"Fehler beim Speichern: {e}")
        return False


def detect_site_type(url: str) -> str:
    if "egun.de" in url:
        return "egun"
    if "kleinanzeigen.de" in url:
        return "kleinanzeigen"
    if "ebay.de" in url or "ebay.com" in url:
        return "ebay"
    return "generic"


# ── Sniper-Watches (eBay-Auktionen) ────────────────────────────────────────────

def load_sniper_watches() -> list[dict]:
    try:
        repo = get_repo()
        f = repo.get_contents("sniper_watches.json")
        return json.loads(f.decoded_content).get("watches", [])
    except Exception:
        return []


def save_sniper_watches(watches: list[dict]) -> bool:
    try:
        repo = get_repo()
        new_content = json.dumps({"watches": watches}, ensure_ascii=False, indent=2)
        try:
            f = repo.get_contents("sniper_watches.json")
            repo.update_file(
                "sniper_watches.json",
                "chore: sniper watches via Web-UI aktualisiert [skip ci]",
                new_content,
                f.sha,
            )
        except GithubException:
            repo.create_file(
                "sniper_watches.json",
                "chore: sniper watches angelegt [skip ci]",
                new_content,
            )
        return True
    except Exception as e:
        st.error(f"Fehler beim Speichern: {e}")
        return False


# ── Login ──────────────────────────────────────────────────────────────────────

def show_login():
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.image("https://em-content.zobj.net/source/google/387/shopping-cart_1f6d2.png", width=80)
        st.title("Monitor Einstellungen")
        st.markdown("---")
        username = st.text_input("👤 Benutzername")
        password = st.text_input("🔒 Passwort", type="password")
        if st.button("Anmelden", use_container_width=True, type="primary"):
            if (username == st.secrets["login"]["username"] and
                    password == st.secrets["login"]["password"]):
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("❌ Falscher Benutzername oder Passwort")


# ── Haupt-App ──────────────────────────────────────────────────────────────────

def show_app():
    # Sidebar
    with st.sidebar:
        st.image("https://em-content.zobj.net/source/google/387/shopping-cart_1f6d2.png", width=50)
        st.title("Monitor")
        st.markdown("---")
        if st.button("🚪 Abmelden", use_container_width=True):
            st.session_state.logged_in = False
            st.rerun()
        st.markdown("---")
        st.caption("Änderungen werden direkt zu GitHub synchronisiert und beim nächsten 10-Minuten-Lauf aktiv.")

    st.title("🛒 Preis-Alarm")

    tab_monitors, tab_sniper, tab_email, tab_install, tab_info = st.tabs([
        "📋 Meine Monitore",
        "🔨 Auktions-Sniper",
        "📧 E-Mail",
        "📱 App installieren",
        "ℹ️ Hilfe & URLs",
    ])

    # ── Tab: Monitore ──────────────────────────────────────────────────────────
    with tab_monitors:
        monitors = load_monitors()

        # Bestehende Monitore anzeigen
        st.subheader(f"Aktive Monitore ({len(monitors)})")

        for i, m in enumerate(monitors):
            is_enabled = m.get("enabled", True)
            status = "🟢" if is_enabled else "⏸️"

            # Pause-Button außerhalb des Expanders (direkt sichtbar)
            hcol1, hcol2 = st.columns([5, 1])
            with hcol1:
                expander_open = st.expander(f"{status} {m.get('name', 'Ohne Namen')}", expanded=False)
            with hcol2:
                pause_label = "▶️ An" if not is_enabled else "⏸️ Aus"
                if st.button(pause_label, key=f"pause_{i}", use_container_width=True):
                    monitors[i] = {**m, "enabled": not is_enabled}
                    if save_monitors(monitors):
                        st.rerun()

            with expander_open:
                col1, col2 = st.columns(2)
                with col1:
                    new_name = st.text_input("Name", value=m.get("name", ""), key=f"name_{i}")
                    new_url  = st.text_input("URL", value=m.get("url", ""), key=f"url_{i}")
                    new_kw   = st.text_input(
                        "Suchbegriffe (kommagetrennt, leer = alles)",
                        value=", ".join(m.get("keywords", [])),
                        key=f"kw_{i}",
                        help="z.B.  airsoft, sniper, gbb"
                    )
                with col2:
                    new_price     = st.number_input("Mindestpreis (€)  (0 = kein Limit)", value=float(m.get("min_price", 0)), min_value=0.0, step=5.0, key=f"price_{i}")
                    new_max_price = st.number_input("Maximalpreis (€)  (0 = kein Limit)", value=float(m.get("max_price", 0)), min_value=0.0, step=5.0, key=f"maxprice_{i}")
                    new_sofort    = st.checkbox("Nur Sofortkauf / Festpreis", value=m.get("sofortkauf_only", False), key=f"sofort_{i}")
                    new_active    = st.checkbox("Monitor aktiv", value=m.get("enabled", True), key=f"active_{i}")

                bcol1, bcol2, _ = st.columns([1, 1, 3])
                with bcol1:
                    if st.button("💾 Speichern", key=f"save_{i}", use_container_width=True):
                        kws = [k.strip() for k in new_kw.split(",") if k.strip()]
                        monitors[i] = {
                            **m,
                            "name": new_name,
                            "url": new_url,
                            "keywords": kws,
                            "min_price": new_price,
                            "max_price": new_max_price,
                            "sofortkauf_only": new_sofort,
                            "enabled": new_active,
                            "site_type": detect_site_type(new_url),
                        }
                        if save_monitors(monitors):
                            st.success("✅ Gespeichert und zu GitHub synchronisiert!")
                with bcol2:
                    if st.button("🗑 Löschen", key=f"del_{i}", use_container_width=True):
                        monitors.pop(i)
                        if save_monitors(monitors):
                            st.success("Gelöscht!")
                            st.rerun()

        st.markdown("---")
        st.subheader("➕ Neuen Monitor hinzufügen")

        with st.form("new_monitor", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                n_name  = st.text_input("Name *", placeholder="z.B. Kleinanzeigen Airsoft")
                n_url   = st.text_input("URL *", placeholder="https://www.kleinanzeigen.de/s-oldenburg/airsoft/k0")
                n_kw    = st.text_input("Suchbegriffe (leer = alles)", placeholder="airsoft, sniper, gbb")
            with col2:
                n_price     = st.number_input("Mindestpreis (€)  (0 = kein Limit)", min_value=0.0, step=5.0)
                n_max_price = st.number_input("Maximalpreis (€)  (0 = kein Limit)", min_value=0.0, step=5.0)
                n_sofort    = st.checkbox("Nur Sofortkauf / Festpreis")
                n_active    = st.checkbox("Monitor sofort aktivieren", value=True)

            submitted = st.form_submit_button("➕ Hinzufügen", use_container_width=True, type="primary")
            if submitted:
                if not n_name or not n_url:
                    st.error("Name und URL sind Pflichtfelder.")
                else:
                    kws = [k.strip() for k in n_kw.split(",") if k.strip()]
                    monitors.append({
                        "id": str(uuid.uuid4())[:8],
                        "name": n_name,
                        "url": n_url,
                        "site_type": detect_site_type(n_url),
                        "keywords": kws,
                        "min_price": n_price,
                        "max_price": n_max_price,
                        "sofortkauf_only": n_sofort,
                        "enabled": n_active,
                    })
                    if save_monitors(monitors):
                        st.success(f"✅ Monitor »{n_name}« hinzugefügt!")
                        st.rerun()

    # ── Tab: Auktions-Sniper ───────────────────────────────────────────────────
    with tab_sniper:
        st.subheader("🔨 Auktions-Sniper")
        st.markdown(
            "Findet **eBay**- oder **eGun**-Auktionen, die kurz vor dem Ende stehen und noch "
            "**keine Gebote** haben – perfekt für Schnäppchen-Jäger. Du bekommst eine E-Mail mit hoher Priorität."
        )

        watches = load_sniper_watches()
        st.caption(f"Aktive Suchen: {len(watches)}")

        for i, w in enumerate(watches):
            is_enabled = w.get("enabled", True)
            status = "🟢" if is_enabled else "⏸️"
            plat = w.get("platform", "ebay")
            plat_icon = "🛒" if plat == "egun" else "🅴"
            sub = w.get("keyword") if plat == "ebay" else w.get("url", "")[:50]

            hcol1, hcol2 = st.columns([5, 1])
            with hcol1:
                exp = st.expander(f"{status} {plat_icon} {w.get('name', 'Ohne Namen')}  ·  »{sub}«", expanded=False)
            with hcol2:
                pause_label = "▶️ An" if not is_enabled else "⏸️ Aus"
                if st.button(pause_label, key=f"snipause_{i}", use_container_width=True):
                    watches[i] = {**w, "enabled": not is_enabled}
                    if save_sniper_watches(watches):
                        st.rerun()

            with exp:
                col1, col2 = st.columns(2)
                with col1:
                    s_name = st.text_input("Name", value=w.get("name", ""), key=f"sn_name_{i}")
                    s_plat = st.selectbox(
                        "Plattform",
                        ["ebay", "egun"],
                        index=0 if plat == "ebay" else 1,
                        key=f"sn_plat_{i}",
                    )
                    if s_plat == "ebay":
                        s_kw  = st.text_input("Suchbegriff", value=w.get("keyword", ""), key=f"sn_kw_{i}",
                                              help="z.B.  playstation 5  oder  iphone 15")
                        s_url = ""
                    else:
                        s_url = st.text_input("eGun Kategorie-URL", value=w.get("url", ""), key=f"sn_url_{i}",
                                              help="z.B. https://egun.de/market/list_items.php?cat=492")
                        s_kw  = ""
                with col2:
                    s_max  = st.number_input("Maximalpreis (€)  (0 = egal)", value=float(w.get("max_price", 0)), min_value=0.0, step=5.0, key=f"sn_max_{i}")
                    s_active = st.checkbox("Aktiv", value=w.get("enabled", True), key=f"sn_active_{i}")

                bcol1, bcol2, _ = st.columns([1, 1, 3])
                with bcol1:
                    if st.button("💾 Speichern", key=f"sn_save_{i}", use_container_width=True):
                        watches[i] = {
                            **w,
                            "name": s_name,
                            "platform": s_plat,
                            "keyword": s_kw,
                            "url": s_url,
                            "max_price": s_max,
                            "enabled": s_active,
                        }
                        if save_sniper_watches(watches):
                            st.success("✅ Gespeichert!")
                with bcol2:
                    if st.button("🗑 Löschen", key=f"sn_del_{i}", use_container_width=True):
                        watches.pop(i)
                        if save_sniper_watches(watches):
                            st.rerun()

        st.markdown("---")
        st.subheader("➕ Neue Sniper-Suche")

        with st.form("new_sniper", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                sn_name = st.text_input("Name *", placeholder="z.B. PS5 Schnäppchen")
                sn_plat = st.selectbox("Plattform *", ["ebay", "egun"])
                if sn_plat == "ebay":
                    sn_kw  = st.text_input("eBay-Suchbegriff *", placeholder="playstation 5")
                    sn_url = ""
                else:
                    sn_url = st.text_input("eGun Kategorie-URL *",
                                           placeholder="https://egun.de/market/list_items.php?cat=492")
                    sn_kw  = ""
            with col2:
                sn_max  = st.number_input("Maximalpreis (€)  (0 = egal)", min_value=0.0, step=5.0)
                sn_active = st.checkbox("Sofort aktivieren", value=True)

            if st.form_submit_button("➕ Hinzufügen", use_container_width=True, type="primary"):
                if not sn_name or (sn_plat == "ebay" and not sn_kw) or (sn_plat == "egun" and not sn_url):
                    st.error("Name + Suchbegriff/URL sind Pflichtfelder.")
                else:
                    watches.append({
                        "id": str(uuid.uuid4())[:8],
                        "name": sn_name,
                        "platform": sn_plat,
                        "keyword": sn_kw,
                        "url": sn_url,
                        "max_price": sn_max,
                        "enabled": sn_active,
                    })
                    if save_sniper_watches(watches):
                        st.success(f"✅ »{sn_name}« angelegt!")
                        st.rerun()

        st.markdown("---")
        st.info(
            "**So funktioniert's:**\n"
            "- Alle 10 Min durchsuchen wir die gewählte Plattform\n"
            "- Endet eine Auktion in **5–15 Minuten** UND hat **0 Gebote** → 📧 sofort E-Mail\n"
            "- Bei eBay: Suchbegriff (z.B. „playstation 5")\n"
            "- Bei eGun: Kategorie-URL (z.B. Softair, Pistolen, …)\n"
            "- Maximalpreis filtert zu teure Auktionen\n"
            "- Jede Auktion wird nur **einmal** gemeldet"
        )

    # ── Tab: E-Mail ────────────────────────────────────────────────────────────
    with tab_email:
        st.subheader("📧 E-Mail Einstellungen")
        st.info("Die E-Mail-Einstellungen sind als GitHub Secrets gespeichert und können nur über GitHub geändert werden.")

        st.markdown("""
        **Aktuelle Einstellungen** (aus GitHub Secrets):
        - **Absender:** preisalarmahlers@gmail.com
        - **Empfänger:** Steffen.Ahlers90@gmail.com

        **Zum Ändern:**
        1. Öffne: https://github.com/steffenah/preis-alarm/settings/secrets/actions
        2. Klicke auf das Secret → **Update**
        """)

        st.markdown("---")
        st.subheader("✉ Test-E-Mail senden")
        if st.button("Test-E-Mail jetzt senden", type="primary"):
            try:
                import smtplib
                from email.mime.text import MIMEText
                # Secrets direkt aus GitHub Actions – hier nicht verfügbar,
                # darum Info-Meldung
                st.info("Test-E-Mails können direkt über GitHub Actions ausgelöst werden:\n"
                        "https://github.com/steffenah/preis-alarm/actions")
            except Exception as e:
                st.error(str(e))

    # ── Tab: App installieren ──────────────────────────────────────────────────
    with tab_install:
        st.subheader("📱 Preis-Alarm als App installieren")
        st.markdown(
            "Du kannst diese Webseite als **App auf dein Handy oder den PC packen** – "
            "dann öffnet sie sich wie eine echte App im Vollbild, mit eigenem Icon."
        )

        st.markdown("---")
        st.markdown("### 📱 Android (Chrome / Edge)")
        st.markdown("""
        1. Öffne **https://preis-alarm-dmoxajghdbetoa4mvtqrdk.streamlit.app/** in Chrome
        2. Tippe oben rechts auf das **⋮ Menü**
        3. Wähle **„App installieren"** oder **„Zum Startbildschirm hinzufügen"**
        4. Bestätige → ein 🛒 Icon erscheint auf deinem Startbildschirm
        """)

        st.markdown("### 🍎 iPhone (Safari)")
        st.markdown("""
        1. Öffne die Seite in **Safari** (nicht Chrome!)
        2. Tippe unten auf das **Teilen-Symbol** (Quadrat mit Pfeil nach oben)
        3. Wische nach unten und wähle **„Zum Home-Bildschirm hinzufügen"**
        4. Tippe rechts oben auf **„Hinzufügen"**
        """)

        st.markdown("### 💻 Windows / Mac (Chrome / Edge)")
        st.markdown("""
        1. Öffne die Seite in Chrome oder Edge
        2. In der Adressleiste rechts: **„App installieren"-Icon** (kleines Monitor-Symbol)
        3. Klick → die App wird wie ein normales Programm installiert
        4. Du findest sie im Startmenü unter „Preis-Alarm"
        """)

        st.markdown("---")
        st.success(
            "**Vorteil:** Die App startet ohne Browser-Leiste, hat ein eigenes Icon und "
            "kann (bei iOS später auch) Benachrichtigungen empfangen."
        )

    # ── Tab: Hilfe ─────────────────────────────────────────────────────────────
    with tab_info:
        st.subheader("💡 URL-Tipps für verschiedene Seiten")

        st.markdown("""
        ### Kleinanzeigen
        Suchbegriff direkt in der URL – am einfachsten: auf Kleinanzeigen suchen, URL kopieren.
        ```
        https://www.kleinanzeigen.de/s-oldenburg/airsoft/k0
        https://www.kleinanzeigen.de/s-oldenburg/monitor-32-zoll/k0
        https://www.kleinanzeigen.de/s-frankfurt/iphone-15/k0
        ```

        ### eGun
        Kategorie-Nummer in der URL:
        ```
        https://egun.de/market/list_items.php?cat=492   (Softair)
        https://egun.de/market/list_items.php?cat=14    (Pistolen)
        ```

        ### Airsoft-Verzeichnis Forum
        ```
        https://www.airsoft-verzeichnis.de/index.php?status=forum&sp=28
        ```

        ### Weitere Seiten
        Jede beliebige Seite kann überwacht werden – der Monitor erkennt neue Links und prüft ob deine Suchbegriffe darin vorkommen.

        ---
        ### So funktioniert der Monitor
        - Alle **10 Minuten** prüft GitHub Actions alle aktiven Monitore
        - Nur **neue** Einträge lösen eine E-Mail aus (bereits gesehene werden ignoriert)
        - Bei eGun: nur **Sofortkauf**-Angebote über deiner Preisgrenze (wenn aktiviert)
        - Die E-Mail zeigt **Bieterpreis** und **Sofortkaufpreis** getrennt an

        ### Live-Logs ansehen
        👉 https://github.com/steffenah/preis-alarm/actions
        """)


# ── Einstieg ───────────────────────────────────────────────────────────────────

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    show_login()
else:
    show_app()
