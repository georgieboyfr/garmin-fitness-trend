-- D+ donné par Garmin (liste des activités) : comparaison seulement, jamais affiché
-- comme référence (il additionne le bruit du baromètre).
ALTER TABLE activities ADD COLUMN garmin_elevation_gain_m REAL;

-- D+ / D− recalculés par l'application (elevation_job.py).
CREATE TABLE activity_elevation (
    activity_id INTEGER PRIMARY KEY REFERENCES activities (id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('barometer', 'dem', 'none')),
    dem_provider TEXT,                    -- ign, copernicus ou ign+copernicus
    gain_m REAL NOT NULL,
    loss_m REAL NOT NULL,
    algo_version INTEGER NOT NULL,        -- elevation.ALGO_VERSION
    params TEXT NOT NULL,                 -- réglages utilisés (JSON trié)
    computed_at TEXT NOT NULL
);
