# CLAUDE.md

Statistiques de course à pied à partir des données Garmin, hébergées en Docker sur un Synology.

## Référence

Le cahier des charges est [`Stats running — idées pertinentes.md`](Stats%20running%20—%20idées%20pertinentes.md). Il fait foi : toute décision qui le contredit y est reportée (section 10) avant d'être codée. Section 7 = idées à ne pas implémenter sans demande explicite.

## Conventions

- Une phase à la fois (section 8 du brief), terminée, testée et taguée avant la suivante.
- Conventional Commits, petites étapes, versionnement sémantique, `CHANGELOG.md` à jour.
- Tests unitaires pour chaque calcul (D+, records, charge, détection des courses, estimations).
- Course à pied uniquement (`running`, `trail_running`, tapis) dans les statistiques et la charge.
- Le FIT brut est la source de vérité ; chaque étape est idempotente ; les calculs sont versionnés.
- Le LLM ne calcule jamais rien ; aucun nom issu de Strava ne lui est envoyé.
- Secrets uniquement dans `.env` (jamais commité), données dans `/data` (jamais commité).
- En cas d'ambiguïté, poser la question à Greg plutôt que supposer.
- « Terminé » = tests verts, image Docker construite, visible sur ordinateur et mobile, CHANGELOG à jour.

## État d'avancement

- [x] Phase 0 — Audit et plan validés (2 novembre 2026, voir section 10 du brief)
- [ ] Phase 1 — Socle (en cours)
  - [x] 1. Squelette : `app/`, migrations, tests, Dockerfile
  - [x] 2. Connexion Garmin depuis l'admin (`garminconnect` 0.3.20), admin protégée minimale
  - [ ] 3. Synchro : reprise des FIT existants, métadonnées, incrémental
  - [ ] 4. Parsing FIT vers Parquet, modèle de montre
  - [ ] 5. D+ altimètre ou MNT, calibré sur 3 parcours
  - [ ] 6. Noms Strava (archive attendue dans `data/strava/`)
  - [ ] 7. CI GitHub, image amd64/arm64 sur ghcr
- [ ] Phase 2 — Statistiques
- [ ] Phase 3 — Estimateur
- [ ] Phase 4 — Coach
- [ ] Phase 5 — Extensions

## Commandes

- Tests : `.venv/Scripts/python -m pytest -q` ; lint : `.venv/Scripts/python -m ruff check app tests`
- Lancer en local : `DATA_DIR=./data-dev .venv/Scripts/python -m uvicorn app.main:app`
- Pas de Docker sur le poste de dev : l'image est construite par la CI (étape 7) ou sur le Synology.

## Structure

- `app/` : nouvelle application (FastAPI). `app/migrations/NNNN_nom.sql` : migrations, jamais modifiées une fois commitées.
- `tests/` : pytest.
- `backend/` : ancienne application, encore utilisée par `docker-compose.yml` jusqu'à ce que `app/` la remplace ; à supprimer ensuite.

## Existant (avant refonte)

`backend/` : FastAPI + SQLite + fitparse + APScheduler + `garminconnect<0.3` (garth), page unique Chart.js. Données locales : `data/fitness.db`, `data/fit/` (662 FIT, 2020-12 → 2026-10), `data/garth_tokens/`.
