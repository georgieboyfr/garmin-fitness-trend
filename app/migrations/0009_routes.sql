-- Signature de la trace de chaque sortie (routes.py) et parcours auquel elle appartient.
-- Les parcours sont recalculés entièrement à chaque traitement (rapide) : route_id est l'id
-- de la première sortie du parcours.
CREATE TABLE activity_tracks (
    activity_id INTEGER PRIMARY KEY REFERENCES activities (id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    distance_m REAL NOT NULL,
    signature BLOB NOT NULL               -- float64 (points x 2) : lat, lon
);

CREATE TABLE activity_routes (
    activity_id INTEGER PRIMARY KEY REFERENCES activities (id) ON DELETE CASCADE,
    route_id INTEGER NOT NULL
);
CREATE INDEX idx_routes_route ON activity_routes (route_id);
