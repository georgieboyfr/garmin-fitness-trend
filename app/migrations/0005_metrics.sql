-- Métriques par sortie de course à pied (metrics_job.py), recalculées quand la version
-- de l'algorithme ou les paramètres physiologiques (.env) changent.
CREATE TABLE activity_metrics (
    activity_id INTEGER PRIMARY KEY REFERENCES activities (id) ON DELETE CASCADE,
    elapsed_s REAL,
    moving_s REAL,                        -- temps en mouvement (feux, pauses exclus)
    avg_hr REAL,
    max_hr REAL,
    trimp REAL,
    hrss REAL,                            -- 100 = 1 h à la LTHR
    zone1_s REAL, zone2_s REAL, zone3_s REAL, zone4_s REAL, zone5_s REAL,
    hr_best_20min REAL,                   -- meilleures FC moyennes tenues (estimation de la LTHR)
    hr_best_30min REAL,
    hr_best_60min REAL,
    terrain TEXT CHECK (terrain IN ('road', 'trail', 'indoor')),
    version INTEGER NOT NULL,
    params TEXT NOT NULL,                 -- FC repos, FC max, LTHR, sexe utilisés (JSON trié)
    computed_at TEXT NOT NULL
);
