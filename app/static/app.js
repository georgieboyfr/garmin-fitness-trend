"use strict";

// Fonctions communes aux pages de statistiques : thème, formats, info-bulles, graphiques.
const GFT = (() => {
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  // ---------- formats (français) ----------
  const num = (v, dec = 0) => Number(v).toLocaleString("fr-FR", {
    minimumFractionDigits: dec, maximumFractionDigits: dec,
  });
  const duration = (s) => {
    s = Math.round(s || 0);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h ? `${h} h ${String(m).padStart(2, "0")}` : `${m} min ${String(s % 60).padStart(2, "0")}`;
  };
  // temps de course au format chronomètre : 44:57, 1:37:08
  const chrono = (sec) => {
    const s = Math.round(sec), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    const ss = String(s % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
  };
  const pace = (sPerKm) => {
    const s = Math.round(sPerKm);
    return `${Math.floor(s / 60)}'${String(s % 60).padStart(2, "0")}" /km`;
  };
  const dateLong = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("fr-FR", {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });
  const dayDate = (year, i) => new Date(year, 0, 1 + i);
  const dayLabel = (year, i) => dayDate(year, i).toLocaleDateString("fr-FR", { day: "numeric", month: "long" });
  const isMonthStart = (year, i) => dayDate(year, i).getDate() === 1;
  const monthLabel = (year, i) => dayDate(year, i).toLocaleDateString("fr-FR", { month: "short" });

  function formatPage(root = document) {
    root.querySelectorAll("[data-num]").forEach((el) => {
      const unit = el.dataset.unit ? ` ${el.dataset.unit}` : "";
      el.textContent = num(el.dataset.num, Number(el.dataset.dec || 0)) + unit;
    });
    root.querySelectorAll("[data-duration]").forEach((el) => { el.textContent = duration(el.dataset.duration); });
    root.querySelectorAll("[data-date]").forEach((el) => { el.textContent = dateLong(el.dataset.date); });
    root.querySelectorAll("[data-pace]").forEach((el) => { el.textContent = pace(el.dataset.pace); });
    root.querySelectorAll("[data-chrono]").forEach((el) => { el.textContent = chrono(el.dataset.chrono); });
    root.querySelectorAll("[data-datetime]").forEach((el) => {
      const d = new Date(el.dataset.datetime);
      el.textContent = d.toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
      el.title = d.toLocaleString("fr-FR", { dateStyle: "full", timeStyle: "short" });
    });
    root.querySelectorAll("[data-datetime-long]").forEach((el) => {
      el.textContent = new Date(el.dataset.datetimeLong).toLocaleString("fr-FR", {
        weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });
    });
    root.querySelectorAll("[data-short-date]").forEach((el) => {
      el.textContent = new Date(el.dataset.shortDate + "T12:00:00").toLocaleDateString("fr-FR", {
        day: "numeric", month: "short", year: "numeric" });
    });
  }

  // ---------- thème : automatique, clair ou sombre ----------
  const THEMES = ["auto", "light", "dark"];
  const ICONS = { auto: "◐", light: "☀", dark: "☾" };
  const LABELS = { auto: "Thème automatique", light: "Thème clair", dark: "Thème sombre" };
  const charts = [];

  function currentTheme() {
    return document.documentElement.dataset.theme || "auto";
  }

  function setTheme(t) {
    if (t === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = t;
    try { t === "auto" ? localStorage.removeItem("theme") : localStorage.setItem("theme", t); } catch (e) { /* navigation privée */ }
    const btn = document.getElementById("theme-btn");
    if (btn) { btn.textContent = ICONS[t]; btn.title = LABELS[t]; }
    charts.forEach((c) => c.render());
  }

  // ---------- info-bulles (survol sur ordinateur, appui sur mobile) ----------
  let openTip = null;
  function closeTip() {
    if (!openTip) return;
    openTip.btn.setAttribute("aria-expanded", "false");
    openTip.pop.remove();
    openTip = null;
  }
  function showTip(btn) {
    closeTip();
    const pop = document.createElement("div");
    pop.className = "tip-pop";
    pop.setAttribute("role", "tooltip");
    pop.textContent = btn.dataset.tip;
    document.body.append(pop);
    const r = btn.getBoundingClientRect();
    const left = Math.min(Math.max(16, r.left + window.scrollX - 12), window.scrollX + window.innerWidth - pop.offsetWidth - 16);
    pop.style.left = `${left}px`;
    pop.style.top = `${r.bottom + window.scrollY + 8}px`;
    btn.setAttribute("aria-expanded", "true");
    openTip = { btn, pop };
  }
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".tip");
    if (btn) { e.preventDefault(); openTip && openTip.btn === btn ? closeTip() : showTip(btn); }
    else closeTip();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeTip(); });

  // ---------- graphiques ECharts aux couleurs du thème ----------
  function palette() {
    const t = {
      text: css("--text"), muted: css("--muted"), grid: css("--grid"), surface: css("--surface"),
      border: css("--border"), accent: css("--accent"), accentSoft: css("--accent-soft"),
      series: [css("--accent"), css("--series-2"), css("--series-3"), css("--series-4"), css("--series-5"),
               css("--series-6"), css("--series-7"), css("--series-8")],
    };
    // une couleur fixe par année, la même sur toutes les pages (2026 = couleur d'accent)
    t.year = (y) => t.series[(((Number(y) - 2026) % 8) + 8) % 8];
    t.axis = {
      axisLine: { lineStyle: { color: t.border } },
      axisTick: { show: false },
      axisLabel: { color: t.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: t.grid } },
    };
    t.tooltip = {
      backgroundColor: t.surface, borderColor: t.border, textStyle: { color: t.text, fontSize: 13 },
      extraCssText: "box-shadow: 0 6px 20px rgba(0,0,0,.15); border-radius: 9px;",
    };
    return t;
  }

  function chart(id, buildOption) {
    const el = document.getElementById(id);
    if (!el || !window.echarts) return null;
    const instance = echarts.init(el, null, { renderer: "canvas" });
    const c = {
      instance,
      render() {
        instance.setOption({ textStyle: { fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif" },
                             animationDuration: 500, ...buildOption(palette()) }, true);
      },
    };
    c.render();
    charts.push(c);
    return c;
  }
  window.addEventListener("resize", () => charts.forEach((c) => c.instance.resize()));
  // le thème automatique suit celui du système
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (currentTheme() === "auto") charts.forEach((c) => c.render());
  });

  document.addEventListener("DOMContentLoaded", () => {
    formatPage();
    const btn = document.getElementById("theme-btn");
    setTheme(currentTheme());
    btn?.addEventListener("click", () => setTheme(THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length]));
  });

  return { num, duration, chrono, pace, dateLong, dayLabel, isMonthStart, monthLabel, formatPage, chart, palette };
})();
