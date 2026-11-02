import os
import logging
from datetime import date, timedelta, datetime as dt

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler

from garmin_sync import get_db, sync, get_state, sync_running, rebuild_fit_metrics
from fitness_model import compute_series
import stats as stats_module

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app")

app = FastAPI(title="Garmin Fitness Trend")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.get("/api/status")
def api_status():
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    last = conn.execute("SELECT MAX(start_time) FROM activities").fetchone()[0]
    status = {
        "activities_synced": count,
        "last_activity": last,
        "last_sync_status": get_state(conn, "last_sync_status", "never_run"),
        "last_sync_started": get_state(conn, "last_sync_started"),
        "last_sync_finished": get_state(conn, "last_sync_finished"),
        "last_sync_summary": get_state(conn, "last_sync_summary"),
        "last_sync_error": get_state(conn, "last_sync_error"),
        "sync_current_activity": get_state(conn, "sync_current_activity"),
        "sync_current_index": get_state(conn, "sync_current_index"),
        "sync_current_stage": get_state(conn, "sync_current_stage"),
        "sync_current_fit": get_state(conn, "sync_current_fit"),
        "sync_running": sync_running(),
    }
    conn.close()
    return status


@app.get("/api/fitness")
def api_fitness(days: int = 180):
    conn = get_db()
    rows = conn.execute("SELECT date, total_hrss FROM daily_stress").fetchall()
    conn.close()
    daily = {r[0]: r[1] for r in rows}

    end = date.today()
    start = end - timedelta(days=days)
    if daily:
        first = dt.fromisoformat(min(daily.keys())).date()
        if first < start:
            start = first

    return {"series": compute_series(daily, start, end)}


@app.get("/api/activities")
def api_activities(limit: int = 50):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, start_time, sport, duration_s, avg_hr, max_hr, trimp, hrss, "
        "distance_m, elevation_gain_m, avg_cadence, avg_speed_mps, max_altitude_m "
        "FROM activities ORDER BY start_time DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    cols = [
        "id", "start_time", "sport", "duration_s", "avg_hr", "max_hr", "trimp",
        "hrss", "distance_m", "elevation_gain_m", "avg_cadence", "avg_speed_mps", "max_altitude_m"
    ]
    return {"activities": [dict(zip(cols, r)) for r in rows]}


@app.get("/api/stats/summary")
def api_stats_summary():
    conn = get_db()
    data = stats_module.summary(conn)
    conn.close()
    return data


@app.get("/api/stats/distributions")
def api_stats_distributions():
    conn = get_db()
    data = stats_module.distributions(conn)
    conn.close()
    return data


@app.get("/api/stats/yearly")
def api_stats_yearly(metric: str = "distance"):
    column = "distance_m" if metric == "distance" else "elevation_gain_m"
    conn = get_db()
    data = stats_module.yearly_cumulative(conn, column)
    conn.close()
    return {"metric": metric, "series": data}


@app.get("/api/stats/performance")
def api_stats_performance(days: int = 36500):
    if days < 30 or days > 36500:
        raise HTTPException(status_code=400, detail="days doit être compris entre 30 et 36500.")
    conn = get_db()
    data = stats_module.performance_series(conn, days)
    conn.close()
    return data


@app.post("/api/stats/rebuild-performance")
def api_rebuild_performance(background_tasks: BackgroundTasks):
    if sync_running():
        raise HTTPException(status_code=409, detail="Une synchronisation/reconstruction est déjà en cours.")
    background_tasks.add_task(rebuild_fit_metrics)
    return {"status": "recalcul démarré", "message": "Les FIT déjà stockés sont en cours de recalcul."}


@app.get("/api/stats/monthly")
def api_stats_monthly(metric: str = "distance"):
    column = "distance_m" if metric == "distance" else "elevation_gain_m"
    conn = get_db()
    data = stats_module.monthly_totals(conn, column)
    conn.close()
    return {"metric": metric, "series": data}


def _run_sync_safely(days_back):
    try:
        sync(days_back)
    except Exception as e:
        logger.exception("Sync échouée : %s", e)


@app.post("/api/sync")
def api_sync(background_tasks: BackgroundTasks, days_back: int = 30):
    if days_back < 1 or days_back > 3650:
        raise HTTPException(
            status_code=400,
            detail="days_back doit être compris entre 1 et 3650."
        )

    if sync_running():
        return {
            "status": "déjà en cours",
            "message": "Une synchronisation Garmin est déjà en cours."
        }

    background_tasks.add_task(_run_sync_safely, days_back)
    return {
        "status": "sync démarrée",
        "days_back": days_back,
    }


# --- Synchro automatique -------------------------------------------------
scheduler = BackgroundScheduler()
scheduler.add_job(
    lambda: _run_sync_safely(
        int(os.environ.get("SYNC_LOOKBACK_DAYS", 7))
    ),
    "interval",
    hours=int(os.environ.get("SYNC_INTERVAL_HOURS", 12)),
    next_run_time=dt.now() + timedelta(seconds=10),
    max_instances=1,
    coalesce=True,
)
scheduler.start()

# --- Fichiers statiques --------------------------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")
