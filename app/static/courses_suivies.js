"use strict";

// Formulaires des courses suivies (ajout sur la page Estimateur, modification sur la page de la course) :
// envoyés en JSON, puis ouverture de la page de la course.
(() => {
  // « 1:45:00 », « 1h45 », « 45:30 » ou « 95 » (minutes) → secondes ; vide → null ; illisible → NaN
  const parseChrono = (text) => {
    const t = text.trim().toLowerCase().replace(/\s/g, "");
    if (!t) return null;
    let m = t.match(/^(\d+)h(\d{1,2})?(?:m(?:in)?)?$/);
    if (m) return Number(m[1]) * 3600 + Number(m[2] || 0) * 60;
    const parts = t.split(":").map(Number);
    if (parts.some((p) => !Number.isFinite(p))) return NaN;
    if (parts.length === 1) return parts[0] * 60;
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    return NaN;
  };

  document.querySelectorAll("form[data-tracked]").forEach((form) => {
    const status = form.querySelector("[role=status]");
    const source = form.querySelector("[name=source]");
    const roadFields = form.querySelector(".tracked-road");
    const sync = () => { roadFields.hidden = source.value !== "distance"; };
    source.addEventListener("change", sync);
    sync();

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const f = (name) => form.querySelector(`[name=${name}]`).value;
      const target = parseChrono(f("target"));
      if (Number.isNaN(target)) { status.textContent = "Objectif illisible : par exemple 1:45:00."; return; }
      const body = { name: f("name"), race_date: f("race_date") || null, target_s: target,
                     gpx_id: source.value === "distance" ? null : source.value,
                     distance_km: f("distance_km"), gain_m: f("gain_m") };
      status.textContent = "Calcul des prédictions…";
      try {
        const r = await fetch(form.dataset.url, { method: "POST", headers: { "Content-Type": "application/json" },
                                                  body: JSON.stringify(body) });
        const j = await r.json();
        if (!r.ok) { status.textContent = j.detail || "Saisie refusée."; return; }
        location.href = `/estimateur/courses/${j.id}`;
      } catch (e) { status.textContent = "Enregistrement impossible."; }
    });
  });

  document.querySelectorAll("[data-tracked-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!window.confirm("Ne plus suivre cette course ? Son historique de prédictions sera effacé.")) return;
      const r = await fetch(btn.dataset.trackedDelete, { method: "POST" });
      if (r.ok) location.href = "/estimateur#suivies";
    });
  });
})();
