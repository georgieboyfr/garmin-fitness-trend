-- Temps prévu chaque semaine pour les échéances du coach (phase 4, étape 5) : l'estimateur avec la
-- forme du dimanche soir, projeté sur la fitness que le plan donne le jour J.
CREATE TABLE coach_predictions (
    race_id INTEGER NOT NULL REFERENCES coach_races (id) ON DELETE CASCADE,
    week TEXT NOT NULL,                 -- lundi de la semaine
    form_day TEXT NOT NULL,             -- forme au soir de ce jour (le dimanche précédent)
    current_s REAL NOT NULL,            -- temps réaliste avec la forme de ce jour-là
    optimistic_s REAL NOT NULL,         -- temps projeté sur la fitness du jour J (fourchette)
    realistic_s REAL NOT NULL,
    prudent_s REAL NOT NULL,
    fitness_now REAL,
    fitness_race REAL,                  -- fitness projetée le matin de la course ; NULL hors du plan
    slope REAL NOT NULL,                -- part de temps gagnée par point de fitness (négative)
    replayed INTEGER NOT NULL DEFAULT 0,
    version TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (race_id, week)
);

-- objectif gardé par le coureur malgré un écart durable : semaine du choix (pas de nouvelle
-- proposition avant 3 nouvelles semaines d'écart)
ALTER TABLE coach_races ADD COLUMN target_kept_week TEXT;
