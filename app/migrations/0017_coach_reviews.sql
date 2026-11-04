-- Bilan du dimanche du coach (phase 4, étape 4) : une ligne par semaine passée en revue, avec les
-- deux réponses du coureur (qui orientent la semaine suivante) et le bilan figé une fois la semaine
-- close (JSON, coach_review.review).
CREATE TABLE coach_reviews (
    monday TEXT PRIMARY KEY,            -- lundi de la semaine passée en revue (AAAA-MM-JJ)
    next_week TEXT CHECK (next_week IN ('chargée', 'normale', 'libre')),
    feeling TEXT CHECK (feeling IN ('frais', 'normal', 'fatigué')),
    answered_at TEXT,
    summary TEXT,
    summarized_at TEXT
);
