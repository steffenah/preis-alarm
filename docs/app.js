/* ========================================================================
 *  Preis-Alarm  ·  Web-Oberfläche
 *
 *  Zeigt zwei Arten von Suchen in EINER Liste:
 *    · monitor → monitors.json        (meldet neue Inserate)
 *    · sniper  → sniper_watches.json  (meldet bald endende Auktionen)
 *  Gespeichert wird direkt via GitHub-API.
 * ====================================================================== */

const REPO = "steffenah/preis-alarm";
const API_BASE = `https://api.github.com/repos/${REPO}/contents`;
const LOGIN_PASSWORD = "ThinkPad1!";

// ── State ───────────────────────────────────────────────────────────────
let token = localStorage.getItem("ghToken") || "";
let monitors = [];
let watches  = [];
let monitorsSha = "";
let watchesSha  = "";
let newKind = "monitor";     // im Anlege-Formular gewählte Art

// ── Mini-Helfer ─────────────────────────────────────────────────────────
const $  = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const uuid = () => Math.random().toString(36).slice(2, 10);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const splitList = (s) => String(s || "").split(",").map((x) => x.trim()).filter(Boolean);

function sourceLabel(url) {
  if (/egun\.de/.test(url))          return "eGun";
  if (/kleinanzeigen\.de/.test(url)) return "Kleinanzeigen";
  if (/ebay\./.test(url))            return "eBay";
  return "Webseite";
}
function detectSite(url) {
  if (/egun\.de/.test(url))          return "egun";
  if (/kleinanzeigen\.de/.test(url)) return "kleinanzeigen";
  if (/ebay\./.test(url))            return "ebay";
  return "generic";
}

function toast(msg, type = "success") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = `toast ${type} show`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = "toast"), 3000);
}

// ── Tippfehler-Generator ────────────────────────────────────────────────
function typoVariants(input) {
  const out = new Set();
  const w = String(input || "").trim().toLowerCase();
  if (w.length < 4) return [];

  for (let i = 1; i < w.length - 1; i++)          // Buchstabe fehlt
    out.add(w.slice(0, i) + w.slice(i + 1));
  for (let i = 0; i < w.length - 1; i++)          // Buchstaben vertauscht
    out.add(w.slice(0, i) + w[i + 1] + w[i] + w.slice(i + 2));
  [["y","z"],["z","y"],["ie","i"],["i","ie"],["k","c"],["c","k"],["f","ph"],["ph","f"]]
    .forEach(([a, b]) => { if (w.includes(a)) out.add(w.replaceAll(a, b)); });

  out.delete(w);
  return [...out].filter((v) => v.length >= 3 && v.length <= w.length + 2).slice(0, 6);
}

/* ═══════════════════════════════════════════════════════════════════════
 *  GitHub-Anbindung
 * ═══════════════════════════════════════════════════════════════════════ */

function ensureToken() {
  if (token) return Promise.resolve(true);
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal">
        <h2>🔑 Einmalig: GitHub-Token</h2>
        <p>Damit die App deine Suchen speichern kann, braucht sie einen Zugriffs-Schlüssel.
        Er bleibt nur in diesem Browser gespeichert.</p>

        <h3>In 4 Schritten:</h3>
        <ol>
          <li>Öffne <a href="https://github.com/settings/personal-access-tokens/new" target="_blank">diese GitHub-Seite</a></li>
          <li><b>Repository access</b> → „Only select repositories“ → <code>steffenah/preis-alarm</code></li>
          <li><b>Permissions</b> → „Add permissions“ → <b>Contents</b> und <b>Actions</b> jeweils auf <i>Read and write</i></li>
          <li>Unten <b>Generate token</b>, den Schlüssel kopieren und hier einfügen</li>
        </ol>

        <input type="password" id="token-input" placeholder="github_pat_…" autocomplete="off" autofocus>
        <p class="error" id="token-error"></p>

        <div class="btn-row">
          <button class="btn-primary" id="token-save">Speichern</button>
          <button class="btn-ghost" id="token-cancel">Abbrechen</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    const input = overlay.querySelector("#token-input");
    const err   = overlay.querySelector("#token-error");
    const close = (ok) => { overlay.remove(); resolve(ok); };

    overlay.querySelector("#token-save").onclick = () => {
      const t = input.value.trim();
      if (!t.startsWith("github_pat_")) {
        err.textContent = "Das sieht nicht nach einem gültigen Schlüssel aus – er beginnt mit github_pat_";
        return;
      }
      token = t;
      localStorage.setItem("ghToken", token);
      close(true);
    };
    overlay.querySelector("#token-cancel").onclick = () => close(false);
    input.addEventListener("keyup", (e) => {
      if (e.key === "Enter") overlay.querySelector("#token-save").click();
    });
  });
}

async function ghGet(path) {
  const res = await fetch(`${API_BASE}/${path}?ref=main`, {
    headers: token ? { Authorization: `token ${token}` } : {},
  });
  if (!res.ok) throw new Error(`GitHub ${res.status}: ${res.statusText}`);
  return res.json();
}

async function ghPut(path, content, sha, msg) {
  const body = {
    message: msg,
    content: btoa(unescape(encodeURIComponent(content))),
    branch: "main",
  };
  if (sha) body.sha = sha;
  const res = await fetch(`${API_BASE}/${path}`, {
    method: "PUT",
    headers: { Authorization: `token ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.message || res.statusText);
  }
  return res.json();
}

const decodeContent = (b64) => decodeURIComponent(escape(atob(b64.replace(/\s/g, ""))));

async function triggerWorkflow() {
  if (!(await ensureToken())) return false;
  const res = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/monitor.yml/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `token ${token}`,
        "Content-Type": "application/json",
        Accept: "application/vnd.github+json",
      },
      body: JSON.stringify({ ref: "main" }),
    });
  if (res.ok) return true;
  const err = await res.json().catch(() => ({}));
  const msg = err.message || res.statusText;
  if (/not accessible|permission|access/i.test(msg))
    throw new Error("Dem Token fehlt die Berechtigung „Actions“. Siehe Hilfe-Tab.");
  throw new Error(msg);
}

/* ═══════════════════════════════════════════════════════════════════════
 *  Laden & Speichern
 * ═══════════════════════════════════════════════════════════════════════ */

async function loadAll() {
  $("#searches-loading").style.display = "block";
  try {
    const [mf, wf] = await Promise.all([
      ghGet("monitors.json"),
      ghGet("sniper_watches.json").catch(() => null),
    ]);
    monitorsSha = mf.sha;
    monitors = JSON.parse(decodeContent(mf.content)).monitors || [];
    if (wf) {
      watchesSha = wf.sha;
      watches = JSON.parse(decodeContent(wf.content)).watches || [];
    } else {
      watchesSha = "";
      watches = [];
    }
    render();
  } catch (e) {
    toast(`Laden fehlgeschlagen: ${e.message}`, "error");
  }
  $("#searches-loading").style.display = "none";
}

async function save(kind) {
  if (!(await ensureToken())) return false;
  try {
    if (kind === "monitor") {
      const res = await ghPut("monitors.json",
        JSON.stringify({ monitors }, null, 2), monitorsSha,
        "chore: Suchen über Web-UI aktualisiert [skip ci]");
      monitorsSha = res.content.sha;
    } else {
      const res = await ghPut("sniper_watches.json",
        JSON.stringify({ watches }, null, 2), watchesSha,
        "chore: Auktions-Suchen über Web-UI aktualisiert [skip ci]");
      watchesSha = res.content.sha;
    }
    return true;
  } catch (e) {
    toast(`Speichern fehlgeschlagen: ${e.message}`, "error");
    return false;
  }
}

/* ═══════════════════════════════════════════════════════════════════════
 *  Liste rendern
 * ═══════════════════════════════════════════════════════════════════════ */

/** Kurze Zusammenfassung unter dem Namen, damit man nicht aufklappen muss. */
function metaLine(kind, d) {
  const bits = [];
  if (kind === "monitor") {
    bits.push(`<span class="badge badge-new">🔔 Neue Inserate</span>`);
    bits.push(esc(sourceLabel(d.url || "")));
  } else {
    bits.push(`<span class="badge badge-auction">🔨 Auktions-Ende</span>`);
    bits.push(d.platform === "egun" ? "eGun" : "eBay");
    if (d.platform === "ebay" && d.keyword) bits.push(`„${esc(d.keyword)}“`);
  }

  const min = Number(d.min_price) || 0;
  const max = Number(d.max_price) || 0;
  if (min && max)      bits.push(`${min}–${max} €`);
  else if (min)        bits.push(`ab ${min} €`);
  else if (max)        bits.push(`bis ${max} €`);

  const kws = d.keywords || [];
  if (kws.length) bits.push(`„${esc(kws.slice(0, 2).join(", "))}“${kws.length > 2 ? " …" : ""}`);

  const typos = (d.typo_variants || []).length;
  if (typos) bits.push(`🎯 +${typos} Varianten`);

  if ((d.exclude_keywords || []).length) bits.push("🚫 Filter aktiv");

  return bits.join(" · ");
}

function cardHtml(kind, idx, d) {
  const on = d.enabled !== false;
  const isSniper = kind === "sniper";
  const plat = d.platform || "ebay";
  const showUrl = !isSniper || plat === "egun";
  const showKeyword = isSniper && plat === "ebay";

  return `
  <div class="card" data-kind="${kind}" data-idx="${idx}">
    <div class="card-header">
      <span class="status ${on ? "on" : "off"}" title="${on ? "aktiv" : "pausiert"}"></span>
      <div class="name-block">
        <div class="name">${esc(d.name || "Ohne Namen")}</div>
        <div class="meta">${metaLine(kind, d)}</div>
      </div>
      <button class="pause-btn" data-action="toggle">${on ? "⏸️ Pause" : "▶️ Start"}</button>
      <span class="chevron">▸</span>
    </div>

    <div class="card-body">
      <div class="form-grid">
        <label class="full">Name der Suche
          <input data-field="name" value="${esc(d.name || "")}">
        </label>

        ${showKeyword ? `
        <label class="full">eBay-Suchbegriff
          <input data-field="keyword" value="${esc(d.keyword || "")}">
        </label>
        <label class="full">🎯 Tippfehler-Varianten
          <input data-field="typo_variants" value="${esc((d.typo_variants || []).join(", "))}"
                 placeholder="werden zusätzlich mitgesucht">
          <span class="hint">Mit dem Knopf unten automatisch erzeugen lassen.</span>
        </label>` : ""}

        ${showUrl ? `
        <label class="full">Wo soll ich suchen?
          <input data-field="url" value="${esc(d.url || "")}">
        </label>` : ""}

        <label class="full">Nur melden, wenn der Titel eines dieser Wörter enthält
          <input data-field="keywords" value="${esc((d.keywords || []).join(", "))}"
                 placeholder="leer lassen = alle Treffer">
        </label>

        <label class="full">Nie melden, wenn der Titel eines dieser Wörter enthält
          <input data-field="exclude_keywords" value="${esc((d.exclude_keywords || []).join(", "))}"
                 placeholder="z.B. defekt, bastler">
        </label>

        <label class="full">Diese Verkäufer ignorieren
          <input data-field="exclude_sellers" value="${esc((d.exclude_sellers || []).join(", "))}"
                 placeholder="optional">
        </label>

        ${!isSniper ? `
        <label>Preis ab
          <input type="number" data-field="min_price" value="${Number(d.min_price) || ""}"
                 placeholder="egal" min="0" step="5">
        </label>` : ""}
        <label>Preis bis
          <input type="number" data-field="max_price" value="${Number(d.max_price) || ""}"
                 placeholder="egal" min="0" step="5">
        </label>

        ${!isSniper ? `
        <label class="checkbox full">
          <input type="checkbox" data-field="sofortkauf_only" ${d.sofortkauf_only ? "checked" : ""}>
          Nur Sofortkauf / Festpreis
        </label>` : ""}
      </div>

      <div class="btn-row">
        <button class="btn-primary" data-action="save">Speichern</button>
        ${showKeyword ? `<button class="btn-ghost" data-action="typos">🎯 Tippfehler-Varianten hinzufügen</button>` : ""}
        <button class="btn-ghost btn-danger-ghost" data-action="delete">Löschen</button>
      </div>
    </div>
  </div>`;
}

function render() {
  const parts = [
    ...monitors.map((d, i) => cardHtml("monitor", i, d)),
    ...watches.map((d, i)  => cardHtml("sniper",  i, d)),
  ];
  const total = monitors.length + watches.length;
  const active = monitors.filter((m) => m.enabled !== false).length
               + watches.filter((w) => w.enabled !== false).length;

  $("#searches-list").innerHTML = total
    ? `<div class="list-summary">${total} Suche${total === 1 ? "" : "n"} · ${active} aktiv</div>` + parts.join("")
    : `<div class="empty">
         <div class="empty-icon">🔍</div>
         <p><b>Noch keine Suche angelegt</b></p>
         <p class="muted">Leg unten deine erste Suche an – danach meldet sich die App
         automatisch per Telegram, sobald sie etwas findet.</p>
       </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════
 *  Aktionen auf Karten
 * ═══════════════════════════════════════════════════════════════════════ */

/** Liest alle Felder einer Karte aus und normalisiert sie. */
function readCard(card) {
  const out = {};
  card.querySelectorAll("[data-field]").forEach((el) => {
    const k = el.dataset.field;
    if (el.type === "checkbox")    out[k] = el.checked;
    else if (el.type === "number") out[k] = parseFloat(el.value) || 0;
    else                           out[k] = el.value;
  });
  ["keywords", "exclude_keywords", "exclude_sellers", "typo_variants"].forEach((k) => {
    if (typeof out[k] === "string") out[k] = splitList(out[k]);
  });
  return out;
}

const listOf = (kind) => (kind === "monitor" ? monitors : watches);

document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-action]");
  if (btn) {
    e.stopPropagation();
    const card = btn.closest(".card");
    const kind = card.dataset.kind;
    const idx  = +card.dataset.idx;
    const arr  = listOf(kind);
    const act  = btn.dataset.action;

    if (act === "toggle") {
      arr[idx].enabled = arr[idx].enabled === false;
      if (await save(kind)) { toast(arr[idx].enabled ? "Suche gestartet" : "Suche pausiert"); render(); }
      return;
    }

    if (act === "save") {
      const fields = readCard(card);
      if (kind === "monitor") fields.site_type = detectSite(fields.url || "");
      arr[idx] = { ...arr[idx], ...fields };
      if (await save(kind)) { toast("Gespeichert"); render(); }
      return;
    }

    if (act === "delete") {
      if (!confirm(`Suche „${arr[idx].name}“ wirklich löschen?`)) return;
      arr.splice(idx, 1);
      if (await save(kind)) { toast("Gelöscht"); render(); }
      return;
    }

    if (act === "typos") {
      const w = arr[idx];
      const have = w.typo_variants || [];
      const fresh = typoVariants(w.keyword).filter((v) => !have.includes(v) && v !== w.keyword);
      if (!fresh.length) { toast("Es gibt keine neuen Varianten", "error"); return; }
      if (!confirm(
        `Diese ${fresh.length} Varianten zusätzlich mitsuchen?\n\n${fresh.join("\n")}\n\n` +
        `Es bleibt bei einer Suche – sie durchsucht danach nur mehr Schreibweisen.`)) return;
      w.typo_variants = [...have, ...fresh];
      if (await save("sniper")) { toast(`${fresh.length} Varianten ergänzt`); render(); }
      return;
    }
  }

  // Karte auf-/zuklappen
  const header = e.target.closest(".card-header");
  if (header) header.parentElement.classList.toggle("open");
});

/* ═══════════════════════════════════════════════════════════════════════
 *  Neue Suche anlegen
 * ═══════════════════════════════════════════════════════════════════════ */

function syncNewForm() {
  const isSniper = newKind === "sniper";
  const plat = $("#f-platform").value;

  $$(".only-monitor").forEach((el) => el.classList.toggle("hidden", isSniper));
  $$(".only-sniper").forEach((el)  => el.classList.toggle("hidden", !isSniper));
  $$(".only-sniper-ebay").forEach((el) => el.classList.toggle("hidden", !(isSniper && plat === "ebay")));
  $$(".only-url").forEach((el) => el.classList.toggle("hidden", isSniper && plat === "ebay"));

  $("#f-url").placeholder = isSniper
    ? "https://egun.de/market/list_items.php?cat=492"
    : "https://www.kleinanzeigen.de/s-oldenburg/airsoft/k0";
}

$$(".kind-option").forEach((opt) => {
  opt.addEventListener("click", () => {
    $$(".kind-option").forEach((o) => o.classList.toggle("active", o === opt));
    newKind = opt.dataset.kind;
    syncNewForm();
  });
});
$("#f-platform").addEventListener("change", syncNewForm);

$("#btn-open-new").addEventListener("click", () => {
  $("#new-form").classList.remove("hidden");
  $("#btn-open-new").classList.add("hidden");
  syncNewForm();
  $("#f-name").focus();
});

function closeNewForm() {
  $("#new-form").classList.add("hidden");
  $("#btn-open-new").classList.remove("hidden");
  ["f-name", "f-url", "f-keyword", "f-keywords", "f-exclude", "f-sellers"]
    .forEach((id) => ($(`#${id}`).value = ""));
  $("#f-min").value = "";
  $("#f-max").value = "";
  $("#f-sofort").checked = false;
}
$("#btn-cancel-new").addEventListener("click", closeNewForm);

$("#link-url-help").addEventListener("click", (e) => {
  e.preventDefault();
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === "help"));
  $$(".tab-content").forEach((c) => c.classList.toggle("active", c.id === "tab-help"));
  window.scrollTo({ top: 0, behavior: "smooth" });
});

$("#btn-create").addEventListener("click", async () => {
  const name = $("#f-name").value.trim();
  if (!name) { toast("Bitte einen Namen vergeben", "error"); return; }

  const common = {
    id: uuid(),
    name,
    keywords:         splitList($("#f-keywords").value),
    exclude_keywords: splitList($("#f-exclude").value),
    exclude_sellers:  splitList($("#f-sellers").value),
    max_price: parseFloat($("#f-max").value) || 0,
    enabled: true,
  };

  if (newKind === "monitor") {
    const url = $("#f-url").value.trim();
    if (!url) { toast("Bitte eine Adresse angeben", "error"); return; }
    monitors.push({
      ...common,
      url,
      site_type: detectSite(url),
      min_price: parseFloat($("#f-min").value) || 0,
      sofortkauf_only: $("#f-sofort").checked,
    });
    if (await save("monitor")) { toast(`„${name}“ angelegt`); closeNewForm(); render(); }
  } else {
    const plat = $("#f-platform").value;
    const keyword = $("#f-keyword").value.trim();
    const url = $("#f-url").value.trim();
    if (plat === "ebay" && !keyword) { toast("Bitte einen Suchbegriff angeben", "error"); return; }
    if (plat === "egun" && !url)     { toast("Bitte eine Adresse angeben", "error"); return; }
    watches.push({ ...common, platform: plat, keyword, url, typo_variants: [] });
    if (await save("sniper")) { toast(`„${name}“ angelegt`); closeNewForm(); render(); }
  }
});

/* ═══════════════════════════════════════════════════════════════════════
 *  Rahmen: Tabs, Login, Jetzt-prüfen, PWA
 * ═══════════════════════════════════════════════════════════════════════ */

$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    $$(".tab-content").forEach((c) => c.classList.toggle("active", c.id === `tab-${tab.dataset.tab}`));
  });
});

function showApp()   { $("#login-screen").classList.add("hidden");    $("#app").classList.remove("hidden"); loadAll(); }
function showLogin() { $("#login-screen").classList.remove("hidden"); $("#app").classList.add("hidden"); }

$("#btn-login").addEventListener("click", () => {
  if ($("#login-password").value === LOGIN_PASSWORD) {
    sessionStorage.setItem("auth", "1");
    showApp();
  } else {
    $("#login-error").textContent = "Falsches Passwort";
  }
});
$("#login-password").addEventListener("keyup", (e) => {
  if (e.key === "Enter") $("#btn-login").click();
});
$("#btn-logout").addEventListener("click", () => {
  sessionStorage.removeItem("auth");
  showLogin();
});

$("#btn-reset-token").addEventListener("click", async () => {
  localStorage.removeItem("ghToken");
  token = "";
  if (await ensureToken()) toast("Neuer Token gespeichert");
});

$("#btn-run-now").addEventListener("click", async () => {
  const btn = $("#btn-run-now");
  btn.disabled = true;
  const reset = () => { btn.textContent = "⚡ Jetzt prüfen"; btn.disabled = false; };
  btn.textContent = "⏳ startet…";
  try {
    if (await triggerWorkflow()) {
      toast("Prüfung gestartet – Ergebnis kommt in ~1 Minute per Telegram");
      btn.textContent = "✅ läuft";
      setTimeout(reset, 60000);
    } else reset();
  } catch (e) {
    toast(e.message, "error");
    reset();
  }
});

let deferredPrompt;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredPrompt = e;
  $("#btn-install").style.display = "block";
});
$("#btn-install").addEventListener("click", async () => {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  await deferredPrompt.userChoice;
  deferredPrompt = null;
  $("#btn-install").style.display = "none";
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});

// ── Start ───────────────────────────────────────────────────────────────
sessionStorage.getItem("auth") === "1" ? showApp() : showLogin();
