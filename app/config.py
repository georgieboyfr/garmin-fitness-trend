"""
Configuration lue dans les variables d'environnement (fichier .env via docker compose).

Les secrets (identifiants Garmin, mot de passe admin) ne passent jamais par la base :
seules les variables d'environnement et le dossier des jetons les connaissent.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data_dir: Path
    hr_max: float = 190.0
    hr_rest: float = 50.0
    lthr: float = 170.0
    sex: str = "m"
    admin_user: str = "admin"
    admin_password_hash: str = field(default="", repr=False)
    garmin_email: str = ""
    garmin_password: str = field(default="", repr=False)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "fitness.db"

    @property
    def fit_dir(self) -> Path:
        return self.data_dir / "fit"

    @property
    def series_dir(self) -> Path:
        return self.data_dir / "series"

    @property
    def strava_dir(self) -> Path:
        return self.data_dir / "strava"

    @property
    def garmin_tokens_dir(self) -> Path:
        return self.data_dir / "garmin_tokens"

    @property
    def garmin_state_path(self) -> Path:
        return self.data_dir / "garmin_state.json"

    @property
    def session_secret_path(self) -> Path:
        return self.data_dir / "session_secret"

    def ensure_dirs(self):
        for d in (self.data_dir, self.fit_dir, self.series_dir, self.strava_dir, self.garmin_tokens_dir):
            d.mkdir(parents=True, exist_ok=True)


def _float(env, key, default):
    raw = env.get(key)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{key} doit être un nombre (reçu : {raw!r})") from None


def load_config(env=None) -> Config:
    env = os.environ if env is None else env
    sex = (env.get("SEX") or "m").strip().lower()[:1]
    if sex not in ("m", "f"):
        raise ValueError(f"SEX doit valoir m ou f (reçu : {env.get('SEX')!r})")
    cfg = Config(
        data_dir=Path(env.get("DATA_DIR") or "/data"),
        hr_max=_float(env, "HR_MAX", 190.0),
        hr_rest=_float(env, "HR_REST", 50.0),
        lthr=_float(env, "LTHR", 170.0),
        sex=sex,
        admin_user=(env.get("ADMIN_USER") or "admin").strip(),
        admin_password_hash=(env.get("ADMIN_PASSWORD_HASH") or "").strip(),
        garmin_email=(env.get("GARMIN_EMAIL") or "").strip(),
        garmin_password=env.get("GARMIN_PASSWORD") or "",
    )
    if not cfg.hr_rest < cfg.lthr < cfg.hr_max:
        raise ValueError("Il faut HR_REST < LTHR < HR_MAX")
    return cfg
