"""
Pages de statistiques (templates Jinja + ECharts), protégées par la session de l'admin.

Les données de chaque page sont calculées côté serveur et insérées dans la page en JSON :
pas d'appel d'API supplémentaire, et rien à mettre en cache côté navigateur.
"""
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import __version__, courses, db, detail, metrics_job, queries, stats
from .auth import SESSION_COOKIE

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")

# (chemin, libellé, prête) : les pages pas encore prêtes n'apparaissent pas dans le menu
PAGES = [
    ("/", "Accueil", True),
    ("/volume", "Volume", True),
    ("/sorties", "Sorties", True),
    ("/performance", "Performance", True),
    ("/forme", "Forme", True),
    ("/courses", "Courses", True),
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


@router.get("/sorties")
def sorties(request: Request, page: int = 1, year: str = "", terrain: str = "all",
            sort: str = "date", order: str = "desc", q: str = ""):
    if (redirect := _login_redirect(request)):
        return redirect
    acts = _activities(request)
    years = sorted({a["start"].year for a in acts}, reverse=True)
    year_value = int(year) if year.isdigit() and int(year) in years else None
    terrain = terrain if terrain in stats.TERRAINS else "all"
    sort = sort if sort in stats.SORTS else "date"
    order = "asc" if order == "asc" else "desc"
    data = stats.activity_list(acts, year_value, terrain, sort, order, page, q)
    filters = {"year": year_value or "", "terrain": terrain, "sort": sort, "order": order, "q": q}
    return render(request, "sorties.html", "/sorties", data=data, years=years, filters=filters,
                  terrains=stats.TERRAINS)


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
