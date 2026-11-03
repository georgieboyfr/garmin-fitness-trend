"""
Pages de statistiques (templates Jinja + ECharts), protégées par la session de l'admin.

Les données de chaque page sont calculées côté serveur et insérées dans la page en JSON :
pas d'appel d'API supplémentaire, et rien à mettre en cache côté navigateur.
"""
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import __version__, courses, db, detail, estimator, metrics_job, queries, settings, stats, trail
from .auth import SESSION_COOKIE
from .track_parser import parse_route

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")

# (chemin, libellé, prête) : les pages pas encore prêtes n'apparaissent pas dans le menu
PAGES = [
    ("/", "Accueil", True),
    ("/volume", "Volume", True),
    ("/sorties", "Sorties", True),
    ("/performance", "Performance", True),
    ("/forme", "Forme", True),
    ("/courses", "Courses", True),
    ("/estimateur", "Estimateur", True),
]

router = APIRouter(include_in_schema=False)


def _today(request: Request):
    return datetime.now(ZoneInfo(request.app.state.config.timezone)).date()


def _login_redirect(request: Request):
    """None si la session est valide, sinon la redirection vers la connexion."""
    if request.app.state.auth.check_session(request.cookies.get(SESSION_COOKIE)):
        return None
    return RedirectResponse(f"/admin?next={quote(request.url.path)}", status_code=303)


def render(request: Request, template: str, active: str, **context):
    return TEMPLATES.TemplateResponse(request, template, {
        "version": __version__,
        "nav": [(path, label) for path, label, ready in PAGES if ready],
        "active": active,
        **context,
    })


@router.get("/")
def home(request: Request):
    if (redirect := _login_redirect(request)):
        return redirect
    conn = db.connect(request.app.state.config.db_path)
    try:
        acts = queries.running_activities(conn)
    finally:
        conn.close()
    return render(request, "home.html", "/", data=stats.home(acts, _today(request)))


def _activities(request: Request):
    conn = db.connect(request.app.state.config.db_path)
    try:
        return queries.running_activities(conn)
    finally:
        conn.close()


@router.get("/volume")
def volume(request: Request, terrain: str = "all"):
    if (redirect := _login_redirect(request)):
        return redirect
    if terrain not in stats.TERRAINS:
        terrain = "all"
    acts = stats.filter_terrain(_activities(request), terrain)
    return render(request, "volume.html", "/volume", data=stats.volume(acts, _today(request)),
                  terrain=terrain, terrains=stats.TERRAINS)


PER_PAGE_COOKIE = "per_page"


def _number(value: str):
    """Borne d'un curseur : nombre positif, ou None (curseur en bout de course, pas de filtre)."""
    try:
        v = float(value.replace(",", "."))
    except ValueError:
        return None
    return v if v >= 0 and math.isfinite(v) else None


@router.get("/sorties")
def sorties(request: Request, page: int = 1, year: str = "", terrain: str = "all",
            sort: str = "date", order: str = "desc", q: str = "",
            dmin: str = "", dmax: str = "", gmin: str = "", gmax: str = "", per_page: str = ""):
    if (redirect := _login_redirect(request)):
        return redirect
    acts = _activities(request)
    years = sorted({a["start"].year for a in acts}, reverse=True)
    year_value = int(year) if year.isdigit() and int(year) in years else None
    terrain = terrain if terrain in stats.TERRAINS else "all"
    sort = sort if sort in stats.SORTS else "date"
    order = "asc" if order == "asc" else "desc"
    # nombre de sorties par page : choisi dans la page, sinon le dernier choix (cookie)
    chosen = per_page.isdigit() and int(per_page) in stats.PAGE_SIZES
    size = int(per_page) if chosen else int(request.cookies.get(PER_PAGE_COOKIE, "0") or 0)
    size = size if size in stats.PAGE_SIZES else stats.PER_PAGE
    distance = (_number(dmin), _number(dmax))
    gain = (_number(gmin), _number(gmax))
    data = stats.activity_list(acts, year_value, terrain, sort, order, page, q, distance, gain, size)
    keys = ("dmin", "dmax", "gmin", "gmax")
    bound = {k: "" if v is None else f"{v:g}" for k, v in zip(keys, distance + gain, strict=True)}
    filters = {"year": year_value or "", "terrain": terrain, "sort": sort, "order": order, "q": q, **bound}
    response = render(request, "sorties.html", "/sorties", data=data, years=years, filters=filters,
                      terrains=stats.TERRAINS, bounds=stats.list_bounds(acts), page_sizes=stats.PAGE_SIZES)
    if chosen:
        response.set_cookie(PER_PAGE_COOKIE, str(size), max_age=365 * 86400, httponly=True, samesite="lax")
    return response


@router.get("/performance")
def performance(request: Request, terrain: str = "road", year: str = ""):
    if (redirect := _login_redirect(request)):
        return redirect
    conn = db.connect(request.app.state.config.db_path)
    try:
        efforts = queries.best_efforts(conn)
    finally:
        conn.close()
    terrain = terrain if terrain in ("road", "trail") else "road"
    years = sorted({e["year"] for e in efforts}, reverse=True)
    year_value = int(year) if year.isdigit() and int(year) in years else None
    return render(request, "performance.html", "/performance",
                  data=stats.performance(efforts, terrain, year_value), years=years)


@router.get("/forme")
def forme(request: Request):
    if (redirect := _login_redirect(request)):
        return redirect
    cfg = request.app.state.config
    conn = db.connect(cfg.db_path)
    try:
        acts = queries.running_activities(conn)
        lthr = metrics_job.params_of(cfg, conn)["lthr"]
    finally:
        conn.close()
    return render(request, "forme.html", "/forme", data=stats.forme(acts, _today(request), lthr))


@router.get("/sorties/{activity_id}")
def sortie(request: Request, activity_id: int):
    if (redirect := _login_redirect(request)):
        return redirect
    cfg = request.app.state.config
    conn = db.connect(cfg.db_path)
    try:
        acts = queries.running_activities(conn)
        data = detail.activity_detail(cfg, conn, activity_id, acts, queries.best_efforts(conn))
    finally:
        conn.close()
    if data is not None:
        conn = db.connect(cfg.db_path)
        try:
            data["race_status"] = queries.race_decisions(conn).get(activity_id)
        finally:
            conn.close()
    if data is None:
        return HTMLResponse(TEMPLATES.get_template("not_found.html").render(version=__version__, nav=[
            (path, label) for path, label, ready in PAGES if ready], active=""), status_code=404)
    return render(request, "sortie.html", "/sorties", data=data)



@router.get("/courses")
def courses_page(request: Request):
    if (redirect := _login_redirect(request)):
        return redirect
    cfg = request.app.state.config
    conn = db.connect(cfg.db_path)
    try:
        data = courses.race_page(cfg, conn, _today(request))
        pending = len(courses.overview(cfg, conn)["pending"])
    finally:
        conn.close()
    return render(request, "courses.html", "/courses", data=data, pending=pending)


ESTIMATOR_COOKIE = "estimateur"


def _choice(value: str, cookie: str, allowed, default: int) -> tuple[int, bool]:
    """Réglage choisi dans la page, sinon le dernier choix (cookie), sinon la valeur par défaut ;
    et s'il vient d'être choisi."""
    if value.isdigit() and int(value) in allowed:
        return int(value), True
    return (int(cookie) if cookie.isdigit() and int(cookie) in allowed else default), False


@router.get("/estimateur")
def estimateur(request: Request, distance: str = "", gain: str = "", weeks: str = "", months: str = "",
               gpx: str = ""):
    if (redirect := _login_redirect(request)):
        return redirect
    cfg = request.app.state.config
    conn = db.connect(cfg.db_path)
    try:
        acts = queries.running_activities(conn)
        efforts = queries.best_efforts(conn)
        lthr = metrics_job.params_of(cfg, conn)["lthr"]
        confirmed = {i for i, status in queries.race_decisions(conn).items() if status == "confirmed"}
        elevation_params = settings.get(conn, "elevation")
    finally:
        conn.close()
    today = _today(request)
    # périodes de la forme (semaines) et du modèle allure-pente (mois), mémorisées dans un cookie
    saved = request.cookies.get(ESTIMATOR_COOKIE, "").split("-") + ["", ""]
    weeks_value, weeks_chosen = _choice(weeks, saved[0], estimator.FORM_WEEKS, estimator.WINDOW_DAYS // 7)
    months_value, months_chosen = _choice(months, saved[1], estimator.MODEL_PERIODS, 12)
    window = weeks_value * 7
    km, gain_m = _number(distance), _number(gain) or 0.0
    model = estimator.grade_pace_model(acts, today, estimator.MODEL_PERIODS[months_value])
    estimate = estimator.predict_road(efforts, today, km * 1000, gain_m, window_days=window) if km else None
    trail_result, gpx_meta = None, None
    if GPX_ID.fullmatch(gpx) and (cfg.gpx_dir / f"{gpx}.gpx").exists():
        gpx_meta = _gpx_meta(cfg, gpx)
        lats, lons, eles = parse_route((cfg.gpx_dir / f"{gpx}.gpx").read_bytes())
        trail_result = trail.estimate_gpx(lats, lons, eles, acts, efforts, today, window,
                                          estimator.MODEL_PERIODS[months_value],
                                          _gpx_dem(request, gpx, lats, lons), elevation_params)
    response = render(request, "estimateur.html", "/estimateur",
                      profile=estimator.current_form(acts, efforts, today, lthr, window),
                      table=estimator.road_table(efforts, today, window), estimate=estimate,
                      validation=estimator.validate_road(acts, efforts, confirmed, window),
                      weeks=weeks_value, months=months_value, form_weeks=estimator.FORM_WEEKS,
                      personal_exponent=estimator.personal_exponent(efforts, today),
                      model=model, model_table=estimator.model_table(model) if model else [],
                      trail=trail_result, gpx=gpx_meta, gpx_recent=_gpx_recent(cfg),
                      query={"distance": distance, "gain": gain, "gpx": gpx_meta["id"] if gpx_meta else ""})
    if weeks_chosen or months_chosen:
        response.set_cookie(ESTIMATOR_COOKIE, f"{weeks_value}-{months_value}", max_age=365 * 86400,
                            httponly=True, samesite="lax")
    return response


# ---------- GPX des courses à estimer ----------

GPX_ID = re.compile(r"[0-9a-f]{16}")
GPX_MAX_BYTES = 20 * 1024 * 1024
GPX_RECENT = 8


def _gpx_meta(cfg, gpx_id: str) -> dict:
    path = cfg.gpx_dir / f"{gpx_id}.json"
    meta = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {"id": gpx_id, "name": meta.get("name") or "Parcours", "uploaded_at": meta.get("uploaded_at")}


def _gpx_dem(request: Request, gpx_id: str, lats, lons) -> dict | None:
    """Altitudes du MNT le long du parcours, mises en cache à côté du GPX (data/gpx/<id>.dem.parquet) :
    le MNT n'est interrogé qu'une fois par parcours."""
    path = request.app.state.config.gpx_dir / f"{gpx_id}.dem.parquet"
    if path.exists():
        t = pq.read_table(path)
        return {"distance": t["distance_m"].to_numpy(), "altitude": t["altitude_m"].to_numpy().astype(float),
                "source": (t.schema.metadata or {}).get(b"provider", b"").decode()}
    dem = getattr(request.app.state, "dem", None)
    profile = trail.dem_altitudes(dem, lats, lons) if dem is not None else None
    if profile is not None:
        table = pa.table({"distance_m": profile["distance"],
                          "altitude_m": profile["altitude"].astype(np.float32)})
        pq.write_table(table.replace_schema_metadata({"provider": profile["source"]}), path)
    return profile


def _gpx_recent(cfg) -> list[dict]:
    """Derniers GPX importés, du plus récent au plus ancien."""
    if not cfg.gpx_dir.exists():
        return []
    files = sorted(cfg.gpx_dir.glob("*.gpx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [_gpx_meta(cfg, p.stem) for p in files[:GPX_RECENT] if GPX_ID.fullmatch(p.stem)]


@router.post("/estimateur/gpx")
async def upload_gpx(request: Request):
    """GPX envoyé tel quel par la page (corps de la requête) : vérifié, puis rangé dans data/gpx
    sous l'empreinte de son contenu (le même fichier importé deux fois n'est stocké qu'une fois)."""
    if not request.app.state.auth.check_session(request.cookies.get(SESSION_COOKIE)):
        return JSONResponse({"detail": "Session expirée : reconnecte-toi."}, status_code=401)
    data = await request.body()
    if not data or len(data) > GPX_MAX_BYTES:
        return JSONResponse({"detail": "Fichier vide ou trop gros (20 Mo au plus)."}, status_code=400)
    try:
        lats, lons, eles = parse_route(data)
    except Exception:
        return JSONResponse({"detail": "Ce fichier n'est pas un GPX lisible."}, status_code=400)
    if trail.route_profile(lats, lons, eles) is None:
        return JSONResponse({"detail": "Trace inutilisable : moins de 1 km, ou sans altitude."},
                            status_code=400)
    cfg = request.app.state.config
    gpx_id = hashlib.sha256(data).hexdigest()[:16]
    cfg.gpx_dir.mkdir(parents=True, exist_ok=True)
    (cfg.gpx_dir / f"{gpx_id}.gpx").write_bytes(data)
    name = unquote(request.headers.get("x-filename", "")).rsplit(".", 1)[0][:120] or "Parcours"
    (cfg.gpx_dir / f"{gpx_id}.json").write_text(json.dumps(
        {"name": name, "uploaded_at": datetime.now(UTC).replace(microsecond=0).isoformat()},
        ensure_ascii=False), encoding="utf-8")
    _gpx_dem(request, gpx_id, lats, lons)          # altitude du MNT, interrogé une fois
    return {"id": gpx_id}
