"use strict";

// Liste des sorties : curseurs min–max de distance et de D+, date courte, ligne cliquable.
(() => {
  const POS = 1000;

  // échelle quadratique : plus de précision vers les petites valeurs, où se trouvent la plupart des sorties
  function setupRange(box) {
    const max = Number(box.dataset.max), step = Number(box.dataset.step), unit = box.dataset.unit;
    const [low, high] = box.querySelectorAll("input[type=range]");
    const [lowField, highField] = box.querySelectorAll("input[type=hidden]");
    const out = box.querySelector(".range-value");
    const toValue = (pos) => Math.min(max, Math.round((max * (pos / POS) ** 2) / step) * step);
    const toPos = (v) => Math.round(POS * Math.sqrt(Math.min(max, Math.max(0, v)) / max));

    low.value = lowField.value === "" ? 0 : toPos(Number(lowField.value));
    high.value = highField.value === "" ? POS : toPos(Number(highField.value));

    function update(moved) {
      if (Number(low.value) > Number(high.value)) {
        if (moved === low) low.value = high.value; else high.value = low.value;
      }
      const lo = Number(low.value), hi = Number(high.value);
      // curseur en bout de course : pas de borne
      lowField.value = lo === 0 ? "" : toValue(lo);
      highField.value = hi === POS ? "" : toValue(hi);
      const a = GFT.num(lo === 0 ? 0 : toValue(lo)), b = GFT.num(hi === POS ? max : toValue(hi));
      out.textContent = lo === 0 && hi === POS ? "toutes" : `${a} – ${b} ${unit}`;
      box.style.setProperty("--lo", `${(lo / POS) * 100}%`);
      box.style.setProperty("--hi", `${(hi / POS) * 100}%`);
      // la poignée basse passe au-dessus quand les deux sont collées en fin de course
      low.style.zIndex = lo > POS - 10 ? 3 : 1;
    }
    [low, high].forEach((input) => {
      input.addEventListener("input", () => update(input));
      input.addEventListener("change", () => box.closest("form").requestSubmit());
    });
    update();
  }

  document.querySelectorAll("[data-range]").forEach(setupRange);

  // adresse lisible : les filtres vides ne sont pas envoyés
  document.getElementById("filters")?.addEventListener("submit", (e) => {
    e.target.querySelectorAll("input[name], select[name]").forEach((f) => { if (f.value === "") f.disabled = true; });
  });

  // date courte avec le jour de la semaine : « lun. 3 nov. 2026 », heure au survol
  document.querySelectorAll("[data-day]").forEach((el) => {
    const d = new Date(el.dataset.day);
    el.textContent = d.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
    el.title = d.toLocaleString("fr-FR", { dateStyle: "full", timeStyle: "short" });
  });

  // toute la ligne mène à la fiche de la sortie
  document.querySelectorAll("tr[data-href]").forEach((tr) => {
    tr.addEventListener("click", (e) => {
      if (e.target.closest("a") || window.getSelection().toString()) return;
      if (e.ctrlKey || e.metaKey) window.open(tr.dataset.href, "_blank");
      else location.href = tr.dataset.href;
    });
  });
})();
