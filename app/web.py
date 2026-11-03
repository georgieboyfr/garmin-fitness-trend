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
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import __version__, db, queries, stats
from .auth import SESSION_COOKIE

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")

# (chemin, libellé, prête) : les pages pas encore prêtes n'apparaissent pas dans le menu
PAGES = [
    ("/", "Accueil", True),
    ("/volume", "Volume", True),
    ("/performance", "Performance", False),
    ("/forme", "Forme", False),
    ("/courses", "Courses", False),
    ("/sorties", "Sorties", False),
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

