/* ========================================================================
 *  Preis-Alarm  ·  Static Single-Page-App
 *  Liest und schreibt monitors.json + sniper_watches.json via GitHub API.
 * ====================================================================== */

const REPO = "steffenah/preis-alarm";
const API_BASE = `https://api.github.com/repos/${REPO}/contents`;
const LOGIN_PASSWORD = "ThinkPad1!";

// ── State ───────────────────────────────────────────────────────────────
let token = localStorage.getItem("ghToken") || "";
let monitors = [];
let sniperWatches = [];
let monitorsSha = "";
let sniperSha = "";

// ── Helpers ─────────────────────────────────────────────────────────────
function $(sel) { return document.querySelector(sel); }
function $$(sel) { return Array.from(document.querySelectorAll(sel)); }
function uuid() { return Math.random().toString(36).slice(2, 10); }
function esc(s) { return String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }

// ── Tippfehler-Generator: erzeugt typische Schreibfehler-Varianten ──────────
function typoVariants(input) {
  const out = new Set();
  const w = input.trim().toLowerCase();
  if (w.length < 4) return [];

  // 1) Buchstaben weglassen
  for (let i = 1; i < w.length - 1; i++) {
    out.add(w.slice(0, i) + w.slice(i + 1));
  }
  // 2) Benachbarte Buchstaben tauschen
  for (let i = 0; i < w.length - 1; i++) {
    out.add(w.slice(0, i) + w[i + 1] + w[i] + w.slice(i + 2));
  }
  // 3) Häufige Substitutionen (deutsch + Tastatur-Nachbarn)
  const subs = [["y","z"],["z","y"],["ie","i"],["i","ie"],["k","c"],["c","k"],["f","ph"],["ph","f"]];
  subs.forEach(([a, b]) => {
    if (w.includes(a)) out.add(w.replaceAll(a, b));
  });

  // Original + sehr lange/sehr kurze raus
  out.delete(w);
  return [...out].filter(v => v.length >= 3 && v.length <= w.length + 2).slice(0, 6);
}
function detectSite(url) {
  if (/egun\.de/.test(url))         return "egun";
  if (/kleinanzeigen\.de/.test(url)) return "kleinanzeigen";
  if (/ebay\./.test(url))            return "ebay";
  return "generic";
}

function toast(msg, type = "success") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = `toast ${type} show`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.className = "toast", 2500);
}

// ── GitHub API ──────────────────────────────────────────────────────────
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
    headers: {
      Authorization: `token ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(`Speichern fehlgeschlagen (${res.status}): ${err.message || res.statusText}`);
  }
  return res.json();
}

function decodeContent(b64) {
  return decodeURIComponent(escape(atob(b64.replace(/\s/g, ""))));
}

// ── Token-Verwaltung ────────────────────────────────────────────────────
async function ensureToken() {
  if (token) return true;
  const t = prompt(
    "GitHub Personal Access Token eingeben:\n\n" +
    "1) https://github.com/settings/tokens?type=beta\n" +
    "2) Fine-grained Token mit 'Contents: read & write' für steffenah/preis-alarm\n" +
    "3) Token hier einfügen"
  );
  if (!t) return false;
  token = t.trim();
  localStorage.setItem("ghToken", token);
  return true;
}

// ── Daten laden ─────────────────────────────────────────────────────────
async function loadMonitors() {
  $("#monitors-loading").style.display = "block";
  try {
    const f = await ghGet("monitors.json");
    monitorsSha = f.sha;
    monitors = JSON.parse(decodeContent(f.content)).monitors || [];
    renderMonitors();
  } catch (e) {
    toast(e.message, "error");
  }
  $("#monitors-loading").style.display = "none";
}

async function loadSniper() {
  $("#sniper-loading").style.display = "block";
  try {
    const f = await ghGet("sniper_watches.json");
    sniperSha = f.sha;
    sniperWatches = JSON.parse(decodeContent(f.content)).watches || [];
    renderSniper();
  } catch (e) {
    // Wenn die Datei nicht existiert: leeres Array
    if (/404/.test(e.message)) {
      sniperWatches = [];
      sniperSha = "";
      renderSniper();
    } else {
      toast(e.message, "error");
    }
  }
  $("#sniper-loading").style.display = "none";
}

// ── Speichern ───────────────────────────────────────────────────────────
async function saveMonitors() {
  if (!await ensureToken()) return false;
  try {
    const body = JSON.stringify({ monitors }, null, 2);
    const res = await ghPut("monitors.json", body, monitorsSha,
                            "chore: monitors via Web-UI aktualisiert [skip ci]");
    monitorsSha = res.content.sha;
    return true;
  } catch (e) {
    toast(e.message, "error");
    return false;
  }
}

async function saveSniper() {
  if (!await ensureToken()) return false;
  try {
    const body = JSON.stringify({ watches: sniperWatches }, null, 2);
    const res = await ghPut("sniper_watches.json", body, sniperSha,
                            "chore: sniper watches via Web-UI aktualisiert [skip ci]");
    sniperSha = res.content.sha;
    return true;
  } catch (e) {
    toast(e.message, "error");
    return false;
  }
}

// ── Monitors UI ─────────────────────────────────────────────────────────
function renderMonitors() {
  const html = monitors.map((m, i) => {
    const enabled = m.enabled !== false;
    const status = enabled ? "🟢" : "⏸️";
    const pauseLabel = enabled ? "⏸️ Aus" : "▶️ An";
    return `
    <div class="card" data-i="${i}">
      <div class="card-header">
        <span class="status">${status}</span>
        <div class="name">
          ${esc(m.name || "Ohne Namen")}
          <div class="sub">${esc(m.site_type || "generic")} · ${esc((m.keywords || []).join(", ") || "alle Treffer")}</div>
        </div>
        <button class="pause-btn" data-action="pause" data-i="${i}">${pauseLabel}</button>
        <span class="chevron">▶</span>
      </div>
      <div class="card-body">
        <div class="form-grid">
          <label class="full">Name <input data-field="name" value="${esc(m.name || "")}"></label>
          <label class="full">URL <input data-field="url" value="${esc(m.url || "")}"></label>
          <label class="full">Suchbegriffe (kommagetrennt, leer = alles)
            <input data-field="keywords" value="${esc((m.keywords || []).join(", "))}">
          </label>
          <label class="full">🚫 Ausschluss-Wörter (kommagetrennt, optional)
            <input data-field="exclude_keywords" value="${esc((m.exclude_keywords || []).join(", "))}" placeholder="z.B. defekt, bastler, ersatzteil">
          </label>
          <label>Mindestpreis € (0 = kein Limit)
            <input type="number" data-field="min_price" value="${m.min_price || 0}" min="0" step="5">
          </label>
          <label>Maximalpreis € (0 = kein Limit)
            <input type="number" data-field="max_price" value="${m.max_price || 0}" min="0" step="5">
          </label>
          <label class="checkbox"><input type="checkbox" data-field="sofortkauf_only" ${m.sofortkauf_only ? "checked" : ""}> Nur Sofortkauf</label>
          <label class="checkbox"><input type="checkbox" data-field="enabled" ${enabled ? "checked" : ""}> Aktiv</label>
        </div>
        <div style="display:flex;gap:0.5rem;margin-top:0.5rem">
          <button class="btn-icon" data-action="save" data-i="${i}">💾 Speichern</button>
          <button class="btn-icon btn-danger" data-action="delete" data-i="${i}">🗑 Löschen</button>
        </div>
      </div>
    </div>`;
  }).join("");
  $("#monitors-list").innerHTML = html || `<p class="muted">Noch keine Monitore – leg unten einen an.</p>`;
}

// ── Sniper UI ───────────────────────────────────────────────────────────
function renderSniper() {
  const html = sniperWatches.map((w, i) => {
    const enabled = w.enabled !== false;
    const status = enabled ? "🟢" : "⏸️";
    const pauseLabel = enabled ? "⏸️ Aus" : "▶️ An";
    const plat = w.platform || "ebay";
    const platIcon = plat === "egun" ? "🛒" : "🅴";
    const sub = plat === "ebay" ? (w.keyword || "") : (w.url || "").slice(0, 60);
    return `
    <div class="card" data-i="${i}" data-kind="sniper">
      <div class="card-header">
        <span class="status">${status}</span>
        <div class="name">
          ${platIcon} ${esc(w.name || "Ohne Namen")}
          <div class="sub">${esc(sub)}</div>
        </div>
        <button class="pause-btn" data-action="sn-pause" data-i="${i}">${pauseLabel}</button>
        <span class="chevron">▶</span>
      </div>
      <div class="card-body">
        <div class="form-grid">
          <label class="full">Name <input data-field="name" value="${esc(w.name || "")}"></label>
          <label>Plattform
            <select data-field="platform">
              <option value="ebay" ${plat === "ebay" ? "selected" : ""}>eBay</option>
              <option value="egun" ${plat === "egun" ? "selected" : ""}>eGun</option>
            </select>
          </label>
          <label>Maximalpreis € (0 = egal)
            <input type="number" data-field="max_price" value="${w.max_price || 0}" min="0" step="5">
          </label>
          <label class="full sniper-keyword" ${plat === "egun" ? 'style="display:none"' : ""}>
            eBay-Suchbegriff <input data-field="keyword" value="${esc(w.keyword || "")}">
          </label>
          <label class="full sniper-url" ${plat === "ebay" ? 'style="display:none"' : ""}>
            eGun Kategorie-URL <input data-field="url" value="${esc(w.url || "")}">
          </label>
          <label class="full sniper-filter" ${plat === "ebay" ? 'style="display:none"' : ""}>
            Schlagwort-Filter (optional, kommagetrennt – leer = ALLE 0-Gebot-Auktionen)
            <input data-field="keywords" value="${esc((w.keywords || []).join(", "))}" placeholder="z.B. mp5, glock, ak47">
          </label>
          <label class="full">🚫 Ausschluss-Wörter (kommagetrennt, optional)
            <input data-field="exclude_keywords" value="${esc((w.exclude_keywords || []).join(", "))}" placeholder="z.B. defekt, bastler, ersatzteil">
          </label>
          <label class="checkbox"><input type="checkbox" data-field="enabled" ${enabled ? "checked" : ""}> Aktiv</label>
        </div>
        <div style="display:flex;gap:0.5rem;margin-top:0.5rem;flex-wrap:wrap">
          <button class="btn-icon" data-action="sn-save" data-i="${i}">💾 Speichern</button>
          ${plat === "ebay" ? `<button class="btn-icon" data-action="sn-typos" data-i="${i}">🎯 Tippfehler-Varianten anlegen</button>` : ""}
          <button class="btn-icon btn-danger" data-action="sn-delete" data-i="${i}">🗑 Löschen</button>
        </div>
      </div>
    </div>`;
  }).join("");
  $("#sniper-list").innerHTML = html || `<p class="muted">Noch keine Sniper-Suchen.</p>`;
}

// ── Card-Klicks (Edit, Save, Delete, Pause) ─────────────────────────────
document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-action]");
  if (btn) {
    e.stopPropagation();
    const i = +btn.dataset.i;
    const a = btn.dataset.action;

    // ── Monitor-Actions ─────
    if (a === "pause") {
      monitors[i].enabled = !(monitors[i].enabled !== false);
      if (await saveMonitors()) { toast("Aktualisiert"); renderMonitors(); }
    }
    if (a === "save") {
      const card = btn.closest(".card");
      const fields = {};
      card.querySelectorAll("[data-field]").forEach(el => {
        const k = el.dataset.field;
        if (el.type === "checkbox") fields[k] = el.checked;
        else if (el.type === "number") fields[k] = parseFloat(el.value) || 0;
        else fields[k] = el.value;
      });
      fields.keywords = (fields.keywords || "").split(",").map(s => s.trim()).filter(Boolean);
      fields.exclude_keywords = (fields.exclude_keywords || "").split(",").map(s => s.trim()).filter(Boolean);
      fields.site_type = detectSite(fields.url || "");
      monitors[i] = { ...monitors[i], ...fields };
      if (await saveMonitors()) { toast("Gespeichert"); renderMonitors(); }
    }
    if (a === "delete") {
      if (!confirm(`»${monitors[i].name}« wirklich löschen?`)) return;
      monitors.splice(i, 1);
      if (await saveMonitors()) { toast("Gelöscht"); renderMonitors(); }
    }

    // ── Sniper-Actions ─────
    if (a === "sn-pause") {
      sniperWatches[i].enabled = !(sniperWatches[i].enabled !== false);
      if (await saveSniper()) { toast("Aktualisiert"); renderSniper(); }
    }
    if (a === "sn-save") {
      const card = btn.closest(".card");
      const fields = {};
      card.querySelectorAll("[data-field]").forEach(el => {
        const k = el.dataset.field;
        if (el.type === "checkbox") fields[k] = el.checked;
        else if (el.type === "number") fields[k] = parseFloat(el.value) || 0;
        else fields[k] = el.value;
      });
      // keywords als Array (kommagetrennt)
      if (typeof fields.keywords === "string") {
        fields.keywords = fields.keywords.split(",").map(s => s.trim()).filter(Boolean);
      }
      if (typeof fields.exclude_keywords === "string") {
        fields.exclude_keywords = fields.exclude_keywords.split(",").map(s => s.trim()).filter(Boolean);
      }
      sniperWatches[i] = { ...sniperWatches[i], ...fields };
      if (await saveSniper()) { toast("Gespeichert"); renderSniper(); }
    }
    if (a === "sn-delete") {
      if (!confirm(`»${sniperWatches[i].name}« wirklich löschen?`)) return;
      sniperWatches.splice(i, 1);
      if (await saveSniper()) { toast("Gelöscht"); renderSniper(); }
    }
    if (a === "sn-typos") {
      const orig = sniperWatches[i];
      const variants = typoVariants(orig.keyword || "");
      if (!variants.length) { toast("Keine Varianten möglich", "error"); return; }
      if (!confirm(`Folgende ${variants.length} Tippfehler-Suchen anlegen?\n\n${variants.join(", ")}\n\nDas erzeugt ${variants.length} neue Sniper-Watches.`)) return;
      variants.forEach(v => {
        sniperWatches.push({
          ...orig,
          id: uuid(),
          name: `${orig.name} 🎯 ${v}`,
          keyword: v,
        });
      });
      if (await saveSniper()) { toast(`${variants.length} Varianten angelegt`); renderSniper(); }
    }
    return;
  }

  // Karten-Header (öffnen/schließen)
  const header = e.target.closest(".card-header");
  if (header) header.parentElement.classList.toggle("open");
});

// ── Sniper: Plattform-Toggle innerhalb Card ─────────────────────────────
document.addEventListener("change", (e) => {
  const sel = e.target;
  if (sel.dataset?.field === "platform") {
    const card = sel.closest(".card");
    card.querySelector(".sniper-keyword").style.display = sel.value === "ebay" ? "" : "none";
    card.querySelector(".sniper-url").style.display     = sel.value === "egun" ? "" : "none";
    card.querySelector(".sniper-filter").style.display  = sel.value === "egun" ? "" : "none";
  }
});

// ── Neues Item: Monitor ─────────────────────────────────────────────────
$("#btn-add-monitor").addEventListener("click", async () => {
  const name = $("#new-mon-name").value.trim();
  const url  = $("#new-mon-url").value.trim();
  if (!name || !url) { toast("Name & URL nötig", "error"); return; }
  const kws  = $("#new-mon-kw").value.split(",").map(s => s.trim()).filter(Boolean);
  const excl = $("#new-mon-excl").value.split(",").map(s => s.trim()).filter(Boolean);
  monitors.push({
    id: uuid(),
    name,
    url,
    site_type: detectSite(url),
    keywords: kws,
    exclude_keywords: excl,
    min_price: parseFloat($("#new-mon-min").value) || 0,
    max_price: parseFloat($("#new-mon-max").value) || 0,
    sofortkauf_only: $("#new-mon-sofort").checked,
    enabled: $("#new-mon-active").checked,
  });
  if (await saveMonitors()) {
    toast(`»${name}« angelegt`);
    renderMonitors();
    ["new-mon-name", "new-mon-url", "new-mon-kw", "new-mon-excl"].forEach(id => $(`#${id}`).value = "");
  }
});

// ── Neues Item: Sniper ──────────────────────────────────────────────────
$("#new-snip-platform").addEventListener("change", (e) => {
  const ebay = e.target.value === "ebay";
  $("#new-snip-keyword-label").classList.toggle("hidden", !ebay);
  $("#new-snip-url-label").classList.toggle("hidden",  ebay);
  $("#new-snip-filter-label").classList.toggle("hidden", ebay);
});

$("#btn-add-sniper").addEventListener("click", async () => {
  const name = $("#new-snip-name").value.trim();
  const platform = $("#new-snip-platform").value;
  const keyword = $("#new-snip-keyword").value.trim();
  const url     = $("#new-snip-url").value.trim();
  const filter  = $("#new-snip-filter").value.trim();
  if (!name) { toast("Name fehlt", "error"); return; }
  if (platform === "ebay" && !keyword) { toast("Suchbegriff fehlt", "error"); return; }
  if (platform === "egun" && !url)     { toast("URL fehlt", "error"); return; }
  const excl = $("#new-snip-excl").value.split(",").map(s => s.trim()).filter(Boolean);
  sniperWatches.push({
    id: uuid(),
    name,
    platform,
    keyword,
    url,
    keywords: filter.split(",").map(s => s.trim()).filter(Boolean),
    exclude_keywords: excl,
    max_price: parseFloat($("#new-snip-max").value) || 0,
    enabled: $("#new-snip-active").checked,
  });
  if (await saveSniper()) {
    toast(`»${name}« angelegt`);
    renderSniper();
    ["new-snip-name", "new-snip-keyword", "new-snip-url", "new-snip-filter", "new-snip-excl"].forEach(id => $(`#${id}`).value = "");
  }
});

// ── Tab-Navigation ──────────────────────────────────────────────────────
$$(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach(t => t.classList.toggle("active", t === tab));
    const name = tab.dataset.tab;
    $$(".tab-content").forEach(c => c.classList.toggle("active", c.id === `tab-${name}`));
  });
});

// ── Login ───────────────────────────────────────────────────────────────
function showApp() {
  $("#login-screen").classList.add("hidden");
  $("#app").classList.remove("hidden");
  loadMonitors();
  loadSniper();
}

function showLogin() {
  $("#login-screen").classList.remove("hidden");
  $("#app").classList.add("hidden");
}

$("#btn-login").addEventListener("click", () => {
  const pw = $("#login-password").value;
  if (pw === LOGIN_PASSWORD) {
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
$("#btn-reset-token").addEventListener("click", () => {
  localStorage.removeItem("ghToken");
  token = "";
  toast("Token gelöscht. Beim nächsten Speichern fragt die App neu.");
});

// ── PWA-Installation ────────────────────────────────────────────────────
let deferredPrompt;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredPrompt = e;
  $("#btn-install").style.display = "block";
});
$("#btn-install")?.addEventListener("click", async () => {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  await deferredPrompt.userChoice;
  deferredPrompt = null;
  $("#btn-install").style.display = "none";
});

// ── Service Worker registrieren ─────────────────────────────────────────
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

// ── Bootstrapping ───────────────────────────────────────────────────────
if (sessionStorage.getItem("auth") === "1") {
  showApp();
} else {
  showLogin();
}
