"use strict";

// Page Performance : courbe allure-durée et VAM par année.
(() => {
  const D = JSON.parse(document.getElementById("page-data").textContent);
  const paceLabel = (s) => `${Math.floor(s / 60)}'${String(Math.round(s % 60)).padStart(2, "0")}"`;

  GFT.chart("chart-curve", (t) => {
    const years = Object.keys(D.curve).sort();
    return {
      grid: { left: 8, right: 16, top: 40, bottom: 8, containLabel: true },
      legend: { top: 0, left: 0, type: "scroll", textStyle: { color: t.muted } },
      tooltip: {
        trigger: "axis", ...t.tooltip,
        formatter: (ps) => `${ps[0].axisValue}<br>` + ps.filter((p) => p.value != null)
          .sort((a, b) => a.value - b.value)
          .map((p) => `${p.marker} ${p.seriesName} : <b>${paceLabel(p.value)} /km</b>`).join("<br>"),
      },
      xAxis: { type: "category", data: D.duration_labels, boundaryGap: false, ...t.axis },
      yAxis: {
        type: "value", inverse: true, scale: true, ...t.axis,
        axisLabel: { ...t.axis.axisLabel, formatter: (v) => paceLabel(v) },
      },
      series: years.map((y, i) => ({
        name: y, type: "line", data: D.curve[y], connectNulls: true, symbolSize: 6,
        lineStyle: { width: i === years.length - 1 ? 3 : 1.8, color: t.year(y) }, itemStyle: { color: t.year(y) },
        emphasis: { focus: "series" },
      })),
    };
  });

  GFT.chart("chart-vam", (t) => ({
    grid: { left: 8, right: 8, top: 16, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "axis", ...t.tooltip,
      formatter: (ps) => {
        const v = D.vam[ps[0].dataIndex];
        return `${v.year} : <b>${GFT.num(v.vam)} m/h</b><br>sur ${GFT.num(v.gain)} m de D+<br>${v.name}`;
      },
    },
    xAxis: { type: "category", data: D.vam.map((v) => String(v.year)), ...t.axis },
    yAxis: { type: "value", ...t.axis, axisLabel: { ...t.axis.axisLabel, formatter: (v) => `${GFT.num(v)} m/h` } },
    series: [{
      type: "bar", barMaxWidth: 46,
      data: D.vam.map((v) => ({ value: v.vam, itemStyle: { color: t.year(v.year), borderRadius: [4, 4, 0, 0] } })),
      label: { show: true, position: "top", color: t.muted, fontSize: 11, formatter: (p) => GFT.num(p.value) },
    }],
  }));

  const t = GFT.palette();
  document.querySelectorAll(".year-dot").forEach((el) => { el.style.background = t.year(el.dataset.year); });
})();
