"use strict";

// Survol 3D de la sortie : relief (MapLibre GL), trace colorée selon l'allure, la FC, la pente ou
// l'altitude, caméra qui suit le coureur. Le cap de la caméra est lissé par le serveur (lacets et
// demi-tours sans à-coups) ; ici, la caméra s'incline vers la verticale dès qu'un relief se glisse
// entre elle et le coureur, puis revient doucement.
(() => {
  const card = document.querySelector(".map-card");
  if (!card) return;
  const D = JSON.parse(document.getElementById("page-data").textContent);
  const btn2d = card.querySelector('[data-map-mode="2d"]');
  const btn3d = card.querySelector('[data-map-mode="3d"]');
  const btnFly = card.querySelector("#fly-start");
  const map2d = document.getElementById("map");
  const host = document.getElementById("fly");

  const TERRAIN = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png";
  const ign = (layer, format) => "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER="
    + layer + "&STYLE=normal&TILEMATRIXSET=PM&FORMAT=" + format + "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}";
  const EXAGGERATION = 1.3;
  const VIEWS = {                       // caméra de suivi : inclinaison, zoom, part de l'écran sous le coureur
    follow: { label: "Derrière", pitch: 64, zoom: 15.6, lift: 0.22 },
    drone: { label: "Drone", pitch: 50, zoom: 14.4, lift: 0.12 },
    free: { label: "Libre" },
  };
  const SPEEDS = [0.5, 1, 2, 4, 8];
  const RAMPS = {
    pace: { label: "Allure", colors: ["#3b5bdb", "#1c9ad6", "#20c997", "#fcc419", "#fd7e14", "#e03131"], invert: true },
    hr: { label: "FC", colors: ["#3b5bdb", "#1c9ad6", "#20c997", "#fcc419", "#fd7e14", "#e03131"] },
    grade: { label: "Pente", colors: ["#1971c2", "#74c0fc", "#f1f3f5", "#ffa94d", "#c92a2a"], symmetric: true },
    alt: { label: "Altitude", colors: ["#2b8a3e", "#94d82d", "#ffe066", "#e8590c", "#f8f9fa"] },
  };

  let viewer = null;
  let loading = null;

  // ---------- bascule carte 2D / survol 3D ----------
  function setMode(mode) {
    const is3d = mode === "3d";
    btn2d.setAttribute("aria-pressed", String(!is3d));
    btn3d.setAttribute("aria-pressed", String(is3d));
    map2d.hidden = is3d;
    host.hidden = !is3d;
    if (!is3d) {
      viewer?.pause();
      window.__map?.invalidateSize();
      return Promise.resolve(null);
    }
    if (viewer) { viewer.resize(); return Promise.resolve(viewer); }
    loading ||= open3d().catch((e) => {
      loading = null;
      host.innerHTML = `<p class="fly-error">Survol 3D indisponible : ${e.message}</p>`;
      return null;
    });
    return loading;
  }
  btn2d?.addEventListener("click", () => setMode("2d"));
  btn3d?.addEventListener("click", () => setMode("3d"));
  btnFly?.addEventListener("click", async () => {
    const v = await setMode("3d");
    v?.play();
  });

  const loadCss = (href) => new Promise((ok) => {
    const l = Object.assign(document.createElement("link"), { rel: "stylesheet", href });
    l.onload = ok; l.onerror = ok;
    document.head.appendChild(l);
  });
  const loadJs = (src) => new Promise((ok, ko) => {
    const s = Object.assign(document.createElement("script"), { src });
    s.onload = ok; s.onerror = () => ko(new Error("bibliothèque 3D non chargée"));
    document.head.appendChild(s);
  });

  async function open3d() {
    host.innerHTML = '<div class="fly-loading"><span class="fly-spinner"></span>Préparation du relief…</div>';
    const v = "4.7.1";
    const [r] = await Promise.all([
      fetch(`/sorties/${D.id}/survol`),
      window.maplibregl ? null : Promise.all([loadCss(`/static/vendor/maplibre/maplibre-gl.css?v=${v}`),
                                              loadJs(`/static/vendor/maplibre/maplibre-gl.js?v=${v}`)]),
    ]);
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || data.detail || "trace introuvable");
    viewer = createViewer(data);
    return viewer;
  }

  // ---------- outils ----------
  const lerp = (a, b, u) => a + (b - a) * u;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const hex = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
  const mix = (colors, u) => {
    const x = clamp(u, 0, 1) * (colors.length - 1);
    const i = Math.min(colors.length - 2, Math.floor(x));
    const a = hex(colors[i]), b = hex(colors[i + 1]);
    return "#" + a.map((v, k) => Math.round(lerp(v, b[k], x - i)).toString(16).padStart(2, "0")).join("");
  };
  const quantile = (sorted, q) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.floor(q * sorted.length)))];
  const paceLabel = (s) => `${Math.floor(s / 60)}'${String(Math.round(s % 60)).padStart(2, "0")}"`;
  const chrono = (s) => {
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return (h ? `${h}:${String(m).padStart(2, "0")}` : `${m}`) + `:${String(sec).padStart(2, "0")}`;
  };
  const fr = (v, d = 0) => v.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });

  // résolution du rendu : sans GPU (rendu logiciel), 1 ; sur téléphone, 1,5 au plus (l'écran 3× ne
  // se voit pas en mouvement et coûte quatre fois plus) ; sinon celle de l'écran, 2 au plus
  function renderRatio() {
    const dpr = window.devicePixelRatio || 1;
    try {
      const gl = document.createElement("canvas").getContext("webgl");
      const info = gl && gl.getExtension("WEBGL_debug_renderer_info");
      const name = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : "";
      if (!gl || /swiftshader|llvmpipe|software|basic render/i.test(name)) return 1;
    } catch (e) { return 1; }
    return Math.min(dpr, matchMedia("(pointer: coarse)").matches ? 1.5 : 2);
  }

  function createViewer(T) {
    const n = T.lat.length;
    const km = T.km;
    const totalKm = km[n - 1] || 0.001;
    const hasAlt = T.alt.some((v) => v != null);
    const hasHr = T.hr.some((v) => v != null);
    const inFrance = T.lat[0] > 41 && T.lat[0] < 51.2 && T.lon[0] > -5.3 && T.lon[0] < 9.7;
    // durée du survol à vitesse 1 : 4 s par km, entre 30 s et 1 min 40
    const baseDuration = clamp(totalKm * 4, 30, 100);

    host.innerHTML = `
      <div class="fly-map"></div>
      <div class="fly-vignette"></div>
      <div class="fly-hud fly-stats" aria-live="off">
        <div class="fly-km"><b data-k="km">0,00</b><span>km</span></div>
        <dl>
          <div><dt>Temps</dt><dd data-k="time">0:00</dd></div>
          <div><dt>Allure</dt><dd data-k="pace">—</dd></div>
          ${hasHr ? '<div><dt>FC</dt><dd data-k="hr">—</dd></div>' : ""}
          ${hasAlt ? '<div><dt>Altitude</dt><dd data-k="alt">—</dd></div><div><dt>Pente</dt><dd data-k="grade">—</dd></div>' : ""}
        </dl>
      </div>
      <div class="fly-hud fly-legend"><span data-k="legend-label"></span><i></i><span class="fly-legend-ends"><span data-k="lo"></span><span data-k="hi"></span></span></div>
      <div class="fly-hud fly-bottom">
        <canvas class="fly-profile" aria-label="Profil de la sortie : cliquer pour se placer"></canvas>
        <div class="fly-controls">
          <button type="button" class="fly-btn fly-play" data-act="play" aria-label="Lancer le survol">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path class="i-play" fill="currentColor" d="M7 4.5v15l13-7.5z"/><path class="i-pause" fill="currentColor" d="M6 4h4.5v16H6zm7.5 0H18v16h-4.5z"/></svg>
          </button>
          <button type="button" class="fly-btn" data-act="speed" title="Vitesse du survol">1×</button>
          <span class="fly-sep"></span>
          <div class="fly-group" data-group="view">${Object.entries(VIEWS).map(([k, x]) =>
            `<button type="button" class="fly-chip" data-view="${k}">${x.label}</button>`).join("")}</div>
          <span class="fly-sep"></span>
          <div class="fly-group" data-group="metric">${Object.entries(RAMPS).filter(([k]) =>
            (k !== "hr" || hasHr) && ((k !== "grade" && k !== "alt") || hasAlt)).map(([k, x]) =>
            `<button type="button" class="fly-chip" data-metric="${k}">${x.label}</button>`).join("")}</div>
          <span class="fly-sep"></span>
          <div class="fly-group" data-group="base">
            <button type="button" class="fly-chip" data-base="photo">Photo</button>
            ${inFrance ? '<button type="button" class="fly-chip" data-base="plan">Plan IGN</button>' : ""}
            <button type="button" class="fly-chip" data-base="osm">OSM</button>
          </div>
          <span class="fly-grow"></span>
          <button type="button" class="fly-btn" data-act="zoom-in" aria-label="Rapprocher la caméra">+</button>
          <button type="button" class="fly-btn" data-act="zoom-out" aria-label="Éloigner la caméra">−</button>
          <button type="button" class="fly-btn" data-act="full" aria-label="Plein écran">
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/></svg>
          </button>
        </div>
      </div>`;
    const $ = (sel) => host.querySelector(sel);
    const field = (k) => host.querySelector(`[data-k="${k}"]`);

    // ---------- carte ----------
    const photoTiles = inFrance ? [ign("ORTHOIMAGERY.ORTHOPHOTOS", "image/jpeg")]
      : ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"];
    const map = new maplibregl.Map({
      container: $(".fly-map"),
      pixelRatio: renderRatio(),
      maxPitch: 82,
      attributionControl: { compact: true },
      cooperativeGestures: true,
      locale: {
        "CooperativeGesturesHandler.WindowsHelpText": "Ctrl + molette pour zoomer",
        "CooperativeGesturesHandler.MacHelpText": "⌘ + molette pour zoomer",
        "CooperativeGesturesHandler.MobileHelpText": "Deux doigts pour déplacer la carte",
      },
      style: {
        version: 8,
        sources: {
          photo: { type: "raster", tiles: photoTiles, tileSize: 256, maxzoom: inFrance ? 18 : 19,
                   attribution: inFrance ? "© IGN" : "© contributeurs OpenStreetMap" },
          plan: { type: "raster", tiles: [ign("GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", "image/png")], tileSize: 256,
                  maxzoom: 18, attribution: "© IGN" },
          osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256,
                 maxzoom: 19, attribution: "© contributeurs OpenStreetMap" },
          dem: { type: "raster-dem", tiles: [TERRAIN], tileSize: 256, maxzoom: 15, encoding: "terrarium",
                 attribution: "Relief : Mapzen, AWS Terrain Tiles" },
          shade: { type: "raster-dem", tiles: [TERRAIN], tileSize: 256, maxzoom: 15, encoding: "terrarium" },
        },
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#1d2228" } },
          { id: "photo", type: "raster", source: "photo", paint: { "raster-fade-duration": 200 } },
          { id: "plan", type: "raster", source: "plan", layout: { visibility: "none" } },
          { id: "osm", type: "raster", source: "osm", layout: { visibility: "none" } },
          { id: "shade", type: "hillshade", source: "shade", layout: { visibility: "none" },
            paint: { "hillshade-exaggeration": 0.35, "hillshade-shadow-color": "#2b2f36" } },
        ],
        terrain: { source: "dem", exaggeration: EXAGGERATION },
        sky: {
          "sky-color": "#6fa8dc", "horizon-color": "#dbe9f6", "fog-color": "#e8eef5",
          "sky-horizon-blend": 0.6, "horizon-fog-blend": 0.7, "fog-ground-blend": 0.75, "atmosphere-blend": 0.9,
        },
      },
      bounds: bounds(), fitBoundsOptions: { padding: 40, pitch: 0 },
    });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true, showZoom: false }), "top-right");

    function bounds() {
      let w = 180, s = 90, e = -180, nn = -90;
      for (let i = 0; i < n; i++) {
        w = Math.min(w, T.lon[i]); e = Math.max(e, T.lon[i]);
        s = Math.min(s, T.lat[i]); nn = Math.max(nn, T.lat[i]);
      }
      return [[w, s], [e, nn]];
    }
    const coords = T.lat.map((la, i) => [T.lon[i], la]);

    // ---------- couleurs de la trace ----------
    const ramps = {};
    function rampFor(metric) {
      if (!(metric in ramps)) ramps[metric] = buildRamp(metric);
      return ramps[metric];
    }
    function buildRamp(metric) {
      const conf = RAMPS[metric];
      const values = T[metric];
      const sorted = values.filter((v) => v != null).sort((a, b) => a - b);
      if (!sorted.length) return null;
      let lo = quantile(sorted, 0.05), hi = quantile(sorted, 0.95);
      if (conf.symmetric) { const m = Math.max(Math.abs(lo), Math.abs(hi), 5); lo = -m; hi = m; }
      if (hi - lo < 1e-6) hi = lo + 1;
      const color = (v) => mix(conf.colors, conf.invert ? (hi - v) / (hi - lo) : (v - lo) / (hi - lo));
      return { conf, lo, hi, color, metric };
    }
    const stopCache = {};
    function colorStops(ramp) {
      if (stopCache[ramp.metric]) return stopCache[ramp.metric];
      const stops = Math.min(n, 240);
      const out = [];
      let last = null;
      for (let k = 0; k < stops; k++) {
        const i = Math.round((k / (stops - 1)) * (n - 1));
        // moyenne sur le tronçon : couleur stable, pas de clignotement
        const a = Math.max(0, i - Math.ceil(n / stops / 2)), b = Math.min(n - 1, i + Math.ceil(n / stops / 2));
        let sum = 0, cnt = 0;
        for (let j = a; j <= b; j++) if (T[ramp.metric][j] != null) { sum += T[ramp.metric][j]; cnt++; }
        const v = cnt ? sum / cnt : last;
        if (v != null) last = v;
        out.push([k / (stops - 1), v == null ? "#ffffff" : ramp.color(v)]);
      }
      return (stopCache[ramp.metric] = out);
    }
    // dégradé de la trace, dessinée jusqu'à la fraction upTo de sa longueur (le reste transparent)
    const NONE = "rgba(0,0,0,0)";
    function gradientExpr(stops, upTo = 1) {
      const expr = ["interpolate", ["linear"], ["line-progress"]];
      if (upTo >= 1) { stops.forEach(([p, c]) => expr.push(p, c)); return expr; }
      const cut = Math.max(upTo, 1e-4);
      let i = 0;
      for (; i < stops.length && stops[i][0] < cut; i++) expr.push(stops[i][0], stops[i][1]);
      const c = stops[Math.min(i, stops.length - 1)][1];
      expr.push(cut, c);
      if (cut + 1e-4 < 1) expr.push(cut + 1e-4, NONE, 1, NONE);
      return expr;
    }
    let revealed = 1;               // part de la trace affichée (1 : toute)
    function setReveal(upTo) {
      const ramp = rampFor(metric);
      if (!ramp || !map.getLayer("track")) return;
      revealed = upTo;
      map.setPaintProperty("track", "line-gradient", gradientExpr(colorStops(ramp), upTo));
      map.setPaintProperty("track-shadow", "line-gradient",
                           gradientExpr([[0, "#000000"], [1, "#000000"]], upTo));
      endPin?.getElement().classList.toggle("is-hidden", upTo < 0.999);
    }
    const fmtMetric = { pace: paceLabel, hr: (v) => `${Math.round(v)}`, grade: (v) => `${v > 0 ? "+" : ""}${Math.round(v)} %`,
                        alt: (v) => `${fr(v)} m` };
    let metric = "pace";
    function setMetric(m) {
      const ramp = rampFor(m);
      if (!ramp) return;
      metric = m;
      setReveal(revealed);
      field("legend-label").textContent = ramp.conf.label;
      $(".fly-legend i").style.background = `linear-gradient(90deg, ${ramp.conf.colors.join(",")})`;
      const [lo, hi] = ramp.conf.invert ? [ramp.hi, ramp.lo] : [ramp.lo, ramp.hi];
      field("lo").textContent = fmtMetric[m](lo);
      field("hi").textContent = fmtMetric[m](hi);
      host.querySelectorAll("[data-metric]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.metric === m)));
      drawProfile();
    }

    function setBase(b) {
      ["photo", "plan", "osm"].forEach((id) => map.setLayoutProperty(id, "visibility", id === b ? "visible" : "none"));
      map.setLayoutProperty("shade", "visibility", b === "photo" ? "none" : "visible");
      host.querySelectorAll("[data-base]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.base === b)));
    }

    // ---------- marqueurs ----------
    const pin = (cls, title) => {
      const el = document.createElement("div");
      el.className = `fly-pin ${cls}`;
      el.title = title;
      return el;
    };
    const runnerEl = document.createElement("div");
    runnerEl.className = "fly-runner";
    runnerEl.innerHTML = "<i></i><b></b>";
    let runner = null, endPin = null;

    map.on("load", () => {
      map.addSource("track", { type: "geojson", lineMetrics: true,
        data: { type: "Feature", geometry: { type: "LineString", coordinates: coords } } });
      map.addSource("comet", { type: "geojson", lineMetrics: true,
        data: { type: "Feature", geometry: { type: "LineString", coordinates: coords.slice(0, 2) } } });
      map.addLayer({ id: "track-shadow", type: "line", source: "track",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-gradient": "#000", "line-opacity": 0.45, "line-width": ["interpolate", ["linear"], ["zoom"], 10, 4, 16, 10],
                 "line-blur": 3 } });
      map.addLayer({ id: "track", type: "line", source: "track",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-width": ["interpolate", ["linear"], ["zoom"], 10, 2.5, 16, 6], "line-gradient": "#fff" } });
      map.addLayer({ id: "comet-glow", type: "line", source: "comet",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#fff", "line-width": ["interpolate", ["linear"], ["zoom"], 10, 8, 16, 18], "line-blur": 8,
                 "line-gradient": ["interpolate", ["linear"], ["line-progress"], 0, "rgba(255,255,255,0)", 1, "rgba(255,255,255,0.75)"] } });
      map.addLayer({ id: "comet", type: "line", source: "comet",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-width": ["interpolate", ["linear"], ["zoom"], 10, 2, 16, 4],
                 "line-gradient": ["interpolate", ["linear"], ["line-progress"], 0, "rgba(255,255,255,0)", 1, "#ffffff"] } });
      new maplibregl.Marker({ element: pin("fly-start", "Départ"), opacityWhenCovered: "0.4" }).setLngLat(coords[0]).addTo(map);
      endPin = new maplibregl.Marker({ element: pin("fly-end", "Arrivée"), opacityWhenCovered: "0.4" }).setLngLat(coords[n - 1]).addTo(map);
      runner = new maplibregl.Marker({ element: runnerEl, opacityWhenCovered: "0.7" }).setLngLat(coords[0]).addTo(map);
      setMetric(metric);
      setBase(inFrance ? "photo" : "osm");
      // présentation : la trace entière, inclinée
      map.fitBounds(bounds(), { padding: { top: 60, bottom: 140, left: 40, right: 40 }, pitch: 55,
                                bearing: -20, duration: 2200, essential: true });
      update(true);
    });

    // ---------- état du survol ----------
    let f = 0;                   // position : indice (fractionnaire) dans la trace
    let playing = false;
    let speedIdx = 1;
    let view = "follow";
    let zoomOffset = 0;
    let attached = false;        // la caméra suit le coureur
    let camPitch = VIEWS.follow.pitch;
    let camBearing = 0;
    let lastT = null;
    let raf = null;
    let transition = false;

    const at = (arr, x) => {
      const i = Math.min(n - 2, Math.floor(x)), u = x - i;
      const a = arr[i], b = arr[i + 1];
      if (a == null || b == null) return a ?? b;
      return lerp(a, b, u);
    };
    const posAt = (x) => [at(T.lon, x), at(T.lat, x)];

    // ---------- relief entre la caméra et le coureur ----------
    function clearPitch(center, bearing, wanted, zoom) {
      if (!map.terrain) return wanted;
      const cam = map.transform.cameraToCenterDistance || map.getCanvas().clientHeight * 1.5;
      const mpp = 40075016.686 * Math.cos(center[1] * Math.PI / 180) / (512 * 2 ** zoom);
      const dist = cam * mpp;                                  // distance caméra-coureur (m)
      const q = (lng, lat) => map.queryTerrainElevation([lng, lat]);
      const base = q(center[0], center[1]);
      if (base == null) return wanted;
      const ahead = posAt(Math.min(n - 1, f + 250 / T.step_m));
      const baseAhead = q(ahead[0], ahead[1]) ?? base;
      const rad = bearing * Math.PI / 180;
      const mLat = 1 / 111195, mLng = mLat / Math.cos(center[1] * Math.PI / 180);
      const dLng = -Math.sin(rad) * mLng, dLat = -Math.cos(rad) * mLat;          // vers l'arrière
      const margin = 25 * EXAGGERATION;
      for (let p = wanted; p >= 12; p -= 6) {
        const back = dist * Math.sin(p * Math.PI / 180), up = dist * Math.cos(p * Math.PI / 180);
        const camLng = center[0] + dLng * back, camLat = center[1] + dLat * back, camAlt = base + up;
        let blocked = false;
        for (let k = 1; k <= 8 && !blocked; k++) {
          const u = k / 8;
          // vers le coureur
          const e1 = q(lerp(center[0], camLng, u), lerp(center[1], camLat, u));
          if (e1 != null && e1 > lerp(base, camAlt, u) - margin * Math.min(1, u * 3)) blocked = true;
          // vers la trace 250 m plus loin
          const e2 = q(lerp(ahead[0], camLng, u), lerp(ahead[1], camLat, u));
          if (u < 1 && e2 != null && e2 > lerp(baseAhead, camAlt, u) - margin * Math.min(1, u * 3)) blocked = true;
        }
        if (!blocked) return p;
      }
      return 12;
    }

    let pitchCheckedAt = 0, pitchWanted = VIEWS.follow.pitch;
    function cameraFor(x, dt) {
      const v = VIEWS[view];
      const center = posAt(x);
      const zoom = v.zoom + zoomOffset;
      const targetBearing = at(T.heading, x);
      const k = dt == null ? 1 : 1 - Math.exp(-dt / 0.6);
      camBearing = dt == null ? targetBearing : camBearing + (targetBearing - camBearing) * k;
      // le relief n'est testé que 6 fois par seconde : la caméra s'y ajuste en douceur
      const now = performance.now();
      if (dt == null || now - pitchCheckedAt > 160) {
        pitchCheckedAt = now;
        pitchWanted = clearPitch(center, camBearing, v.pitch, zoom);
      }
      const wanted = pitchWanted;
      // s'incliner vite quand le relief masque, revenir lentement
      const tau = wanted < camPitch ? 0.25 : 1.6;
      camPitch = dt == null ? wanted : camPitch + (wanted - camPitch) * (1 - Math.exp(-dt / tau));
      const h = map.getCanvas().clientHeight;
      return { center, zoom, bearing: camBearing % 360, pitch: camPitch, padding: { top: h * v.lift, bottom: 0, left: 0, right: 0 } };
    }

    // ---------- affichage ----------
    let lastReveal = 0, lastHud = 0, cometAt = -1, cometTime = 0;
    function update(force) {
      const pos = posAt(f);
      runner?.setLngLat(pos);
      const now = performance.now();
      if (force || Math.floor(f) !== cometAt || now - cometTime > 120) {
        cometAt = Math.floor(f);
        cometTime = now;
        const tail = Math.max(0, f - 300 / T.step_m);
        const pts = [];
        for (let i = Math.ceil(tail); i < f; i++) pts.push(coords[i]);
        pts.push(pos);
        if (pts.length < 2) pts.unshift(coords[0]);
        map.getSource("comet")?.setData({ type: "Feature", geometry: { type: "LineString", coordinates: pts } });
      }
      if (revealed < 1 && (force || now - lastReveal > 100)) { lastReveal = now; setReveal(f / (n - 1)); }
      if (force || now - lastHud > 120) {
        lastHud = now;
        field("km").textContent = fr(at(km, f), 2);
        field("time").textContent = chrono(at(T.time_s, f));
        const pc = at(T.pace, f);
        field("pace").textContent = pc ? `${paceLabel(pc)} /km` : "—";
        if (hasHr) { const h = at(T.hr, f); field("hr").textContent = h ? `${Math.round(h)} bpm` : "—"; }
        if (hasAlt) {
          const a = at(T.alt, f), g = at(T.grade, f);
          field("alt").textContent = a != null ? `${fr(a)} m` : "—";
          field("grade").textContent = g != null ? `${g > 0.5 ? "+" : ""}${fr(g, 0)} %` : "—";
          field("grade").dataset.sign = g > 3 ? "up" : g < -3 ? "down" : "";
        }
        drawProfile();
      }
    }

    function frame(t) {
      raf = null;
      // la progression suit l'horloge, même si l'affichage saccade (appareil lent)
      const dt = lastT == null ? 0.016 : Math.min(1, (t - lastT) / 1000);
      lastT = t;
      // une animation de MapLibre interrompue (easeTo, fitBounds) peut laisser l'altitude du centre
      // figée : le coureur serait alors dessiné hors du cadre. En suivi, elle doit suivre le sol.
      if ((attached || transition) && map._elevationFreeze) map._elevationFreeze = false;
      if (transition) {
        // vol d'approche jusqu'à la caméra de suivi, interpolé ici (jumpTo, sans gel de l'altitude)
        const u = clamp((t - transition.start) / transition.duration, 0, 1);
        const e = u * u * (3 - 2 * u);
        const to = cameraFor(f, null);
        const a = transition.from;
        let db = ((to.bearing - a.bearing) % 360 + 540) % 360 - 180;          // plus court chemin
        map.jumpTo({ center: [lerp(a.center[0], to.center[0], e), lerp(a.center[1], to.center[1], e)],
                     zoom: lerp(a.zoom, to.zoom, e), bearing: a.bearing + db * e, pitch: lerp(a.pitch, to.pitch, e),
                     padding: { top: lerp(a.top, to.padding.top, e), bottom: 0, left: 0, right: 0 } });
        if (u >= 1) { transition = false; attached = true; camBearing = at(T.heading, f); }
      } else if (playing) {
        f = Math.min(n - 1, f + dt * (n - 1) / baseDuration * SPEEDS[speedIdx]);
        if (f >= n - 1) finish();
      }
      if (attached && !transition && view !== "free") map.jumpTo(cameraFor(Math.min(f, n - 1), Math.min(dt, 0.1)));
      update(false);
      if (playing || transition) raf = requestAnimationFrame(frame);
    }
    const kick = () => { if (!raf) { lastT = null; raf = requestAnimationFrame(frame); } };

    function attach() {
      if (view === "free") { attached = false; return; }
      map.stop();
      const c = map.getCenter();
      transition = { start: performance.now(), duration: 1800,
                     from: { center: [c.lng, c.lat], zoom: map.getZoom(), bearing: map.getBearing(),
                             pitch: map.getPitch(), top: map.getPadding().top || 0 } };
      kick();
    }

    function play() {
      if (f >= n - 1) f = 0;
      // la trace se dévoile au fil du survol
      const beginReveal = () => { if (revealed >= 1) setReveal(Math.max(f / (n - 1), 1e-4)); };
      if (map.getLayer("track")) beginReveal();
      playing = true;
      host.classList.add("is-playing");
      $(".fly-play").setAttribute("aria-label", "Mettre en pause");
      if (!map.loaded() && !map.getSource("track")) { map.once("load", () => { beginReveal(); attach(); }); return; }
      if (view !== "free" && !attached) attach();
      kick();
    }
    function pause() {
      playing = false;
      host.classList.remove("is-playing");
      $(".fly-play").setAttribute("aria-label", "Lancer le survol");
    }
    function finish() {
      pause();
      attached = false;
      setReveal(1);
      setTimeout(() => map.fitBounds(bounds(), { padding: { top: 60, bottom: 140, left: 40, right: 40 }, pitch: 50,
                                                bearing: map.getBearing(), duration: 2600, essential: true }), 600);
    }
    function seek(x) {
      f = clamp(x, 0, n - 1);
      if (attached && view !== "free") { camBearing = at(T.heading, f); map.jumpTo(cameraFor(f, null)); }
      update(true);
    }

    function setView(v) {
      view = v;
      host.querySelectorAll("[data-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === v)));
      if (v === "free") { attached = false; map.easeTo({ padding: { top: 0, bottom: 0, left: 0, right: 0 }, duration: 600 }); }
      else if (playing || attached) attach();
    }

    // une interaction à la souris pendant le suivi : passage en vue libre
    map.on("dragstart", (e) => { if (e.originalEvent && attached) setView("free"); });
    map.on("rotatestart", (e) => { if (e.originalEvent && attached) setView("free"); });
    // en suivi, la molette (avec Ctrl, ou seule en plein écran) rapproche ou éloigne la caméra
    let wheelSum = 0;
    map.getContainer().addEventListener("wheel", (e) => {
      if (!attached || view === "free") return;
      const full = document.fullscreenElement === host || host.classList.contains("fly-max");
      if (!full && !e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      e.stopPropagation();
      wheelSum += e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
      if (Math.abs(wheelSum) < 40) return;
      zoomOffset = clamp(zoomOffset + (wheelSum < 0 ? 0.25 : -0.25), -3, 2);
      wheelSum = 0;
      if (!playing) map.jumpTo(cameraFor(f, null));
    }, { passive: false, capture: true });

    // ---------- profil (bas de l'écran) ----------
    const canvas = $(".fly-profile");
    const ctx = canvas.getContext("2d");
    const altVals = hasAlt ? T.alt : null;
    let altMin = 0, altMax = 1;
    if (altVals) {
      const a = altVals.filter((v) => v != null);
      altMin = Math.min(...a); altMax = Math.max(...a);
      if (altMax - altMin < 20) { altMax += 10; altMin -= 10; }
    }
    // deux images du profil (estompée et vive) calculées une fois par taille et par mesure ;
    // à chaque mise à jour, seuls la partie parcourue et le curseur sont recopiés
    let layers = null;
    function profileLayers(w, h, dpr) {
      const key = `${w}x${h}x${dpr}x${metric}`;
      if (layers?.key === key) return layers;
      const X = (i) => (km[i] / totalKm) * w;
      const Y = (v) => altVals ? h - 4 - ((v - altMin) / (altMax - altMin)) * (h - 10) : h * 0.6;
      const ramp = rampFor(metric);
      const step = Math.max(1, Math.floor(n / (w * 1.5)));
      const make = (alpha) => {
        const c = document.createElement("canvas");
        c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
        const g = c.getContext("2d");
        g.setTransform(dpr, 0, 0, dpr, 0, 0);
        const grad = g.createLinearGradient(0, 0, w, 0);
        if (ramp) {
          for (let k = 0; k <= 60; k++) {
            const i = Math.round(k / 60 * (n - 1));
            const v = T[metric][i];
            if (v != null) grad.addColorStop(km[i] / totalKm, ramp.color(v));
          }
        }
        g.beginPath(); g.moveTo(0, h);
        let last = altVals ? altVals.find((v) => v != null) : 0;
        for (let i = 0; i < n; i += step) { const v = altVals ? (altVals[i] ?? last) : 0; last = v; g.lineTo(X(i), Y(v)); }
        g.lineTo(w, h); g.closePath();
        g.globalAlpha = alpha; g.fillStyle = ramp ? grad : "#fff"; g.fill();
        g.globalAlpha = 1;
        if (altVals) {
          g.beginPath();
          last = altVals.find((v) => v != null);
          for (let i = 0; i < n; i += step) { const v = altVals[i] ?? last; last = v; i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v)); }
          g.strokeStyle = "rgba(255,255,255,0.8)"; g.lineWidth = 1.2; g.stroke();
        }
        return c;
      };
      layers = { key, dim: make(0.28), bright: make(0.85), Y };
      return layers;
    }
    function drawProfile() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (!w || !h) return;
      if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
      const L = profileLayers(w, h, dpr);
      const Y = L.Y;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(L.dim, 0, 0);
      const xf = (at(km, f) / totalKm) * w;
      const xs = Math.max(1, Math.round(xf * dpr));
      ctx.drawImage(L.bright, 0, 0, xs, canvas.height, 0, 0, xs, canvas.height);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // curseur
      ctx.fillStyle = "#fff";
      ctx.fillRect(xf - 1, 0, 2, h);
      const yv = altVals ? Y(at(altVals, f) ?? altMin) : h * 0.6;
      ctx.beginPath(); ctx.arc(xf, yv, 4.5, 0, Math.PI * 2); ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = "rgba(0,0,0,0.35)"; ctx.stroke();
    }
    const kmToIndex = (k) => {
      let lo = 0, hi = n - 1;
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if (km[m] < k) lo = m; else hi = m; }
      const span = km[hi] - km[lo];
      return lo + (span > 0 ? clamp((k - km[lo]) / span, 0, 1) : 0);
    };
    let scrubbing = false;
    const scrubTo = (e) => {
      const r = canvas.getBoundingClientRect();
      seek(kmToIndex(clamp((e.clientX - r.left) / r.width, 0, 1) * totalKm));
    };
    canvas.addEventListener("pointerdown", (e) => { scrubbing = true; canvas.setPointerCapture(e.pointerId); scrubTo(e); });
    canvas.addEventListener("pointermove", (e) => { if (scrubbing) scrubTo(e); });
    canvas.addEventListener("pointerup", () => { scrubbing = false; });

    // survol du profil de la page : position du coureur (hors lecture)
    document.addEventListener("profile-hover", (e) => { if (!playing && e.detail?.km != null) seek(kmToIndex(e.detail.km)); });

    // ---------- commandes ----------
    host.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b || !host.contains(b)) return;
      if (b.dataset.view) setView(b.dataset.view);
      else if (b.dataset.metric) setMetric(b.dataset.metric);
      else if (b.dataset.base) setBase(b.dataset.base);
      else if (b.dataset.act === "play") (playing ? pause : play)();
      else if (b.dataset.act === "speed") {
        speedIdx = (speedIdx + 1) % SPEEDS.length;
        b.textContent = `${fr(SPEEDS[speedIdx], SPEEDS[speedIdx] < 1 ? 1 : 0)}×`;
      } else if (b.dataset.act === "zoom-in" || b.dataset.act === "zoom-out") {
        const d = b.dataset.act === "zoom-in" ? 0.5 : -0.5;
        if (view === "free" || !attached) map.easeTo({ zoom: map.getZoom() + d, duration: 300 });
        else { zoomOffset = clamp(zoomOffset + d, -3, 2); if (!playing) map.jumpTo(cameraFor(f, null)); }
      } else if (b.dataset.act === "full") toggleFull();
    });
    host.tabIndex = 0;
    host.addEventListener("keydown", (e) => {
      if (e.key === " ") { e.preventDefault(); (playing ? pause : play)(); }
      else if (e.key === "ArrowRight") seek(f + 500 / T.step_m);
      else if (e.key === "ArrowLeft") seek(f - 500 / T.step_m);
      else if (e.key === "Escape" && host.classList.contains("fly-max")) toggleFull();
    });

    function toggleFull() {
      const native = document.fullscreenElement === host;
      if (native) { document.exitFullscreen(); return; }
      if (host.classList.contains("fly-max")) { host.classList.remove("fly-max"); document.body.classList.remove("fly-lock"); }
      else if (host.requestFullscreen) host.requestFullscreen().catch(() => maximize());
      else maximize();
      setTimeout(resize, 120);
    }
    function maximize() { host.classList.add("fly-max"); document.body.classList.add("fly-lock"); setTimeout(resize, 50); }
    // plein écran : la molette zoome sans Ctrl
    document.addEventListener("fullscreenchange", () => {
      const full = document.fullscreenElement === host;
      full ? map.cooperativeGestures.disable() : map.cooperativeGestures.enable();
      setTimeout(resize, 60);
    });
    function resize() { map.resize(); drawProfile(); }
    new ResizeObserver(() => resize()).observe(host);

    setView("follow");
    return { play, pause, resize };
  }
})();
