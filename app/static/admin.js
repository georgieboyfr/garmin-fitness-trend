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
  if (s.authenticated) refreshGarmin();
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

init();
