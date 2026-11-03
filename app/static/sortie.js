"use strict";

// Fiche d'une sortie : carte, profils, zones de FC, passages sur le même parcours.
(() => {
  const D = JSON.parse(document.getElementById("page-data").textContent);
  const P = D.profiles;
  const paceLabel = (s) => `${Math.floor(s / 60)}'${String(Math.round(s % 60)).padStart(2, "0")}"`;

  // ---------- marquer comme course (enregistré comme une décision de l'admin) ----------
  const toggle = document.getElementById("race-toggle");
  toggle?.addEventListener("click", async () => {
    const confirmed = toggle.dataset.status === "confirmed";
    toggle.disabled = true;
    const r = await fetch(`/admin/api/races/${toggle.dataset.id}`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "admin-ui" },
      body: JSON.stringify({ status: confirmed ? "rejected" : "confirmed" }),
    });
    if (r.ok) location.reload();
    else toggle.disabled = false;
  });

  // ---------- carte : Plan IGN (France), photos aériennes, OpenStreetMap ----------
  let hoverMarker = null;
  if (P.track.length && window.L) {
    const ign = (layer, format) => L.tileLayer(
      "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=" + layer
      + "&STYLE=normal&TILEMATRIXSET=PM&FORMAT=" + format + "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}",
      { maxZoom: 19, maxNativeZoom: 18, attribution: "&copy; IGN" });
    const layers = {
      "Plan IGN": ign("GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", "image/png"),
      "Photos aériennes": ign("ORTHOIMAGERY.ORTHOPHOTOS", "image/jpeg"),
      "OpenStreetMap": L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        { maxZoom: 19, attribution: "&copy; contributeurs OpenStreetMap" }),
    };
    const [lat0, lon0] = P.track[0];
    const inFrance = lat0 > 41 && lat0 < 51.2 && lon0 > -5.3 && lon0 < 9.7;
    const map = L.map("map", { scrollWheelZoom: false, layers: [inFrance ? layers["Plan IGN"] : layers.OpenStreetMap] });
    L.control.layers(layers, null, { collapsed: true }).addTo(map);
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
    const line = L.polyline(P.track, { color: accent, weight: 4, opacity: 0.9 }).addTo(map);
    const dot = (pos, color) => L.circleMarker(pos, { radius: 6, color: "#fff", weight: 2, fillColor: color, fillOpacity: 1 });
    dot(P.track[0], "#2b8a3e").bindTooltip("Départ").addTo(map);
    dot(P.track[P.track.length - 1], "#c92a2a").bindTooltip("Arrivée").addTo(map);
    hoverMarker = dot(P.track[0], accent);
    map.fitBounds(line.getBounds(), { padding: [16, 16] });
    window.__map = map;

    // zoom à la molette avec Ctrl (ou au pincement du pavé tactile) : la molette seule fait défiler la page
    const box = map.getContainer();
    const hint = L.DomUtil.create("div", "map-hint", box);
    hint.textContent = "Ctrl + molette pour zoomer";
    let hintTimer = null, wheelSum = 0;
    box.addEventListener("wheel", (e) => {
      if (!e.ctrlKey && !e.metaKey) {
        hint.classList.add("show");
        clearTimeout(hintTimer);
        hintTimer = setTimeout(() => hint.classList.remove("show"), 1200);
        return;
      }
      e.preventDefault();
      hint.classList.remove("show");
      // un cran de molette vaut environ 100 ; le pincement envoie de petits pas, cumulés
      wheelSum += e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
      if (Math.abs(wheelSum) < 60) return;
      const step = wheelSum < 0 ? 1 : -1;
      wheelSum = 0;
      map.setZoomAround(map.mouseEventToContainerPoint(e), map.getZoom() + step);
    }, { passive: false });
  }

  // ---------- profils : altitude, allure, FC ----------
  if (P.km.length) {
    const hasAlt = P.altitude.some((v) => v != null);
    const hasHr = P.hr.some((v) => v != null);
    const panels = [hasAlt && "alt", "pace", hasHr && "hr"].filter(Boolean);
    // échelle de l'allure : du 5e au 95e centile, avec une marge (les arrêts ne l'écrasent pas)
    const sortedPace = P.pace.filter((v) => v != null).sort((a, b) => a - b);
    const pct = (q) => sortedPace[Math.min(sortedPace.length - 1, Math.floor(q * sortedPace.length))];
    const paceBounds = sortedPace.length
      ? { min: Math.max(120, Math.floor((pct(0.05) - 30) / 60) * 60), max: Math.ceil((pct(0.95) + 60) / 60) * 60 }
      : {};
    // indice du point de profil atteint à un instant donné (pour surligner les intervalles)
    const kmIndexAt = (sec) => {
      let i = P.time_s.findIndex((v) => v != null && v >= sec);
      return i < 0 ? P.time_s.length - 1 : i;
    };
    // une graduation par kilomètre (ou tous les 2, 5, 10 km sur les longues sorties)
    const totalKm = P.km[P.km.length - 1] || 1;
    const kmStep = [1, 2, 5, 10, 20].find((s) => totalKm / s <= 12) || 50;
    const kmTick = (i) => i > 0 && Math.floor(P.km[i] / kmStep) !== Math.floor(P.km[i - 1] / kmStep);
    // allure : une graduation par minute (ou toutes les 2 min si l'écart est grand)
    const paceInterval = paceBounds.max && paceBounds.max - paceBounds.min > 360 ? 120 : 60;
    const chart = GFT.chart("chart-profile", (t) => {
      const h = 92 / panels.length;
      const grids = panels.map((_, i) => ({ left: 8, right: 16, top: `${i * h + 9}%`, height: `${h - 10}%`,
                                            containLabel: true }));
      const kmLabels = P.km.map((v) => v);
      const series = [];
      const yAxis = [];
      panels.forEach((name, i) => {
        const conf = {
          alt: { label: "Altitude", data: P.altitude, color: t.series[2], unit: "m", area: true },
          pace: { label: "Allure", data: P.pace, color: t.accent, unit: "/km" },
          hr: { label: "FC", data: P.hr, color: t.series[3], unit: "bpm" },
        }[name];
        const bounds = name === "pace" ? { ...paceBounds, interval: paceInterval } : {};
        yAxis.push({ type: "value", gridIndex: i, scale: true, inverse: name === "pace", splitNumber: 3, ...t.axis,
          ...bounds, axisLabel: { ...t.axis.axisLabel, formatter: (v) => name === "pace" ? paceLabel(v) : GFT.num(v) } });
        const efforts = name === "pace" && P.intervals
          ? P.intervals.rows.filter((r) => r.kind === "effort" || r.kind === "tour") : [];
        series.push({ name: conf.label, type: "line", xAxisIndex: i, yAxisIndex: i, data: conf.data, showSymbol: false,
          ...(efforts.length ? { markArea: { silent: true, itemStyle: { color: t.accentSoft },
            data: efforts.map((r) => [{ xAxis: kmIndexAt(r.start_s) }, { xAxis: kmIndexAt(r.start_s + r.duration_s) }]) } } : {}),
          connectNulls: name !== "pace", lineStyle: { width: 1.6, color: conf.color }, itemStyle: { color: conf.color },
          ...(conf.area ? { areaStyle: { color: conf.color, opacity: 0.12 } } : {}) });
      });
      return {
        grid: grids,
        legend: { top: 0, left: 0, textStyle: { color: t.muted }, selectedMode: false },
        axisPointer: { link: [{ xAxisIndex: "all" }] },
        tooltip: {
          trigger: "axis", ...t.tooltip,
          formatter: (ps) => {
            const i = ps[0].dataIndex;
            const parts = [`<b>${GFT.num(P.km[i], 2)} km</b> · ${GFT.chrono(P.time_s[i])}`];
            if (hasAlt && P.altitude[i] != null) parts.push(`Altitude : ${GFT.num(P.altitude[i])} m`);
            if (P.pace[i] != null) parts.push(`Allure : ${paceLabel(P.pace[i])} /km`);
            if (hasHr && P.hr[i] != null) parts.push(`FC : ${P.hr[i]} bpm`);
            return parts.join("<br>");
          },
        },
        xAxis: panels.map((_, i) => ({ type: "category", gridIndex: i, data: kmLabels, boundaryGap: false, ...t.axis,
          axisLabel: { ...t.axis.axisLabel, show: i === panels.length - 1, interval: kmTick,
                       formatter: (v) => `${GFT.num(Math.round(v), 0)} km` } })),
        yAxis, series,
      };
    });
    // survol du profil : position sur la carte
    if (chart && hoverMarker && window.__map) {
      chart.instance.on("updateAxisPointer", (e) => {
        const info = e.axesInfo && e.axesInfo[0];
        if (!info) return;
        const pos = P.track[info.value];
        if (pos) hoverMarker.setLatLng(pos).addTo(window.__map);
      });
      chart.instance.getZr().on("globalout", () => hoverMarker.remove());
    }
  }

  // ---------- zones de FC ----------
  const totalZones = D.zones.reduce((a, b) => a + b, 0);
  GFT.chart("chart-zones", (t) => ({
    grid: { left: 8, right: 40, top: 4, bottom: 4, containLabel: true },
    tooltip: { ...t.tooltip, formatter: (p) => `${p.name} : <b>${GFT.duration(p.value)}</b>` },
    xAxis: { type: "value", show: false },
    yAxis: { type: "category", data: ["Z1", "Z2", "Z3", "Z4", "Z5"], inverse: true, ...t.axis, splitLine: { show: false } },
    series: [{ type: "bar", barMaxWidth: 18,
      data: D.zones.map((v, i) => ({ value: v,
        itemStyle: { color: [t.series[2], t.series[1], t.series[4], t.series[0], t.series[5]][i], borderRadius: 4 } })),
      label: { show: true, position: "right", color: t.muted, fontSize: 11,
               formatter: (p) => totalZones ? `${Math.round(p.value / totalZones * 100)} %` : "" } }],
  }));

  // ---------- passages sur le même parcours ----------
  if (D.passages.length > 1) {
    const chart = GFT.chart("chart-route", (t) => ({
      grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
      tooltip: { ...t.tooltip, formatter: (p) => { const x = D.passages[p.dataIndex];
        return `${new Date(x.date + "T12:00:00").toLocaleDateString("fr-FR", { dateStyle: "medium" })}<br>`
          + `<b>${GFT.duration(x.moving_s)}</b>${x.avg_hr ? ` · FC ${Math.round(x.avg_hr)}` : ""}<br>${x.name}`
          + (x.id === D.id ? "<br><i>cette sortie</i>" : "<br><i>clique pour l'ouvrir</i>"); } },
      xAxis: { type: "time", ...t.axis },
      yAxis: { type: "value", scale: true, ...t.axis, axisLabel: { ...t.axis.axisLabel, formatter: (v) => GFT.duration(v) } },
      series: [{ type: "line", data: D.passages.map((x) => [x.date, x.moving_s]),
        symbolSize: (v, p) => (D.passages[p.dataIndex].id === D.id ? 14 : 8),
        lineStyle: { color: t.muted, width: 1, type: "dashed" },
        itemStyle: { color: (p) => (D.passages[p.dataIndex].id === D.id ? t.accent : t.series[1]) } }],
    }));
    chart?.instance.on("click", (p) => {
      const x = D.passages[p.dataIndex];
      if (x && x.id !== D.id) location.href = `/sorties/${x.id}`;
    });
  }
})();

// ---------- estimé et réel (course réalisée) ----------
(() => {
  const btn = document.getElementById("estimate-run");
  if (!btn) return;
  const status = document.getElementById("estimate-status");
  const signed = (s) => (s > 0 ? "+" : s < 0 ? "−" : "") + GFT.chrono(Math.abs(s));
  const run = async () => {
    btn.disabled = true;
    status.textContent = "Calcul en cours…";
    try {
      const r = await fetch(btn.dataset.url);
      const data = await r.json();
      if (!r.ok) { status.textContent = data.detail || data.error || "Estimation impossible."; return; }
      status.textContent = "";
      btn.hidden = true;
      show(data);
    } catch (e) { status.textContent = "Estimation impossible."; } finally { btn.disabled = false; }
  };
  const show = (data) => {
    document.getElementById("estimate-result").hidden = false;
    const rows = document.getElementById("estimate-rows");
    rows.replaceChildren(...data.estimates.map((e) => {
      const tr = document.createElement("tr");
      const day = new Date(e.day + "T12:00:00").toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
      const gap = data.elapsed_s - e.realistic_s;
      tr.innerHTML = `<td></td><td class="strong"></td><td class="muted"></td><td></td><td></td>`;
      tr.children[0].textContent = `${e.label} (${day})`;
      tr.children[1].textContent = GFT.chrono(e.realistic_s);
      tr.children[2].textContent = `${GFT.chrono(e.optimistic_s)} – ${GFT.chrono(e.prudent_s)}`;
      tr.children[3].textContent = GFT.chrono(data.elapsed_s);
      tr.children[4].textContent = `${signed(gap)} (${e.error_pct > 0 ? "estimé trop lent" : "estimé trop rapide"} de `
        + `${Math.abs(e.error_pct).toFixed(1).replace(".", ",")} %)`;
      return tr;
    }));
    GFT.chart("chart-estimate", (t) => {
      const colors = [t.accent, t.series[2]];
      return {
        grid: { left: 8, right: 8, top: 28, bottom: 28, containLabel: true },
        legend: { top: 0, textStyle: { color: t.muted }, data: data.estimates.map((e) => e.label) },
        tooltip: { ...t.tooltip, trigger: "axis", formatter: (ps) => {
          const i = ps[0].dataIndex;
          return `<b>Km ${GFT.num(data.km[i], 1)}</b> · ${GFT.num(data.altitude[i])} m<br>Réel ${GFT.chrono(data.actual[i])}`
            + data.estimates.map((e) => `<br>${e.label} : ${GFT.chrono(e.times[i])} (${signed(e.gap[i])})`).join(""); } },
        xAxis: { type: "value", min: 0, max: data.km[data.km.length - 1], ...t.axis,
                 axisLabel: { ...t.axis.axisLabel, formatter: "{value} km", showMaxLabel: false } },
        yAxis: [
          { type: "value", ...t.axis, axisLabel: { ...t.axis.axisLabel, formatter: (v) => signed(v) } },
          { type: "value", scale: true, show: false },
        ],
        series: [
          { name: "Altitude", type: "line", yAxisIndex: 1, symbol: "none", silent: true,
            data: data.km.map((k, i) => [k, data.altitude[i]]), lineStyle: { opacity: 0 },
            areaStyle: { color: t.grid, opacity: 0.6 } },
          ...data.estimates.map((e, j) => ({
            name: e.label, type: "line", symbol: "none", lineStyle: { width: 2, color: colors[j] },
            itemStyle: { color: colors[j] }, data: data.km.map((k, i) => [k, e.gap[i]]),
            markLine: j ? undefined : { symbol: "none", silent: true, data: [{ yAxis: 0 }],
                                        lineStyle: { color: t.muted, type: "dashed" }, label: { show: false } } })),
        ],
      };
    });
  };
  btn.addEventListener("click", run);
  if (location.hash === "#estime-reel") run();
})();

