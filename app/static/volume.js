"use strict";

// Page Volume et régularité.
(() => {
  const D = JSON.parse(document.getElementById("page-data").textContent);
  const today = new Date(D.today + "T12:00:00");
  const year = today.getFullYear();
  const UNITS = { distance_km: "km", gain_m: "m", km_effort: "km" };

  // ---------- sélecteurs (boutons segmentés) ----------
  function segmented(id, onChange) {
    const box = document.getElementById(id);
    box.addEventListener("click", (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      box.querySelectorAll("button").forEach((b) => b.removeAttribute("aria-current"));
      btn.setAttribute("aria-current", "true");
      onChange(btn.dataset);
    });
  }

  // ---------- cumul jour par jour ----------
  let cumulMetric = "distance_km";
  const todayIndex = GFT.dayOfYear(today);
  const cumulYears = () => Object.keys(D.cumulative[cumulMetric]).sort();
  const cumulChart = GFT.chart("chart-cumul", (t) => {
    const data = D.cumulative[cumulMetric];
    const unit = UNITS[cumulMetric];
    const years = Object.keys(data).sort();
    return {
      grid: { left: 8, right: 16, top: 40, bottom: 8, containLabel: true },
      legend: { top: 0, left: 0, type: "scroll", textStyle: { color: t.muted }, pageTextStyle: { color: t.muted } },
      tooltip: {
        trigger: "axis", ...t.tooltip,
        formatter: (ps) => `${GFT.dayLabel(year, ps[0].dataIndex)}<br>` + ps
          .filter((p) => p.value != null).sort((a, b) => b.value - a.value)
          .map((p) => `${p.marker} ${p.seriesName} : <b>${GFT.num(p.value)} ${unit}</b>`).join("<br>"),
      },
      xAxis: {
        type: "category", data: Array.from({ length: 366 }, (_, i) => i), boundaryGap: false, ...t.axis,
        axisLabel: { ...t.axis.axisLabel, interval: (i) => GFT.isMonthStart(year, i),
                     formatter: (i) => GFT.monthLabel(year, Number(i)) },
      },
      yAxis: { type: "value", ...t.axis, axisLabel: { ...t.axis.axisLabel, formatter: (v) => `${GFT.num(v)} ${unit}` } },
      series: years.map((y) => {
        const current = Number(y) === year;
        return {
          name: y, type: "line", data: data[y], showSymbol: false, z: current ? 10 : 2,
          lineStyle: { width: current ? 3 : 1.6, color: t.year(y) }, itemStyle: { color: t.year(y) },
          emphasis: { focus: "series" },
          ...(current ? { areaStyle: { color: t.accentSoft }, markLine: GFT.todayLine(t, todayIndex) } : {}),
        };
      }),
    };
  });
  GFT.todayButton("cumul-today", cumulChart, todayIndex, () => Math.max(0, cumulYears().indexOf(String(year))));
  segmented("cumul-metric", (d) => { cumulMetric = d.metric; cumulChart.render(); });

  // ---------- par année ----------
  GFT.chart("chart-years", (t) => ({
    grid: { left: 8, right: 8, top: 40, bottom: 8, containLabel: true },
    legend: { top: 0, left: 0, textStyle: { color: t.muted } },
    tooltip: { trigger: "axis", ...t.tooltip },
    xAxis: { type: "category", data: D.yearly.map((y) => String(y.year)), ...t.axis },
    yAxis: [
      { type: "value", ...t.axis, axisLabel: { ...t.axis.axisLabel, formatter: (v) => `${GFT.num(v)} km` } },
      { type: "value", ...t.axis, splitLine: { show: false },
        axisLabel: { ...t.axis.axisLabel, formatter: (v) => `${GFT.num(v)} m/km` } },
    ],
    series: [
      { name: "Distance", type: "bar", barGap: "10%", itemStyle: { color: t.muted }, data: D.yearly.map((y) => ({ value: y.distance_km,
          itemStyle: { color: t.year(y.year), borderRadius: [4, 4, 0, 0] } })),
        tooltip: { valueFormatter: (v) => `${GFT.num(v)} km` } },
      { name: "Km-effort", type: "bar", itemStyle: { color: t.muted, opacity: 0.45 }, data: D.yearly.map((y) => ({ value: y.km_effort,
          itemStyle: { color: t.year(y.year), opacity: 0.45, borderRadius: [4, 4, 0, 0] } })),
        tooltip: { valueFormatter: (v) => `${GFT.num(v)} km` } },
      { name: "D+ par km", type: "line", yAxisIndex: 1, data: D.yearly.map((y) => y.gain_per_km),
        symbolSize: 7, lineStyle: { width: 2, color: t.text }, itemStyle: { color: t.text },
        tooltip: { valueFormatter: (v) => `${GFT.num(v, 1)} m/km` } },
    ],
  }));

  // ---------- par mois ----------
  let monthMetric = "distance_km";
  const MONTHS = Array.from({ length: 12 }, (_, m) =>
    new Date(2000, m, 1).toLocaleDateString("fr-FR", { month: "short" }));
  const monthChart = GFT.chart("chart-months", (t) => {
    const data = D.monthly[monthMetric];
    const years = Object.keys(data).sort();
    const unit = UNITS[monthMetric];
    const selected = Object.fromEntries(years.map((y, i) => [y, i >= years.length - 3]));
    return {
      grid: { left: 8, right: 8, top: 40, bottom: 8, containLabel: true },
      legend: { top: 0, left: 0, type: "scroll", selected, textStyle: { color: t.muted } },
      tooltip: { trigger: "axis", ...t.tooltip, valueFormatter: (v) => `${GFT.num(v)} ${unit}` },
      xAxis: { type: "category", data: MONTHS, ...t.axis },
      yAxis: { type: "value", ...t.axis, axisLabel: { ...t.axis.axisLabel, formatter: (v) => `${GFT.num(v)} ${unit}` } },
      series: years.map((y) => ({
        name: y, type: "bar", data: data[y], itemStyle: { color: t.year(y), borderRadius: [3, 3, 0, 0] },
      })),
    };
  });
  segmented("month-metric", (d) => { monthMetric = d.metric; monthChart.render(); });

  // ---------- calendrier ----------
  let calYear = year;
  const calChart = GFT.chart("chart-calendar", (t) => {
    const days = Object.entries(D.calendar)
      .filter(([d]) => d.startsWith(String(calYear)))
      .map(([d, v]) => [d, v.km]);
    const narrow = document.getElementById("chart-calendar").clientWidth < 600;
    return {
      tooltip: {
        ...t.tooltip,
        formatter: (p) => {
          const v = D.calendar[p.value[0]];
          const day = new Date(p.value[0] + "T12:00:00").toLocaleDateString("fr-FR",
            { weekday: "long", day: "numeric", month: "long" });
          return `${day}<br><b>${GFT.num(v.km, 1)} km</b>, ${GFT.num(v.gain)} m D+<br>`
            + v.names.map((n) => `· ${n}`).join("<br>");
        },
      },
      visualMap: {
        show: false, min: 0, max: 25, inRange: { color: [t.accentSoft, t.accent] },
      },
      calendar: {
        range: String(calYear), orient: narrow ? "vertical" : "horizontal",
        top: narrow ? 30 : 24, left: narrow ? 40 : 36, right: narrow ? 10 : 8, bottom: 4,
        cellSize: narrow ? ["auto", 13] : ["auto", 15],
        itemStyle: { color: t.grid, borderColor: t.surface, borderWidth: 2 },
        splitLine: { show: false },
        dayLabel: { firstDay: 1, nameMap: ["D", "L", "M", "M", "J", "V", "S"], color: t.muted, fontSize: 10 },
        monthLabel: { nameMap: MONTHS, color: t.muted, fontSize: 11 },
        yearLabel: { show: false },
      },
      series: [{ type: "heatmap", coordinateSystem: "calendar", data: days }],
    };
  });
  segmented("cal-year", (d) => { calYear = Number(d.year); calChart.render(); });

  // pastilles de couleur des années dans le tableau
  const t = GFT.palette();
  document.querySelectorAll(".year-dot").forEach((el) => { el.style.background = t.year(el.dataset.year); });
})();
