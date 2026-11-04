-- Choix du coureur entre les deux propositions d'une séance du coach (phase 4, étape 9) : la
-- seconde proposition remplace celle du coach ce jour-là, tant que la séance prévue reste la même.
CREATE TABLE coach_choices (
    day TEXT PRIMARY KEY,               -- date de la séance (AAAA-MM-JJ)
    label TEXT NOT NULL,                -- libellé de la proposition du coach au moment du choix
    chosen_at TEXT NOT NULL
);
