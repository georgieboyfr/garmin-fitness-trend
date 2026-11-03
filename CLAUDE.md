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
- Le LLM ne calcule jamais rien ; aucun nom ni description issus de Strava ne lui est envoyé (table `strava_activities`, vue `activity_names`).
- Secrets uniquement dans `.env` (jamais commité), données dans `/data` (jamais commité).
- En cas d'ambiguïté, poser la question à Greg plutôt que supposer.
- « Terminé » = tests verts, image Docker construite, visible sur ordinateur et mobile, CHANGELOG à jour.
- Sessions courtes : une étape par session. Étape terminée = commit, suivi ci-dessous à jour, puis proposer à Greg de couper la session et lui donner la phrase de reprise : « Lis CLAUDE.md et reprends à la prochaine étape non cochée de la phase en cours. »
- Toute idée de Greg non implémentée est notée, datée, dans la section 7 du brief (« Idées notées en cours de route »).

## État d'avancement

- [x] Phase 0 — Audit et plan validés (2 novembre 2026, voir section 10 du brief)
- [x] Phase 1 — Socle (v0.1.1, en production sur le Synology le 3 novembre 2026)
  - [x] 1. Squelette : `app/`, migrations, tests, Dockerfile
  - [x] 2. Connexion Garmin depuis l'admin (`garminconnect` 0.3.20), admin protégée minimale
  - [x] 3. Synchro : reprise des FIT existants, métadonnées, incrémental
  - [x] 4. Parsing FIT vers Parquet, modèle de montre
  - [x] 5. D+ altimètre ou MNT (calibration croisée MNT/baromètre, voir section 10 du brief)
  - [x] 6. Noms et descriptions Strava, sorties sans montre importées
  - [x] 7. CI GitHub, image amd64/arm64 sur ghcr (v0.1.0 publiée le 3 novembre 2026)
  - [x] Bascule du Synology et vérification de l'admin
- [ ] Phase 2 — Statistiques (en cours)
  - [x] 1. Socle de l'interface : templates Jinja, navigation, thèmes clair/sombre, ECharts, accès protégé, page d'accueil
  - [x] 2. Métriques par activité versionnées : temps en mouvement, TRIMP/HRSS, zones FC (LTHR), route ou trail, estimation de la LTHR
  - [x] 3. Page Volume et régularité
  - [x] 4. Page Sorties : liste paginée
  - [x] 5. Records en fenêtre glissante, courbe allure-durée, VAM : page Performance
  - [x] 6. Page Forme : Fitness/Fatigue/Form, Efficiency Factor, découplage, temps par zone
  - [x] 7. Parcours similaires et comparaison des temps, fiche de chaque sortie (carte, profils, temps au km)
  - [x] 8. Détection des courses, validation dans l'admin, page Courses
  - [x] 8 bis. Fiche de sortie : intervalles (tours de la montre ou détection sur l'allure), classement des meilleurs efforts (3 novembre 2026)
  - [ ] 8 ter. Modifications notées par Greg (liste du 3 novembre 2026)
    - [x] a. Liste des sorties : sans « vs parcours », curseurs min–max de distance et de D+ (bornes de l'historique), nombre de sorties par page au choix (50 par défaut, mémorisé), pagination en haut et en bas avec la position, lisibilité
    - [x] b. Fiche de sortie : bloc « vs parcours » en bas, dernier km affiché « (682 m) », EF et découplage expliqués, zoom de la carte à la molette
    - [x] c. Performance : records dépliés réorganisés avec la FC moyenne, meilleurs temps par année cliquables (sortie) et année cliquable (top 10 de l'année), top 10 des montées sur 100, 200, 500 m, 1 km de D+
    - [ ] d. Forme, Courses, Volume : couleur des jauges selon l'état, périmètre du découplage indiqué (sorties plates d'au moins 1 h), info-bulle « vs habituel », bouton « aujourd'hui » sur les cumuls
    - [ ] e. VAP (allure ajustée à la pente, min/km) sur les sorties trail (méthode à valider avec Greg)
    - [ ] f. Indicateur de forme du jour sur la fiche de sortie : vitesse et FC face à l'attendu, en tenant compte des intervalles et du dénivelé (méthode à valider avec Greg)
  - [ ] 9. Vérification ordinateur et mobile, v0.2.0 (tag, CHANGELOG, image construite par la CI, mise à jour du Synology)
- [ ] Phase 3 — Estimateur
- [ ] Phase 4 — Coach
- [ ] Phase 5 — Extensions

## Commandes

- Tests : `.venv/Scripts/python -m pytest -q` ; lint : `.venv/Scripts/python -m ruff check app tests`
- Lancer en local : `DATA_DIR=./data-dev .venv/Scripts/python -m uvicorn app.main:app`
- Pas de Docker sur le poste de dev : l'image est construite par la CI (tag `vX.Y.Z`) ou sur le Synology.

## Structure

- `app/` : nouvelle application (FastAPI). `app/migrations/NNNN_nom.sql` : migrations, jamais modifiées une fois commitées.
- `tests/` : pytest. `tests/fit_builder.py` fabrique des FIT de test : jamais de vrai FIT de Greg dans le dépôt (traces GPS).
- `.github/workflows/` : CI (lint, tests) et publication de l'image sur tag `vX.Y.Z`.
- Dépôt : `github.com/georgieboyfr/garmin-fitness-trend` (public), poussé en SSH via l'alias `github-garmin-fitness-trend` (clé de déploiement du serveur de dev).

## Données locales (poste de dev)

`data/trend.db`, `data/fit/`, `data/series/`, `data/dem/`, `data/strava/`, `data/garmin_tokens/`. L'ancienne application (supprimée en 0.1.0, voir l'historique Git) utilisait `data/fitness.db` et `data/garth_tokens/`.
