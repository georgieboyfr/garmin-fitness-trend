-- Origine d'une activité : Garmin (cas général) ou Strava (sortie sans équivalent Garmin,
-- importée depuis l'archive Strava ; son id est alors -<id Strava> pour ne jamais
-- croiser un id Garmin).
ALTER TABLE activities ADD COLUMN source TEXT NOT NULL DEFAULT 'garmin'
    CHECK (source IN ('garmin', 'strava'));

-- Activités de l'export Strava (activities.csv). Seuls les noms donnés par Greg servent
-- (jamais envoyés à un LLM : conditions Strava).
CREATE TABLE strava_activities (
    strava_id INTEGER PRIMARY KEY,
    start_time_utc TEXT NOT NULL,         -- ISO 8601 UTC
    name TEXT,
    description TEXT,                     -- description saisie dans Strava
    activity_type TEXT,                   -- type Strava, tel qu'exporté (langue du compte)
    distance_m REAL,
    elapsed_s REAL,
    elevation_gain_m REAL,                -- D+ calculé par Strava (comparaison seulement)
    filename TEXT,                        -- trace dans l'archive (activities/...)
    generic_name INTEGER NOT NULL DEFAULT 0 CHECK (generic_name IN (0, 1)),
    activity_id INTEGER REFERENCES activities (id) ON DELETE SET NULL,  -- appariée ou importée
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_strava_start ON strava_activities (start_time_utc);
CREATE INDEX idx_strava_activity ON strava_activities (activity_id);

-- Fichiers d'export traités (dossier surveillé ou upload de l'admin).
CREATE TABLE strava_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    sha256 TEXT,
    kind TEXT CHECK (kind IN ('zip', 'csv')),
    status TEXT NOT NULL CHECK (status IN ('ok', 'older', 'duplicate', 'error')),
    activities INTEGER,
    last_activity_utc TEXT,               -- date de la dernière activité contenue
    error TEXT,
    imported_at TEXT NOT NULL
);

-- Nom affiché : celui donné dans Strava s'il n'est pas générique, sinon celui de Garmin
-- (et pour une activité importée de Strava, son nom Strava même générique).
-- Description : celle saisie dans Strava, s'il y en a une.
CREATE VIEW activity_names AS
SELECT a.id AS activity_id,
       COALESCE((SELECT s.name FROM strava_activities s
                 WHERE s.activity_id = a.id AND s.generic_name = 0
                 ORDER BY s.strava_id LIMIT 1),
                a.garmin_name,
                (SELECT s.name FROM strava_activities s WHERE s.activity_id = a.id
                 ORDER BY s.strava_id LIMIT 1)) AS name,
       (SELECT NULLIF(TRIM(s.description), '') FROM strava_activities s WHERE s.activity_id = a.id
        ORDER BY s.strava_id LIMIT 1) AS description
FROM activities a;
