-- Meilleurs efforts de chaque sortie (bests.py), calculés avec les métriques :
--   distance : key = distance (m), value = meilleur temps (s), start_s = départ dans la sortie
--   duration : key = durée (s), value = plus grande distance parcourue (m)
--   climb    : key = 0, value = meilleure VAM (m/h) sur une montée de plus de 200 m, extra = D+ (m)
CREATE TABLE activity_bests (
    activity_id INTEGER NOT NULL REFERENCES activities (id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('distance', 'duration', 'climb')),
    key REAL NOT NULL,
    value REAL NOT NULL,
    start_s REAL,
    extra REAL,
    PRIMARY KEY (activity_id, kind, key)
);
CREATE INDEX idx_bests_kind ON activity_bests (kind, key, value);
