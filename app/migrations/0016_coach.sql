-- Calendrier du coach (phase 4), séparé des courses suivies de l'estimateur : échéances datées
-- avec une priorité A (objectif principal), B (course importante) ou C (préparation).
CREATE TABLE coach_races (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    race_date TEXT NOT NULL,            -- AAAA-MM-JJ
    priority TEXT NOT NULL CHECK (priority IN ('A', 'B', 'C')),
    gpx_id TEXT,                        -- parcours importé (data/gpx), sinon distance et D+
    distance_m REAL,
    gain_m REAL NOT NULL DEFAULT 0,
    target_s REAL,                      -- objectif (temps total), proposé par l'estimateur
    created_at TEXT NOT NULL
);
CREATE INDEX idx_coach_races_date ON coach_races (race_date);
