-- Montres connues : le baromètre décide de la source d'altitude (altimètre ou MNT).
-- La présence d'une altitude dans le FIT ne suffit pas (Forerunner 245 : altitude GPS).
CREATE TABLE devices (
    garmin_product INTEGER PRIMARY KEY,   -- file_id.garmin_product du FIT
    model TEXT NOT NULL,
    has_barometer INTEGER NOT NULL CHECK (has_barometer IN (0, 1))
);
INSERT INTO devices (garmin_product, model, has_barometer) VALUES
    (2503, 'Forerunner 35', 0),
    (3076, 'Forerunner 245', 0),
    (3992, 'Forerunner 255', 1);

-- Activités Garmin, tous sports confondus : le filtre « course à pied » est fait
-- par les calculs, pour ne jamais avoir à retélécharger une activité.
CREATE TABLE activities (
    id INTEGER PRIMARY KEY,               -- activityId Garmin
    start_time_utc TEXT NOT NULL,         -- ISO 8601 UTC (startTimeGMT), sert à l'appariement Strava
    start_time_local TEXT NOT NULL,       -- heure locale de départ (startTimeLocal)
    activity_type TEXT NOT NULL,          -- activityType.typeKey
    garmin_name TEXT,
    distance_m REAL,
    duration_s REAL,
    moving_duration_s REAL,
    avg_hr REAL,
    max_hr REAL,
    garmin_product INTEGER,               -- lu dans le FIT
    fit_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (fit_status IN ('pending', 'stored', 'error')),
    fit_error TEXT,
    deleted_in_garmin INTEGER NOT NULL DEFAULT 0 CHECK (deleted_in_garmin IN (0, 1)),
    first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_activities_start ON activities (start_time_utc);
CREATE INDEX idx_activities_type ON activities (activity_type);

-- Historique des synchros et recalculs, affiché dans l'admin.
CREATE TABLE sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                   -- garmin, strava, recalcul...
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'ok', 'error', 'cancelled')),
    summary TEXT,
    error TEXT
);

-- Réglages modifiables depuis l'admin (valeurs JSON). Jamais de secret ici.
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
