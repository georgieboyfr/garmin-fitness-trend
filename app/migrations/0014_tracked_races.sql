-- Courses suivies par l'estimateur (indépendantes du coach) et leur prédiction de chaque semaine.
CREATE TABLE tracked_races (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    race_date TEXT,                     -- AAAA-MM-JJ, facultative
    gpx_id TEXT,                        -- parcours importé (data/gpx), sinon distance et D+
    distance_m REAL,
    gain_m REAL NOT NULL DEFAULT 0,
    target_s REAL,                      -- objectif facultatif (temps total)
    activity_id INTEGER REFERENCES activities (id) ON DELETE SET NULL,   -- sortie reliée après la course
    created_at TEXT NOT NULL
);

CREATE TABLE tracked_predictions (
    race_id INTEGER NOT NULL REFERENCES tracked_races (id) ON DELETE CASCADE,
    week TEXT NOT NULL,                 -- lundi de la semaine
    form_day TEXT NOT NULL,             -- forme au soir de ce jour (le dimanche précédent)
    optimistic_s REAL NOT NULL,
    realistic_s REAL NOT NULL,
    prudent_s REAL NOT NULL,
    fitness REAL,
    replayed INTEGER NOT NULL DEFAULT 0,    -- 1 : rejouée à l'ajout de la course, pas enregistrée ce lundi-là
    version TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (race_id, week)
);
