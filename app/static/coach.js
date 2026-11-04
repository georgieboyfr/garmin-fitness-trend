"use strict";

// Page Coach : calendrier des échéances, objectif, disponibilités et habitudes, envoyés en JSON
// puis page rechargée.
(() => {
  // « 1:45:00 », « 1h45 », « 45:30 » ou « 95 » (minutes) → secondes ; vide → null ; illisible → NaN
  const parseChrono = (text) => {
    const t = text.trim().toLowerCase().replace(/\s/g, "");
    if (!t) return null;
    const m = t.match(/^(\d+)h(\d{1,2})?(?:m(?:in)?)?$/);
    if (m) return Number(m[1]) * 3600 + Number(m[2] || 0) * 60;
    const parts = t.split(":").map(Number);
    if (parts.some((p) => !Number.isFinite(p))) return NaN;
    if (parts.length === 1) return parts[0] * 60;
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    return NaN;
  };

  const send = async (url, body, status, anchor) => {
    if (status) status.textContent = "Enregistrement…";
    try {
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
                                   body: JSON.stringify(body) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { if (status) status.textContent = j.detail || "Saisie refusée."; return; }
      location.hash = anchor || "";
      location.reload();
    } catch (e) { if (status) status.textContent = "Enregistrement impossible."; }
  };

  // ajout d'une échéance
  const race = document.querySelector("form.coach-race");
  if (race) {
    const f = (name) => race.querySelector(`[name=${name}]`);
    const source = f("source");
    const road = race.querySelector(".coach-road");
    const sync = () => { road.hidden = source.value !== "distance"; };
    source.addEventListener("change", sync);
    sync();
    const prefill = f("prefill");
    if (prefill) prefill.addEventListener("change", () => {
      const opt = prefill.selectedOptions[0];
      if (!opt || !opt.dataset.race) return;
      const v = JSON.parse(opt.dataset.race);
      f("name").value = v.name || "";
      if (v.race_date) f("race_date").value = v.race_date;
      f("target").value = v.target || "";
      const known = v.gpx_id && [...source.options].some((o) => o.value === v.gpx_id);
      source.value = known ? v.gpx_id : "distance";
      f("distance_km").value = v.distance_m ? String(v.distance_m / 1000).replace(".", ",") : "";
      f("gain_m").value = v.gain_m ? Math.round(v.gain_m) : "";
      sync();
    });
    race.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const status = race.querySelector("[role=status]");
      const target = parseChrono(f("target").value);
      if (Number.isNaN(target)) { status.textContent = "Objectif illisible : par exemple 1:45:00."; return; }
      send(race.dataset.url, { name: f("name").value, race_date: f("race_date").value || null,
                               priority: f("priority").value, target_s: target,
                               gpx_id: source.value === "distance" ? null : source.value,
                               distance_km: f("distance_km").value, gain_m: f("gain_m").value },
           status, "echeances");
    });
  }

  // objectif saisi, ou proposition acceptée
  document.querySelectorAll("form.coach-target").forEach((form) => {
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const status = form.querySelector("[role=status]");
      const target = parseChrono(form.querySelector("[name=target]").value);
      if (Number.isNaN(target)) { status.textContent = "Illisible : par exemple 1:45:00."; return; }
      send(form.dataset.url, { target_s: target }, status, "echeances");
    });
  });
  document.querySelectorAll("[data-accept]").forEach((btn) => {
    btn.addEventListener("click", () => send(btn.dataset.accept, { target_s: Number(btn.dataset.value) },
                                             null, "echeances"));
  });
  document.querySelectorAll("[data-coach-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!window.confirm("Retirer cette course du calendrier du coach ?")) return;
      const r = await fetch(btn.dataset.coachDelete, { method: "POST" });
      if (r.ok) { location.hash = "echeances"; location.reload(); }
    });
  });

  // disponibilités par jour
  const avail = document.querySelector("form.coach-availability");
  if (avail) {
    const status = avail.querySelector("[role=status]");
    avail.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const days = [...avail.querySelectorAll("tr[data-weekday]")].map((tr) => {
        const minutes = tr.querySelector("[name=max_min]").value.trim();
        return { weekday: Number(tr.dataset.weekday), status: tr.querySelector("[name=status]").value,
                 max_min: minutes ? Number(minutes) : null };
      });
      if (days.some((d) => d.max_min !== null && !Number.isFinite(d.max_min))) {
        status.textContent = "Durée en minutes, par exemple 60."; return;
      }
      send(avail.dataset.url, { availability: days }, status, "disponibilites");
    });
    const reset = avail.querySelector("[data-reset]");
    if (reset) reset.addEventListener("click", () => send(avail.dataset.url, { availability: null }, status,
                                                          "disponibilites"));
  }

  // habitudes gardées
  const habits = document.querySelector("form.coach-habits");
  if (habits) habits.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const list = [...habits.querySelectorAll("li[data-weekday]")].map((li) => ({
      weekday: Number(li.dataset.weekday), place: JSON.parse(li.dataset.place),
      name: li.querySelector("[name=name]").value, keep: li.querySelector("[name=keep]").checked }));
    send(habits.dataset.url, { habits: list }, habits.querySelector("[role=status]"), "habitudes");
  });
})();
