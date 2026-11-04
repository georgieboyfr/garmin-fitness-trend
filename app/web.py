"""
Pages de statistiques (templates Jinja + ECharts), protégées par la session de l'admin.

Les données de chaque page sont calculées côté serveur et insérées dans la page en JSON :
pas d'appel d'API supplémentaire, et rien à mettre en cache côté navigateur.
"""
import hashlib
import json
import math
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import (
    __version__,
    coach,
    coach_live,
    coach_plan,
    coach_review,
    courses,
    db,
    detail,
    estimator,
    gpx_store,
    hr_speed,
    metrics_job,
    physio,
    queries,
    settings,
    stats,
    tracked,
    trail,
)
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
    ("/coach", "Coach", True),
]

router = APIRouter(include_in_schema=False)

# paramètre de version des fichiers statiques : la version publiée, ou en développement l'heure de
# démarrage, pour que le navigateur ne garde pas d'anciens scripts d'une session à l'autre
ASSET_VERSION = __version__ if not __version__.endswith("-dev") else f"dev{int(time.time())}"


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
        "asset_version": ASSET_VERSION,
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
    today = _today(request)
    try:
        acts = queries.running_activities(conn)
        efforts = queries.best_efforts(conn)
        params = metrics_job.params_of(cfg, conn)
        lthr = params["lthr"]
        trend = hr_speed.SpeedTrend(queries.steady_blocks(conn), lthr)
        lthr_est = metrics_job.lthr_estimate(conn, today)
    finally:
        conn.close()
    return render(request, "forme.html", "/forme", data=stats.forme(acts, today, lthr),
                  physio=physio.physiology(efforts, today, lthr_est, params["hr_max"], trend),
                  lthr_used=lthr)


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
        return HTMLResponse(TEMPLATES.get_template("not_found.html").render(
            version=__version__, asset_version=ASSET_VERSION, nav=[
            (path, label) for path, label, ready in PAGES if ready], active=""), status_code=404)
    return render(request, "sortie.html", "/sorties", data=data)




@router.get("/sorties/{activity_id}/estime-reel")
def estimate_vs_actual(request: Request, activity_id: int):
    """Estimateur rejoué sur la trace d'une course réalisée (forme de la veille et d'aujourd'hui),
    écart cumulé au temps réel le long du parcours."""
    if (error := _session_error(request)):
        return error
    cfg = request.app.state.config
    conn = db.connect(cfg.db_path)
    try:
        result = tracked.estimate_vs_actual(cfg, conn, activity_id, _today(request))
    finally:
        conn.close()
    return JSONResponse(result, status_code=400 if "error" in result else 200)

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
        factors = tracked.corrections(conn)
        trend = hr_speed.SpeedTrend(queries.steady_blocks(conn), lthr)
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
    estimate = (estimator.predict_road(efforts, today, km * 1000, gain_m, window_days=window, trend=trend)
                if km else None)
    trail_result, gpx_meta = None, None
    if gpx_store.exists(cfg, gpx):
        gpx_meta = gpx_store.meta(cfg, gpx, stations=True)
        lats, lons, eles, dem_profile = gpx_store.route(cfg, gpx, getattr(request.app.state, "dem", None))
        trail_result = trail.estimate_gpx(lats, lons, eles, acts, efforts, today, window,
                                          estimator.MODEL_PERIODS[months_value],
                                          dem_profile, elevation_params,
                                          gpx_meta["aid_stations"], confirmed, trend)
    estimate = estimator.apply_correction(estimate, factors["road"])
    trail_result = estimator.apply_correction(trail_result, factors["trail"])
    validation = estimator.validate_road(acts, efforts, confirmed, window, trend)
    trail_validation = trail.validate_trail(
        tracked.race_profiles(cfg, acts, confirmed, elevation_params), acts, efforts, confirmed,
        window, estimator.MODEL_PERIODS[months_value], trend)
    if estimate:
        estimate["confidence"] = estimator.confidence(estimate, today, validation["used"])
    if trail_result and not trail_result.get("error"):
        trail_result["confidence"] = estimator.confidence(trail_result, today, trail_validation["total"],
                                                          estimator.longest_moving_s(acts, today))
    tracked_rows = _tracked_overview(cfg, today)
    profile = estimator.current_form(acts, efforts, today, lthr, window)
    slope = estimator.fitness_slope(acts, efforts, today, window)
    fitness = profile["load"]["fitness"] if profile["load"] else None

    def context(result, distance_m, gain):
        """Courses passées les plus proches et effet de la forme pour une estimation."""
        if not result or result.get("error"):
            return None
        return {"nearest": estimator.nearest_races(acts, confirmed, distance_m, gain),
                "scenarios": estimator.form_scenarios(result["realistic_s"], fitness, slope),
                "slope": slope, "fitness": fitness}

    response = render(request, "estimateur.html", "/estimateur",
                      profile=profile,
                      road_context=context(estimate, (km or 0) * 1000, gain_m),
                      trail_context=context(trail_result, trail_result.get("distance_m"),
                                            trail_result.get("gain_m")) if trail_result else None,
                      table=[estimator.apply_correction(r, factors["road"])
                             for r in estimator.road_table(efforts, today, window, trend)],
                      estimate=estimate, factors=factors,
                      validation=validation, trail_validation=trail_validation,
                      weeks=weeks_value, months=months_value, form_weeks=estimator.FORM_WEEKS,
                      personal_exponent=estimator.personal_exponent(efforts, today),
                      model=model, model_table=estimator.model_table(model) if model else [],
                      trail=trail_result, gpx=gpx_meta, gpx_recent=gpx_store.recent(cfg),
                      tracked=tracked_rows, ahead=tracked.ahead_errors(tracked_rows),
                      query={"distance": distance, "gain": gain, "gpx": gpx_meta["id"] if gpx_meta else ""})
    if weeks_chosen or months_chosen:
        response.set_cookie(ESTIMATOR_COOKIE, f"{weeks_value}-{months_value}", max_age=365 * 86400,
                            httponly=True, samesite="lax")
    return response



def _tracked_overview(cfg, today):
    conn = db.connect(cfg.db_path)
    try:
        return tracked.overview(cfg, conn, today)
    finally:
        conn.close()


# ---------- courses suivies ----------

def _session_error(request: Request):
    if not request.app.state.auth.check_session(request.cookies.get(SESSION_COOKIE)):
        return JSONResponse({"detail": "Session expirée : reconnecte-toi."}, status_code=401)
    return None


async def _tracked_values(request: Request):
    try:
        return tracked.clean(request.app.state.config, await request.json()), None
    except ValueError as e:
        return None, JSONResponse({"detail": str(e) or "Saisie invalide."}, status_code=400)


@router.post("/estimateur/courses")
async def tracked_create(request: Request):
    """Ajoute une course suivie et rejoue ses prédictions des 12 dernières semaines."""
    if (error := _session_error(request)):
        return error
    values, error = await _tracked_values(request)
    if error:
        return error
    cfg = request.app.state.config
    conn = db.connect(cfg.db_path)
    try:
        race_id = tracked.create(conn, values)
        tracked.record(cfg, conn, _today(request), race_ids={race_id}, replay_weeks=tracked.REPLAY_WEEKS,
                       dem=getattr(request.app.state, "dem", None))
    finally:
        conn.close()
    return {"id": race_id}


@router.post("/estimateur/courses/{race_id}")
async def tracked_update(request: Request, race_id: int):
    if (error := _session_error(request)):
        return error
    values, error = await _tracked_values(request)
    if error:
        return error
    cfg = request.app.state.config
    conn = db.connect(cfg.db_path)
    try:
        if tracked.get(conn, race_id) is None:
            return JSONResponse({"detail": "Course inconnue."}, status_code=404)
        if tracked.update(conn, race_id, values):
            tracked.record(cfg, conn, _today(request), race_ids={race_id}, replay_weeks=tracked.REPLAY_WEEKS,
                           dem=getattr(request.app.state, "dem", None))
    finally:
        conn.close()
    return {"id": race_id}


@router.post("/estimateur/courses/{race_id}/supprimer")
def tracked_delete(request: Request, race_id: int):
    if (error := _session_error(request)):
        return error
    conn = db.connect(request.app.state.config.db_path)
    try:
        tracked.delete(conn, race_id)
    finally:
        conn.close()
    return {"deleted": race_id}


@router.get("/estimateur/courses/{race_id}")
def tracked_page(request: Request, race_id: int):
    if (redirect := _login_redirect(request)):
        return redirect
    cfg = request.app.state.config
    today = _today(request)
    conn = db.connect(cfg.db_path)
    try:
        race = tracked.get(conn, race_id)
        if race is None:
            return HTMLResponse(TEMPLATES.get_template("not_found.html").render(
                version=__version__, asset_version=ASSET_VERSION,
                nav=[(path, label) for path, label, ready in PAGES if ready], active=""),
                status_code=404)
        data = tracked.load_data(cfg, conn)
        if tracked.link_races(cfg, conn, today, data):
            race = tracked.get(conn, race_id)
        info = tracked.summary(cfg, conn, race, today)
        candidates = tracked.candidates(conn, race) if info["past"] or info["activity_id"] else []
    finally:
        conn.close()
    context = None
    if info["last"]:
        acts = data["acts"]
        distance_m, gain = race["distance_m"], race["gain_m"]
        if race["gpx_id"] and gpx_store.exists(cfg, race["gpx_id"]):
            lats, lons, eles, dem_profile = gpx_store.route(cfg, race["gpx_id"])
            profile = trail.route_profile(lats, lons, eles, dem_profile, data["params"])
            if profile:
                distance_m, gain = float(profile["distance"][-1]), profile["gain_m"]
        before = date.fromisoformat(race["race_date"]) if race["race_date"] else None
        slope = estimator.fitness_slope(acts, data["efforts"], today)
        last = info["last"]
        context = {"nearest": estimator.nearest_races(acts, data["confirmed"], distance_m or 0, gain or 0,
                                                      before=before),
                   "scenarios": estimator.form_scenarios(last["realistic_s"], last["fitness"], slope),
                   "slope": slope, "fitness": last["fitness"]}
    return render(request, "course_suivie.html", "/estimateur", race=info, predictions=info["predictions"],
                  estimate_context=context, gpx_recent=gpx_store.recent(cfg), candidates=candidates)


@router.post("/estimateur/courses/{race_id}/sortie")
async def tracked_link(request: Request, race_id: int):
    """Relie à la main la course suivie à une sortie (ou la délie avec null)."""
    if (error := _session_error(request)):
        return error
    try:
        activity_id = (await request.json()).get("activity_id")
        activity_id = None if activity_id is None else int(activity_id)
    except (ValueError, TypeError, AttributeError):
        return JSONResponse({"detail": "Sortie invalide."}, status_code=400)
    conn = db.connect(request.app.state.config.db_path)
    try:
        race = tracked.get(conn, race_id)
        if race is None:
            return JSONResponse({"detail": "Course inconnue."}, status_code=404)
        if activity_id is not None and activity_id not in {a["id"] for a in tracked.candidates(conn, race)}:
            return JSONResponse({"detail": "Sortie hors des jours de la course."}, status_code=400)
        tracked.set_activity(conn, race_id, activity_id, manual=True)
    finally:
        conn.close()
    return {"id": race_id, "activity_id": activity_id}


# ---------- GPX des courses à estimer ----------

GPX_MAX_BYTES = 20 * 1024 * 1024


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
    # altitude du MNT, interrogé une fois
    gpx_store.dem_profile(cfg, gpx_id, lats, lons, getattr(request.app.state, "dem", None))
    return {"id": gpx_id}


@router.post("/estimateur/gpx/{gpx_id}/ravitos")
async def save_aid_stations(request: Request, gpx_id: str):
    """Ravitos d'un parcours (km, nom, arrêt en minutes), enregistrés avec son nom."""
    if not request.app.state.auth.check_session(request.cookies.get(SESSION_COOKIE)):
        return JSONResponse({"detail": "Session expirée : reconnecte-toi."}, status_code=401)
    cfg = request.app.state.config
    if not gpx_store.exists(cfg, gpx_id):
        return JSONResponse({"detail": "Parcours inconnu."}, status_code=404)
    try:
        stations = trail.clean_stations(await request.json())
    except ValueError as e:
        return JSONResponse({"detail": str(e) if str(e).strip() else "Saisie invalide."}, status_code=400)
    path = cfg.gpx_dir / f"{gpx_id}.json"
    meta = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    meta["aid_stations"] = stations
    path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return {"aid_stations": stations}


# ---------- coach ----------

@router.get("/coach")
def coach_page(request: Request, vue: str = ""):
    if (redirect := _login_redirect(request)):
        return redirect
    cfg = request.app.state.config
    today = _today(request)
    dem = getattr(request.app.state, "dem", None)
    conn = db.connect(cfg.db_path)
    try:
        sync_cfg = settings.get(conn, "garmin_sync")
        synced = (not sync_cfg["enabled"]
                  or settings.get_state(conn, "garmin_last_auto_day") == today.isoformat())
        co = coach_live.Coach(cfg, conn, today, dem, synced)
        cal = co.cal
        # les courses s'informent entre elles : l'estimation suit la forme du jour, résultats des
        # courses passées compris ; un objectif qui s'en écarte de plus de 3 % est signalé
        recent_past = next((r for r in cal["past"]
                            if (today - date.fromisoformat(r["race_date"])).days <= coach.DRIFT_SINCE_DAYS),
                           None)
        for r in cal["upcoming"]:
            r["proposal"] = coach.proposed_target(cfg, r, today, co.data, co.factors, dem)
            r["route"] = tracked._route_label(cfg, r)
            if r["proposal"] and r.get("target_s"):
                drift = r["proposal"]["realistic_s"] / r["target_s"] - 1
                if abs(drift) >= coach.DRIFT_SHARE:
                    r["drift_pct"] = round(drift * 100)
                    r["drift_since"] = recent_past["name"] if recent_past else None
        upcoming_tracked = [r for r in co.tracked_races
                            if not r["race_date"] or r["race_date"] >= today.isoformat()]
        plan = week = bilan = None
        if vue not in ("semaine", "plan", "echeances", "reglages"):
            vue = "semaine" if cal["main"] else "echeances"
        if cal["main"] and vue in ("semaine", "plan"):
            # la semaine en cours est celle du plan du lundi (forme et proposition de la veille) :
            # elle ne bouge pas au fil des sorties de la semaine ; le plan affiche la même.
            # Bilan : celui de la semaine en cours le dimanche, sinon celui de la semaine dernière
            # (figé une fois la semaine close) ; ses réponses orientent la semaine qui suit.
            monday_ = coach_plan.monday(today)
            reviewed = monday_ if today.weekday() == 6 else monday_ - timedelta(days=7)
            summary = co.review(reviewed, conn)
            frozen = co.week_plan(monday_)
            if vue == "plan":
                # le dimanche, la semaine suivante tient compte des réponses du bilan du jour
                nxt = co.adjust_for(monday_ + timedelta(days=7)) if reviewed == monday_ else None
                plan = co.plan_on(today, cal["main"], [co.adjust_for(monday_), nxt])
            if frozen and frozen["weeks"]:
                if plan and plan["weeks"] and plan["weeks"][0]["monday"] == frozen["weeks"][0]["monday"]:
                    plan["weeks"][0] = frozen["weeks"][0]
                week = co.week_view(monday_, frozen)
            if summary:
                answers = co.answers(reviewed)
                bilan = {"summary": summary, "answers": answers, "current": reviewed == monday_,
                         "monday": reviewed.isoformat(),
                         "orientation": coach_review.orientation(answers, summary)}
    finally:
        conn.close()
    return render(request, "coach.html", "/coach", calendar=cal, vue=vue,
                  availability=co.availability, plan=plan, week=week, bilan=bilan,
                  next_week_choices=coach_review.NEXT_WEEK, feeling_choices=coach_review.FEELINGS,
                  inferred=co.inferred, availability_saved=co.profile["availability"] is not None,
                  max_sessions=co.profile["max_sessions"], plan_options=co.profile,
                  period_labels=coach_plan.PERIOD_LABELS,
                  habits=co.habits,
                  priorities=coach.PRIORITIES, gpx_recent=gpx_store.recent(cfg),
                  tracked_races=upcoming_tracked,
                  today=today.isoformat())


@router.post("/coach/bilan/{monday_}")
async def coach_review_answers(request: Request, monday_: str):
    """Réponses du bilan d'une semaine (semaine suivante, ressenti) : elles orientent la suivante."""
    if (error := _session_error(request)):
        return error
    try:
        day = date.fromisoformat(monday_)
        if day.weekday() != 0:
            raise ValueError("La semaine doit commencer un lundi.")
        answers = coach_review.clean_answers(await request.json())
    except ValueError as e:
        return JSONResponse({"detail": str(e) or "Saisie invalide."}, status_code=400)
    conn = db.connect(request.app.state.config.db_path)
    try:
        coach_review.save_answers(conn, day, answers)
    finally:
        conn.close()
    return {"saved": True}


async def _coach_values(request: Request):
    try:
        return coach.clean(request.app.state.config, await request.json()), None
    except ValueError as e:
        return None, JSONResponse({"detail": str(e) or "Saisie invalide."}, status_code=400)


@router.post("/coach/courses")
async def coach_create(request: Request):
    if (error := _session_error(request)):
        return error
    values, error = await _coach_values(request)
    if error:
        return error
    conn = db.connect(request.app.state.config.db_path)
    try:
        race_id = coach.create(conn, values)
    finally:
        conn.close()
    return {"id": race_id}


@router.post("/coach/courses/{race_id}")
async def coach_update(request: Request, race_id: int):
    if (error := _session_error(request)):
        return error
    values, error = await _coach_values(request)
    if error:
        return error
    conn = db.connect(request.app.state.config.db_path)
    try:
        if coach.get(conn, race_id) is None:
            return JSONResponse({"detail": "Course inconnue."}, status_code=404)
        coach.update(conn, race_id, values)
    finally:
        conn.close()
    return {"id": race_id}


@router.post("/coach/courses/{race_id}/objectif")
async def coach_target(request: Request, race_id: int):
    """Objectif accepté (temps proposé) ou modifié ; null le retire."""
    if (error := _session_error(request)):
        return error
    body = await request.json()
    target = body.get("target_s") if isinstance(body, dict) else None
    if target is not None and (isinstance(target, bool) or not isinstance(target, int | float)
                               or not 0 < target <= tracked.MAX_TARGET_S):
        return JSONResponse({"detail": "Objectif invalide."}, status_code=400)
    conn = db.connect(request.app.state.config.db_path)
    try:
        if coach.get(conn, race_id) is None:
            return JSONResponse({"detail": "Course inconnue."}, status_code=404)
        coach.set_target(conn, race_id, float(target) if target is not None else None)
    finally:
        conn.close()
    return {"id": race_id}


@router.post("/coach/courses/{race_id}/priorite")
async def coach_priority(request: Request, race_id: int):
    """Priorité changée, par exemple pour résoudre un conflit du calendrier."""
    if (error := _session_error(request)):
        return error
    body = await request.json()
    conn = db.connect(request.app.state.config.db_path)
    try:
        if coach.get(conn, race_id) is None:
            return JSONResponse({"detail": "Course inconnue."}, status_code=404)
        coach.set_priority(conn, race_id, body.get("priority") if isinstance(body, dict) else None)
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    finally:
        conn.close()
    return {"id": race_id}


@router.post("/coach/courses/{race_id}/supprimer")
def coach_delete(request: Request, race_id: int):
    if (error := _session_error(request)):
        return error
    conn = db.connect(request.app.state.config.db_path)
    try:
        coach.delete(conn, race_id)
    finally:
        conn.close()
    return {"deleted": race_id}


@router.post("/coach/profil")
async def coach_profile(request: Request):
    """Disponibilités par jour et habitudes gardées ; null revient à l'historique."""
    if (error := _session_error(request)):
        return error
    try:
        values = coach.clean_profile(await request.json())
    except (ValueError, KeyError, TypeError) as e:
        return JSONResponse({"detail": str(e) or "Saisie invalide."}, status_code=400)
    conn = db.connect(request.app.state.config.db_path)
    try:
        settings.update(conn, "coach", values)
    finally:
        conn.close()
    return {"saved": True}
