-- Tests de VMA (demi-Cooper : 6 min le plus loin possible) détectés dans les sorties, confirmés ou
-- rejetés dans l'admin comme les courses ; un test confirmé donne une VMA datée, référence de
-- l'estimateur et des allures du coach.
CREATE TABLE vma_tests (
    activity_id INTEGER PRIMARY KEY REFERENCES activities (id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('confirmed', 'rejected')),
    decided_at TEXT NOT NULL
);
