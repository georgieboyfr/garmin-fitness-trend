"use strict";

// Fiche d'une sortie : carte, profils, zones de FC, passages sur le même parcours.
(() => {
  const D = JSON.parse(document.getElementById("page-data").textContent);
  const P = D.profiles;
  const paceLabel = (s) => `${Math.floor(s / 60)}'${String(Math.round(s % 60)).padStart(2, "0")}"`;

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
        series.push({ name: conf.label, type: "line", xAxisIndex: i, yAxisIndex: i, data: conf.data, showSymbol: false,
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
