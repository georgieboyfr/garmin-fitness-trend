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
  $("stats-link").hidden = !s.authenticated;
  if (s.authenticated) {
    refreshGarmin();
    refreshSync(true);
    refreshElevation(true);
    refreshPhysiology();
    refreshRaces();
    refreshStrava();
  }
}

$("login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  busy(e.submitter, async () => {
    try {
      await api("/login", { username: $("login-user").value, password: $("login-password").value });
      $("login-password").value = "";
      showError("login-error", null);
      // retour à la page de statistiques demandée avant la connexion
      const next = new URLSearchParams(location.search).get("next");
      if (next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/admin")) {
        location.href = next;
        return;
      }
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
  $("garmin-empty").hidden = st.state !== "disconnected";

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

// ---------- dénivelé ----------

const SOURCES = { barometer: "Baromètre", dem: "MNT", strava: "Strava (hors de France)", none: "Sans GPS (D+ = 0)" };
const PROVIDERS = { ign: "IGN", copernicus: "Copernicus", "ign+copernicus": "IGN + Copernicus" };
const fmtM = (v) => v == null ? "—" : `${Math.round(v).toLocaleString("fr-FR")} m`;

function renderElevation(st, fillSettings) {
  const pill = $("elev-pill");
  pill.textContent = st.pending ? `${st.pending} à calculer` : "À jour";
  pill.className = "pill " + (st.pending ? "warn" : "ok");
  $("elev-sources").replaceChildren(...st.by_source.map((r) => {
    const tr = document.createElement("tr");
    const label = SOURCES[r.source]
      + (r.dem_provider && r.source === "dem" ? ` (${PROVIDERS[r.dem_provider] || r.dem_provider})` : "");
    [label, r.n, fmtM(r.gain_m), fmtM(r.garmin_gain_m)].forEach((text, i) => {
      const td = document.createElement("td"); td.textContent = text;
      if (i) td.className = "num";
      tr.append(td);
    });
    return tr;
  }));
  if (fillSettings) {
    $("ev-step").value = st.settings.step_m;
    $("ev-window").value = st.settings.window;
    $("ev-thr-baro").value = st.settings.threshold_barometer;
    $("ev-thr-dem").value = st.settings.threshold_dem;
  }
}

async function refreshElevation(fillSettings) {
  try { renderElevation(await api("/elevation"), fillSettings); } catch (err) { /* session gérée ailleurs */ }
}

function flash(id, text) {
  $(id).textContent = text;
  $(id).hidden = false;
  setTimeout(() => { $(id).hidden = true; }, 3000);
}

$("elev-form").addEventListener("submit", (e) => {
  e.preventDefault();
  busy(e.submitter, async () => {
    try {
      await api("/elevation/settings", {
        step_m: Number($("ev-step").value), window: Number($("ev-window").value),
        threshold_barometer: Number($("ev-thr-baro").value), threshold_dem: Number($("ev-thr-dem").value),
      });
      showError("ev-error", null);
      flash("ev-saved", "Enregistré : le D+ sera recalculé à la prochaine synchro, ou maintenant.");
      refreshElevation(false);
    } catch (err) {
      showError("ev-error", err);
    }
  });
});

$("ev-recompute").addEventListener("click", (e) => {
  busy(e.currentTarget, async () => {
    try {
      renderSync(await api("/recompute", {}), false);
      showError("ev-error", null);
    } catch (err) {
      showError("ev-error", err);
    }
  });
});

// ---------- courses ----------

const fmtShort = (d) => new Date(d + "T12:00:00").toLocaleDateString("fr-FR", { dateStyle: "medium" });

// actions selon la liste : en attente, confirmée ou rejetée
const RACE_ACTIONS = {
  pending: [["C'est une course", "confirmed", "primary"], ["Non", "rejected"]],
  confirmed: [["Ce n'est pas une course", "rejected", "ghost"], ["Remettre en attente", null, "ghost"]],
  rejected: [["C'est une course", "confirmed", "primary"], ["Remettre en attente", null, "ghost"]],
};

function raceRow(r, list) {
  const div = document.createElement("div");
  div.className = "race";
  const head = document.createElement("div");
  head.className = "race-head";
  const a = document.createElement("a");
  a.href = `/sorties/${r.id}`;
  a.textContent = r.name || "Sans nom";
  const meta = document.createElement("span");
  meta.className = "muted small";
  meta.textContent = `${fmtShort(r.date)} · ${(r.distance_km).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} km`
    + ` · ${r.gain_m} m D+`;
  head.append(a, meta);
  div.append(head);
  if (r.description) {
    const desc = document.createElement("div");
    desc.className = "race-desc";
    desc.textContent = r.description;
    div.append(desc);
  }
  if (r.reasons) {
    const reasons = document.createElement("div");
    reasons.className = "race-reasons";
    const score = document.createElement("span");
    score.className = "score";
    score.textContent = `score ${r.score} · `;
    reasons.append(score, r.reasons.join(" · "));
    div.append(reasons);
  }
  const actions = document.createElement("div");
  actions.className = "race-actions";
  const button = (label, status, cls) => {
    const b = document.createElement("button");
    b.className = "btn small " + (cls || "");
    b.textContent = label;
    b.addEventListener("click", () => busy(b, async () => {
      await api(`/races/${r.id}`, { status });
      refreshRaces();
    }));
    return b;
  };
  actions.append(...RACE_ACTIONS[list].map(([label, status, cls]) => button(label, status, cls)));
  div.append(actions);
  return div;
}

function renderRaces(st) {
  const pill = $("races-pill");
  pill.textContent = st.pending.length ? `${st.pending.length} à valider` : "À jour";
  pill.className = "pill " + (st.pending.length ? "warn" : "ok");
  $("races-pending").replaceChildren(...(st.pending.length ? st.pending.map((r) => raceRow(r, "pending"))
    : [Object.assign(document.createElement("p"), { className: "muted small", textContent: "Aucune course probable à valider." })]));
  $("races-confirmed-title").textContent = `Courses confirmées (${st.confirmed.length})`;
  $("races-confirmed").replaceChildren(...st.confirmed.map((r) => raceRow(r, "confirmed")));
  $("races-rejected-title").textContent = `Sorties rejetées (${st.rejected.length})`;
  $("races-rejected").replaceChildren(...st.rejected.map((r) => raceRow(r, "rejected")));
  $("races-keywords").value = st.settings.keywords.join("\n");
  $("races-threshold").value = st.settings.threshold;
}

async function refreshRaces() {
  try { renderRaces(await api("/races")); } catch (err) { /* session gérée ailleurs */ }
}

$("races-form").addEventListener("submit", (e) => {
  e.preventDefault();
  busy(e.submitter, async () => {
    try {
      renderRaces(await api("/races/settings", {
        keywords: $("races-keywords").value.split("\n").map((k) => k.trim()).filter(Boolean),
        threshold: Number($("races-threshold").value),
      }));
      showError("races-error", null);
    } catch (err) {
      showError("races-error", err);
    }
  });
});
$("races-reset").addEventListener("click", (e) => busy(e.currentTarget, async () => {
  renderRaces(await api("/races/settings", { keywords: null }));
}));

// ---------- physiologie ----------

let phyEstimate = null;

function renderPhysiology(st) {
  const s = st.settings, env = st.env, y = st.last_12_months, all = st.all_time;
  const fmtDay = (d) => new Date(d + "T12:00:00").toLocaleDateString("fr-FR", { dateStyle: "medium" });
  const origin = (k) => (s[k] === env[k] ? ".env" : "admin");
  $("phy-stats").replaceChildren(
    stat(`${s.lthr}`, `LTHR en vigueur (${origin("lthr")})`),
    stat(y.best_60min ? `${y.best_60min.hr}` : "—", "LTHR estimée (12 mois)"),
    stat(`${s.hr_max}`, `FC max en vigueur (${origin("hr_max")})`),
    stat(all.max_hr ? `${all.max_hr}` : "—", "FC max observée"),
  );
  $("phy-note").textContent = y.best_60min
    ? `Estimation : meilleure FC moyenne tenue une heure sur les 12 derniers mois (${y.best_60min.hr}, le `
      + `${fmtDay(y.best_60min.date)}) ; sur 30 min : ${y.best_30min ? y.best_30min.hr : "—"}. Un effort d'une heure `
      + `à fond se court au seuil. FC max observée sur 12 mois : ${y.max_hr ?? "—"} (la plus haute de tout `
      + `l'historique peut venir d'un artefact du capteur).`
    : "Pas encore de sortie d'une heure avec FC sur les 12 derniers mois.";
  $("phy-lthr").value = s.lthr;
  $("phy-hrmax").value = s.hr_max;
  $("phy-hrrest").value = s.hr_rest;
  phyEstimate = y.best_60min ? y.best_60min.hr : null;
  $("phy-use-estimate").hidden = !phyEstimate || phyEstimate === s.lthr;
  $("phy-use-estimate").textContent = `Utiliser l'estimation (${phyEstimate})`;
  $("phy-reset").hidden = ["lthr", "hr_max", "hr_rest"].every((k) => s[k] === env[k]);
  const z = st.zones;
  $("phy-zones").textContent = `Zones (Friel, sur la LTHR en vigueur) : Z1 < ${z[0]}, Z2 ${z[0]}–${z[1] - 1}, `
    + `Z3 ${z[1]}–${z[2] - 1}, Z4 ${z[2]}–${z[3] - 1}, Z5 ≥ ${z[3]}.`;
}

async function refreshPhysiology() {
  try { renderPhysiology(await api("/physiology")); } catch (err) { /* session gérée ailleurs */ }
}

async function savePhysiology(values) {
  try {
    renderPhysiology(await api("/physiology", values));
    showError("phy-error", null);
    flash("phy-saved", "Enregistré : les sorties sont en cours de recalcul.");
    refreshSync(false);
  } catch (err) {
    showError("phy-error", err);
  }
}

$("phy-form").addEventListener("submit", (e) => {
  e.preventDefault();
  busy(e.submitter, () => savePhysiology({
    lthr: Number($("phy-lthr").value), hr_max: Number($("phy-hrmax").value), hr_rest: Number($("phy-hrrest").value),
  }));
});
$("phy-use-estimate").addEventListener("click", () => { $("phy-lthr").value = phyEstimate; });
$("phy-reset").addEventListener("click", (e) =>
  busy(e.currentTarget, () => savePhysiology({ lthr: null, hr_max: null, hr_rest: null })));

// ---------- Strava ----------

const IMPORT_STATUS = {
  ok: "importé", older: "ignoré : plus ancien que le dernier importé",
  duplicate: "ignoré : déjà importé", error: "illisible",
};

function cells(tr, values) {
  for (const v of values) {
    const td = document.createElement("td"); td.textContent = v; tr.append(td);
  }
  return tr;
}

function renderStrava(st) {
  const c = st.counts;
  const pill = $("strava-pill");
  pill.textContent = c.total ? `Export du ${fmtIso(c.last_activity).split(" ")[0]}` : "Aucun export";
  pill.className = "pill " + (c.total ? "ok" : "off");
  $("strava-stats").replaceChildren(
    stat(c.named, "noms repris"), stat(c.matched, "activités appariées"),
    stat(c.imported, "sorties sans montre importées"), stat(c.waiting_next_export, "en attente du prochain export"),
  );
  $("strava-unmatched-box").hidden = !st.unmatched_runs.length;
  $("strava-unmatched").replaceChildren(...st.unmatched_runs.map((r) => cells(document.createElement("tr"),
    [fmtIso(r.start_time_utc), r.name, r.distance_m == null ? "—" : `${(r.distance_m / 1000).toFixed(1)} km`])));
  $("strava-imports").replaceChildren(...st.imports.map((r) => {
    const tr = cells(document.createElement("tr"), [r.filename,
      (IMPORT_STATUS[r.status] || r.status) + (r.activities ? ` (${r.activities} activités)` : "")
        + (r.error ? ` : ${r.error}` : ""),
      fmtIso(r.last_activity_utc)]);
    tr.children[1].className = "status-" + (r.status === "error" ? "error" : "ok");
    return tr;
  }));
}

async function refreshStrava() {
  try { renderStrava(await api("/strava")); } catch (err) { /* session gérée ailleurs */ }
}

$("strava-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const file = $("strava-file").files[0];
  if (!file) return;
  busy($("strava-send"), async () => {
    showError("strava-error", null);
    $("strava-result").hidden = false;
    $("strava-result").textContent = `Envoi de ${file.name} (${(file.size / 1e6).toFixed(1)} Mo)…`;
    try {
      const r = await fetch("/admin/api/strava/upload?name=" + encodeURIComponent(file.name), {
        method: "POST", body: file, headers: { "X-Requested-With": "admin-ui" },
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || `Erreur ${r.status}`);
      $("strava-result").textContent = `${IMPORT_STATUS[data.status] || data.status}`
        + (data.activities ? ` : ${data.activities} activités, ${data.matched || 0} appariées` : "")
        + (data.imported_new ? `, ${data.imported_new} sortie(s) sans montre ajoutée(s)` : "");
      $("strava-file").value = "";
      refreshStrava();
      refreshSync(false);
    } catch (err) {
      $("strava-result").hidden = true;
      showError("strava-error", err);
    }
  });
});

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
