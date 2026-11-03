"use strict";

// Page Forme : Fitness / Fatigue / Form, pics, zones, Efficiency Factor, découplage.
(() => {
  const D = JSON.parse(document.getElementById("page-data").textContent);
  const s = D.series;
  const dateFmt = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("fr-FR",
    { day: "numeric", month: "short", year: "numeric" });

  // ---------- fitness, fatigue, forme ----------
  GFT.chart("chart-fff", (t) => {
    const startIdx = Math.max(0, s.dates.length - 365);   // la dernière année par défaut
    return {
      grid: [{ left: 8, right: 16, top: 40, height: "58%", containLabel: true },
             { left: 8, right: 16, top: "74%", bottom: 64, containLabel: true }],
      legend: { top: 0, left: 0, textStyle: { color: t.muted } },
      tooltip: {
        trigger: "axis", ...t.tooltip,
        formatter: (ps) => `${dateFmt(s.dates[ps[0].dataIndex])}<br>` + ps
          .map((p) => `${p.marker} ${p.seriesName} : <b>${GFT.num(p.value, p.seriesName === "Charge" ? 0 : 1)}</b>`)
          .join("<br>"),
      },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      xAxis: [
        { type: "category", data: s.dates, gridIndex: 0, ...t.axis, axisLabel: { show: false } },
        { type: "category", data: s.dates, gridIndex: 1, ...t.axis,
          axisLabel: { ...t.axis.axisLabel, formatter: (v) => dateFmt(v) } },
      ],
      yAxis: [
        { type: "value", gridIndex: 0, ...t.axis },
        { type: "value", gridIndex: 1, ...t.axis, splitNumber: 2 },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1], startValue: startIdx },
        { type: "slider", xAxisIndex: [0, 1], startValue: startIdx, bottom: 8, height: 22,
          borderColor: t.border, textStyle: { color: t.muted }, labelFormatter: (i) => dateFmt(s.dates[i]),
          fillerColor: t.accentSoft, dataBackground: { lineStyle: { color: t.muted }, areaStyle: { color: t.grid } } },
      ],
      series: [
        { name: "Fitness", type: "line", data: s.fitness, showSymbol: false,
          lineStyle: { width: 2.5, color: t.series[1] }, itemStyle: { color: t.series[1] },
          areaStyle: { color: t.series[1], opacity: 0.08 } },
        { name: "Fatigue", type: "line", data: s.fatigue, showSymbol: false,
          lineStyle: { width: 1.5, color: t.series[3] }, itemStyle: { color: t.series[3] } },
        { name: "Forme", type: "line", data: s.form, showSymbol: false,
          lineStyle: { width: 2, color: t.accent }, itemStyle: { color: t.accent },
          markArea: { silent: true, data: [
            [{ yAxis: 5, itemStyle: { color: t.series[2], opacity: 0.07 } }, { yAxis: 25 }],
            [{ yAxis: -30, itemStyle: { color: t.series[1], opacity: 0.05 } }, { yAxis: -10 }],
          ] } },
        { name: "Charge", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: s.stress,
          itemStyle: { color: t.muted, opacity: 0.6 }, barMaxWidth: 6 },
      ],
    };
  });

  // ---------- pics par année ----------
  GFT.chart("chart-peaks", (t) => ({
    grid: { left: 8, right: 8, top: 24, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis", ...t.tooltip,
      formatter: (ps) => { const p = D.peaks[ps[0].dataIndex];
        return `${p.year} : <b>${GFT.num(p.fitness, 1)}</b><br>le ${dateFmt(p.date)}`; } },
    xAxis: { type: "category", data: D.peaks.map((p) => String(p.year)), ...t.axis },
    yAxis: { type: "value", ...t.axis },
    series: [{ type: "bar", barMaxWidth: 40,
      data: D.peaks.map((p) => ({ value: p.fitness, itemStyle: { color: t.year(p.year), borderRadius: [4, 4, 0, 0] } })),
      label: { show: true, position: "top", color: t.muted, fontSize: 11, formatter: (p) => GFT.num(p.value) } }],
  }));

  // ---------- zones de FC par année ----------
  const ZONE_NAMES = ["Z1", "Z2", "Z3", "Z4", "Z5"];
  GFT.chart("chart-zones", (t) => {
    const colors = [t.series[2], t.series[1], t.series[4], t.series[0], t.series[5]];
    return {
      grid: { left: 8, right: 8, top: 32, bottom: 8, containLabel: true },
      legend: { top: 0, left: 0, itemWidth: 12, textStyle: { color: t.muted } },
      tooltip: { trigger: "axis", ...t.tooltip, valueFormatter: (v) => `${GFT.num(v, 0)} %` },
      xAxis: { type: "category", data: D.zones.map((z) => String(z.year)), ...t.axis },
      yAxis: { type: "value", max: 100, ...t.axis, axisLabel: { ...t.axis.axisLabel, formatter: "{value} %" } },
      series: ZONE_NAMES.map((name, i) => ({
        name, type: "bar", stack: "z", barMaxWidth: 40, data: D.zones.map((z) => z.pct[i]),
        itemStyle: { color: colors[i] },
        ...(i === 1 ? { markLine: { silent: true, symbol: "none", data: [{ yAxis: 80 }],
          lineStyle: { color: t.text, type: "dashed" },
          label: { formatter: "80 %", color: t.muted, position: "insideEndTop" } } } : {}),
      })),
    };
  });

  // un clic sur un point ouvre la sortie
  const openOnClick = (chart, rows) => chart?.instance.on("click", (p) => {
    const row = rows[p.dataIndex];
    if (p.seriesIndex === 0 && row && row.id != null) location.href = `/sorties/${row.id}`;
  });

  // ---------- Efficiency Factor ----------
  const efChart = GFT.chart("chart-ef", (t) => ({
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    legend: { top: 0, left: 0, textStyle: { color: t.muted } },
    tooltip: { ...t.tooltip, formatter: (p) => p.seriesIndex === 0
      ? `${dateFmt(p.value[0])}<br><b>EF ${GFT.num(p.value[1], 2)}</b><br>${D.ef_points[p.dataIndex].name}`
      : p.seriesIndex === 1 ? `${p.value[0].slice(0, 7)} : médiane <b>${GFT.num(p.value[1], 2)}</b>`
      : `${p.seriesName}<br>${dateFmt(p.value[0])} : <b>${GFT.num(p.value[1], 2)}</b>` },
    xAxis: { type: "time", ...t.axis },
    yAxis: { type: "value", scale: true, ...t.axis, axisLabel: { ...t.axis.axisLabel, formatter: (v) => GFT.num(v, 2) } },
    series: [
      { name: "Sortie facile et plate", type: "scatter", symbolSize: 6,
        data: D.ef_points.map((p) => [p.date, p.ef]), itemStyle: { color: t.series[1], opacity: 0.55 } },
      { name: "Médiane du mois", type: "line", smooth: 0.3, showSymbol: false, connectNulls: false,
        data: D.ef_monthly.map((m) => [m.month + "-15", m.ef]), lineStyle: { width: 2.5, color: t.accent },
        itemStyle: { color: t.accent } },
      ...[["all", "Tendance depuis le début", t.text], ["12m", "Tendance 12 derniers mois", t.series[2]]]
        .filter(([k]) => D.ef_trend[k])
        .map(([k, name, color]) => ({ name, type: "line", symbol: "circle", symbolSize: 7,
          data: [D.ef_trend[k].start, D.ef_trend[k].end],
          lineStyle: { width: 2, type: "dashed", color }, itemStyle: { color }, z: 5 })),
    ],
  }));

  openOnClick(efChart, D.ef_points);

  // ---------- découplage ----------
  const decChart = GFT.chart("chart-decoupling", (t) => ({
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    tooltip: { ...t.tooltip, formatter: (p) => { const d = D.decoupling[p.dataIndex];
      return `${dateFmt(d.date)}<br><b>${GFT.num(d.pct, 1)} %</b> sur ${GFT.num(d.hours, 1)} h<br>${d.name}`; } },
    xAxis: { type: "time", ...t.axis },
    yAxis: { type: "value", ...t.axis, axisLabel: { ...t.axis.axisLabel, formatter: "{value} %" } },
    visualMap: { show: false, dimension: 1, pieces: [{ lte: 5, color: t.series[2] }, { gt: 5, color: t.accent }] },
    series: [{ type: "scatter", symbolSize: (v) => 5 + Math.min(10, (v[2] || 1) * 3),
      data: D.decoupling.map((d) => [d.date, d.pct, d.hours]),
      markLine: { silent: true, symbol: "none", data: [{ yAxis: 5 }],
        lineStyle: { color: t.text, type: "dashed" },
        label: { formatter: "5 %", color: t.muted, position: "insideEndTop" } } }],
  }));
  openOnClick(decChart, D.decoupling);
})();
