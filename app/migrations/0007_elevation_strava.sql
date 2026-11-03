-- Nouvelle source de D+ : « strava ». Hors de France, le MNT Copernicus est un modèle de
-- surface (bâtiments compris) qui surestime le D+ en ville : le D+ de Strava est alors
-- préféré quand l'activité est appariée. D− inconnu dans ce cas (loss_m facultatif).
-- La table est recréée vide : tout est recalculé au traitement suivant, sans réinterroger
-- l'IGN (profils MNT en cache).
DROP TABLE activity_elevation;
CREATE TABLE activity_elevation (
    activity_id INTEGER PRIMARY KEY REFERENCES activities (id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('barometer', 'dem', 'strava', 'none')),
    dem_provider TEXT,                    -- ign, copernicus ou ign+copernicus
    gain_m REAL NOT NULL,
    loss_m REAL,
    algo_version INTEGER NOT NULL,        -- elevation.ALGO_VERSION
    params TEXT NOT NULL,                 -- réglages utilisés (JSON trié)
    computed_at TEXT NOT NULL
);
