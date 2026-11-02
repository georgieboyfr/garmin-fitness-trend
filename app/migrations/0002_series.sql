-- Lecture des FIT : une ligne par activité dont le FIT a été lu (ou a échoué).
-- Les séries elles-mêmes sont dans series/<activity_id>.parquet.
CREATE TABLE activity_series (
    activity_id INTEGER PRIMARY KEY REFERENCES activities (id) ON DELETE CASCADE,
    parser_version INTEGER NOT NULL,      -- fit_parser.PARSER_VERSION au moment de la lecture
    status TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    n_points INTEGER,
    has_gps INTEGER,
    has_altitude INTEGER,
    has_hr INTEGER,
    error TEXT,
    parsed_at TEXT NOT NULL
);
