-- Courses confirmées ou rejetées par Greg (les candidates, elles, sont calculées à la volée).
CREATE TABLE races (
    activity_id INTEGER PRIMARY KEY REFERENCES activities (id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('confirmed', 'rejected')),
    decided_at TEXT NOT NULL
);
