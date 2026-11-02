"use strict";

const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const opts = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "admin-ui" },
        body: JSON.stringify(body) };
  const r = await fetch("/admin/api" + path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err = new Error(data.detail || `Erreur ${r.status}`);
    err.status = r.status;
    throw err;
  }
  return data;
}

function showError(id, err) {
  const el = $(id);
  el.textContent = err ? err.message : "";
  el.hidden = !err;
}

async function busy(button, fn) {
  button.disabled = true;
  try { await fn(); } finally { button.disabled = false; }
}

const fmtDate = (ts) => ts
  ? new Date(ts * 1000).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })
  : "—";

// ---------- session de l'admin ----------

async function init() {
  const health = await fetch("/health").then((r) => r.json()).catch(() => null);
  if (health) $("footer").textContent = `Version ${health.version}`;

  const s = await api("/session");
  $("disabled-msg").hidden = s.admin_enabled;
  $("login-card").hidden = !s.admin_enabled || s.authenticated;
  $("admin-content").hidden = !s.authenticated;
  $("logout-btn").hidden = !s.authenticated;
  if (s.authenticated) {
    refreshGarmin();
    refreshSync(true);
  }
}

$("login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  busy(e.submitter, async () => {
    try {
      await api("/login", { username: $("login-user").value, password: $("login-password").value });
      $("login-password").value = "";
      showError("login-error", null);
      await init();
    } catch (err) {
      showError("login-error", err);
    }
  });
});

$("logout-btn").addEventListener("click", async () => {
  await api("/logout", {});
  await init();
});

// ---------- compte Garmin ----------

const STATES = {
  connected: ["Connecté", "ok"],
  mfa_pending: ["Code MFA attendu", "warn"],
  needs_login: ["Reconnexion nécessaire", "warn"],
  disconnected: ["Non connecté", "off"],
};

let mfaTimer = null;

function renderGarmin(st) {
  const [label, cls] = STATES[st.state] || [st.state, "off"];
  const pill = $("garmin-pill");
  pill.textContent = label;
  pill.className = "pill " + cls;

  const facts = [];
  if (st.account_name || st.email) facts.push(["Compte", st.account_name || st.email]);
  if (st.state !== "disconnected") {
    facts.push(["Mot de passe", st.password_remembered
      ? (st.password_source === "env" ? "mémorisé (variables d'environnement)" : "mémorisé sur le serveur")
      : "non mémorisé"]);
    facts.push(["Connecté le", fmtDate(st.connected_at)]);
  }
  const dl = $("garmin-facts");
  dl.replaceChildren(...facts.flatMap(([k, v]) => {
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = v;
    return [dt, dd];
  }));
  dl.hidden = facts.length === 0;

  showError("garmin-last-error", st.last_error ? new Error(`Dernière erreur (${fmtDate(st.last_error_at)}) : ${st.last_error}`) : null);

  const actions = $("garmin-actions");
  actions.replaceChildren();
  if (st.state === "connected" || st.state === "needs_login") {
    if (st.password_remembered && st.password_source === "admin") {
      actions.append(actionButton("Oublier le mot de passe", "/garmin/forget-password"));
    }
    actions.append(actionButton("Déconnecter le compte", "/garmin/logout", "danger"));
  }

  const needsForm = st.state === "disconnected" || st.state === "needs_login";
  $("garmin-login-card").hidden = !needsForm;
  $("garmin-login-title").textContent = st.state === "needs_login" ? "Reconnecter le compte" : "Connecter le compte";
  if (needsForm && st.email && !$("garmin-email").value) $("garmin-email").value = st.email;

  $("garmin-mfa-card").hidden = st.state !== "mfa_pending";
  clearInterval(mfaTimer);
  if (st.state === "mfa_pending" && st.mfa_expires_at) {
    const tick = () => {
      const left = Math.max(0, Math.round(st.mfa_expires_at - Date.now() / 1000));
      $("garmin-mfa-timer").textContent = left
        ? `Code à saisir dans ${Math.floor(left / 60)} min ${String(left % 60).padStart(2, "0")} s.`
        : "Délai dépassé : recommence la connexion.";
      if (!left) { clearInterval(mfaTimer); refreshGarmin(); }
    };
    tick();
    mfaTimer = setInterval(tick, 1000);
    $("garmin-mfa-code").focus();
  }
}

function actionButton(label, path, cls = "") {
  const b = document.createElement("button");
  b.className = "btn " + cls;
  b.textContent = label;
  b.addEventListener("click", () => busy(b, async () => renderGarmin(await api(path, {}))));
  return b;
}

async function refreshGarmin() {
  try {
    renderGarmin(await api("/garmin"));
  } catch (err) {
    if (err.status === 401) init();
  }
}

$("garmin-login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  busy($("garmin-login-btn"), async () => {
    try {
      const remember = document.querySelector('input[name="remember"]:checked').value === "yes";
      const st = await api("/garmin/login", {
        email: $("garmin-email").value, password: $("garmin-password").value, remember,
      });
      $("garmin-password").value = "";
      showError("garmin-login-error", null);
      renderGarmin(st);
    } catch (err) {
      showError("garmin-login-error", err);
    }
  });
});

$("garmin-mfa-form").addEventListener("submit", (e) => {
  e.preventDefault();
  busy(e.submitter, async () => {
    try {
      const st = await api("/garmin/mfa", { code: $("garmin-mfa-code").value });
      $("garmin-mfa-code").value = "";
      showError("garmin-mfa-error", null);
      renderGarmin(st);
    } catch (err) {
      showError("garmin-mfa-error", err);
    }
  });
});

$("garmin-mfa-cancel").addEventListener("click", async () => {
  renderGarmin(await api("/garmin/mfa/cancel", {}));
});

// ---------- synchro ----------

const RUN_KINDS = { "garmin": "manuelle", "garmin-auto": "quotidienne" };
const fmtIso = (iso) => iso
  ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })
  : "—";
let syncTimer = null;

for (let h = 0; h < 24; h++) $("ss-hour").add(new Option(`${h} h`, h));

function stat(value, label) {
  const div = document.createElement("div");
  div.className = "stat";
  const b = document.createElement("b"); b.textContent = value;
  const span = document.createElement("span"); span.textContent = label;
  div.append(b, span);
  return div;
}

function renderSync(st, fillSettings) {
  const pill = $("sync-pill");
  pill.textContent = st.running ? "En cours" : (st.first_import_done ? "À jour" : "Premier import à faire");
  pill.className = "pill " + (st.running ? "warn" : st.first_import_done ? "ok" : "off");

  const p = st.progress || {};
  $("sync-progress").hidden = !st.running;
  if (st.running) {
    const pos = p.total ? ` ${p.index}/${p.total}` : "";
    $("sync-progress-label").textContent = `${p.stage || "Démarrage"}${pos}${p.detail ? " · " + p.detail : ""}`;
    $("sync-progress-bar").style.width = p.total ? `${(100 * p.index) / p.total}%` : "0";
  }

  const c = st.counts;
  const period = c.first ? `${c.first.slice(0, 4)} → ${c.last.slice(0, 4)}` : "—";
  const cards = [
    stat(c.total, "activités"), stat(c.running_activities, "course à pied"),
    stat(c.fit_stored, "FIT stockés"), stat(period, "période"),
  ];
  if (c.fit_pending) cards.push(stat(c.fit_pending, "FIT à télécharger"));
  if (c.fit_error) cards.push(stat(c.fit_error, "FIT en erreur"));
  if (c.deleted) cards.push(stat(c.deleted, "supprimées dans Garmin"));
  $("sync-stats").replaceChildren(...cards);

  $("sync-now").disabled = $("sync-full").disabled = st.running;
  $("sync-now").textContent = st.first_import_done ? "Synchroniser maintenant" : "Lancer le premier import";

  $("sync-runs").replaceChildren(...st.runs.map((r) => {
    const tr = document.createElement("tr");
    const cells = [fmtIso(r.started_at), RUN_KINDS[r.kind] || r.kind,
      r.status === "running" ? "en cours…" : (r.error ? `Erreur : ${r.error}` : r.summary)];
    for (const text of cells) {
      const td = document.createElement("td"); td.textContent = text; tr.append(td);
    }
    tr.lastChild.className = "status-" + r.status;
    return tr;
  }));
  if (!st.runs.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td"); td.colSpan = 3; td.className = "muted";
    td.textContent = "Aucune synchro pour l'instant.";
    tr.append(td);
    $("sync-runs").append(tr);
  }

  if (fillSettings) {
    $("ss-enabled").checked = st.settings.enabled;
    $("ss-hour").value = st.settings.hour;
    $("ss-history-start").value = st.settings.history_start;
  }

  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => refreshSync(false), st.running ? 2000 : 30000);
}

async function refreshSync(fillSettings) {
  try {
    renderSync(await api("/sync"), fillSettings);
  } catch (err) {
    if (err.status === 401) init();
  }
}

async function startSync(fullHistory) {
  try {
    showError("sync-error", null);
    renderSync(await api("/sync", { full_history: fullHistory }), false);
  } catch (err) {
    showError("sync-error", err);
  }
}

$("sync-now").addEventListener("click", () => startSync(false));
$("sync-full").addEventListener("click", () => startSync(true));

$("sync-settings-form").addEventListener("submit", (e) => {
  e.preventDefault();
  busy(e.submitter, async () => {
    try {
      await api("/sync/settings", {
        enabled: $("ss-enabled").checked,
        hour: Number($("ss-hour").value),
        history_start: $("ss-history-start").value,
      });
      showError("ss-error", null);
      $("ss-saved").hidden = false;
      setTimeout(() => { $("ss-saved").hidden = true; }, 2500);
    } catch (err) {
      showError("ss-error", err);
    }
  });
});

init();
