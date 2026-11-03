"""
Réglages modifiables depuis l'admin, stockés en JSON dans la table settings.

Chaque groupe a ses valeurs par défaut et sa validation ; seules les valeurs
différentes des défauts sont enregistrées.
"""
import json
from datetime import date

DEFAULTS = {
    "garmin_sync": {
        "enabled": True,                  # synchro automatique quotidienne
        "hour": 4,                        # heure locale de la synchro quotidienne
        "history_start": "2015-01-01",    # début du premier import complet
    },
    "elevation": {
        "step_m": 10.0,                   # pas de rééchantillonnage du profil
        "window": 3,                      # fenêtre du filtre médian (points, impair)
        "threshold_barometer": 1.0,       # seuil d'hystérésis, altitude du baromètre (m)
        "threshold_dem": 3.5,             # seuil d'hystérésis, MNT le long de la trace GPS (m)
    },
    # paramètres physiologiques réglés dans l'admin ; None = valeur du .env
    "physiology": {"hr_rest": None, "hr_max": None, "lthr": None, "sex": None},
}

PHYSIOLOGY_LIMITS = {"hr_rest": (30, 100), "hr_max": (120, 230), "lthr": (100, 220)}


def _validate_physiology(values: dict) -> dict:
    out = {}
    for key, value in values.items():
        if value is None:
            out[key] = None                # retour à la valeur du .env
        elif key in PHYSIOLOGY_LIMITS:
            lo, hi = PHYSIOLOGY_LIMITS[key]
            if isinstance(value, bool) or not isinstance(value, int | float) or not lo <= value <= hi:
                raise ValueError(f"{key} doit être un nombre entre {lo} et {hi}")
            out[key] = float(value)
        elif key == "sex":
            if value not in ("m", "f"):
                raise ValueError("sex doit valoir m ou f")
            out[key] = value
        else:
            raise ValueError(f"réglage inconnu : {key}")
    return out


def _validate_elevation(values: dict) -> dict:
    limits = {"step_m": (5.0, 50.0), "threshold_barometer": (0.0, 20.0), "threshold_dem": (0.0, 20.0)}
    out = {}
    for key, value in values.items():
        if key == "window":
            odd_int = isinstance(value, int) and not isinstance(value, bool) and value % 2 == 1
            if not odd_int or not 1 <= value <= 21:
                raise ValueError("window doit être un entier impair entre 1 et 21")
            out[key] = value
        elif key in limits:
            lo, hi = limits[key]
            if isinstance(value, bool) or not isinstance(value, int | float) or not lo <= value <= hi:
                raise ValueError(f"{key} doit être un nombre entre {lo:g} et {hi:g}")
            out[key] = float(value)
        else:
            raise ValueError(f"réglage inconnu : {key}")
    return out


def _validate_garmin_sync(values: dict) -> dict:
    out = {}
    for key, value in values.items():
        if key == "enabled":
            if not isinstance(value, bool):
                raise ValueError("enabled doit valoir true ou false")
        elif key == "hour":
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 23:
                raise ValueError("hour doit être un entier entre 0 et 23")
        elif key == "history_start":
            try:
                d = date.fromisoformat(value)
            except (TypeError, ValueError):
                raise ValueError("history_start doit être une date AAAA-MM-JJ") from None
            if not date(2000, 1, 1) <= d <= date.today():
                raise ValueError("history_start doit être entre 2000 et aujourd'hui")
        else:
            raise ValueError(f"réglage inconnu : {key}")
        out[key] = value
    return out


VALIDATORS = {"garmin_sync": _validate_garmin_sync, "elevation": _validate_elevation,
              "physiology": _validate_physiology}


def get(conn, group: str) -> dict:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (group,)).fetchone()
    stored = json.loads(row[0]) if row else {}
    return {**DEFAULTS[group], **stored}


def update(conn, group: str, values: dict) -> dict:
    if group not in VALIDATORS:
        raise ValueError(f"groupe de réglages inconnu : {group}")
    merged = {**get(conn, group), **VALIDATORS[group](values)}
    diff = {k: v for k, v in merged.items() if DEFAULTS[group].get(k) != v}
    with conn:
        if diff:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (group, json.dumps(diff)),
            )
        else:
            conn.execute("DELETE FROM settings WHERE key=?", (group,))
    return merged


# --- état interne (pas un réglage) : même table, clé préfixée ---

def get_state(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (f"state.{key}",)).fetchone()
    return json.loads(row[0]) if row else default


def set_state(conn, key: str, value):
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"state.{key}", json.dumps(value)),
        )
