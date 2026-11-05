# CLAUDE.md

Statistiques de course à pied à partir des données Garmin, hébergées en Docker sur un Synology.

## Référence

Le cahier des charges est [`Stats running — idées pertinentes.md`](Stats%20running%20—%20idées%20pertinentes.md). Il fait foi : toute décision qui le contredit y est reportée (section 10) avant d'être codée. Section 7 = idées à ne pas implémenter sans demande explicite.

## Conventions

- Une phase à la fois (section 8 du brief), terminée, testée et taguée avant la suivante.
- Conventional Commits, petites étapes, versionnement sémantique, `CHANGELOG.md` à jour.
- À chaque version poussée (tag `vX.Y.Z`), `README.md` mis à jour et poussé aussi : fonctionnalités, feuille de route, limites (demande de Greg du 3 novembre 2026).
- Tests unitaires pour chaque calcul (D+, records, charge, détection des courses, estimations).
- Course à pied uniquement (`running`, `trail_running`, tapis) dans les statistiques et la charge.
- Le FIT brut est la source de vérité ; chaque étape est idempotente ; les calculs sont versionnés.
- Le LLM ne calcule jamais rien ; aucun nom ni description issus de Strava ne lui est envoyé (table `strava_activities`, vue `activity_names`).
- Secrets uniquement dans `.env` (jamais commité), données dans `/data` (jamais commité).
- En cas d'ambiguïté, poser la question à Greg plutôt que supposer.
- « Terminé » = tests verts, image Docker construite, visible sur ordinateur et mobile, CHANGELOG à jour.
- Fin de chaque étape, avant de proposer de couper : serveur de test lancé sur les données locales et onglet Chrome ouvert pour Greg sur la page concernée (voir Commandes), demande de Greg du 4 novembre 2026.
- Sessions courtes : une étape par session. Étape terminée = commit, suivi ci-dessous à jour, puis proposer à Greg de couper la session et lui donner la phrase de reprise : « Lis CLAUDE.md et reprends à la prochaine étape non cochée de la phase en cours. »
- Toute idée de Greg non implémentée est notée, datée, dans la section 7 du brief (« Idées notées en cours de route »).
- Les calculs s'adaptent aux données de chaque coureur et évoluent avec elles : pas de constante calée sur les données de Greg, tout doit marcher pour quelqu'un d'autre (principe de Greg du 4 novembre 2026, section 10 du brief).

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
- [x] Phase 2 — Statistiques (v0.2.0, en production sur le Synology le 3 novembre 2026)
  - [x] 1. Socle de l'interface : templates Jinja, navigation, thèmes clair/sombre, ECharts, accès protégé, page d'accueil
  - [x] 2. Métriques par activité versionnées : temps en mouvement, TRIMP/HRSS, zones FC (LTHR), route ou trail, estimation de la LTHR
  - [x] 3. Page Volume et régularité
  - [x] 4. Page Sorties : liste paginée
  - [x] 5. Records en fenêtre glissante, courbe allure-durée, VAM : page Performance
  - [x] 6. Page Forme : Fitness/Fatigue/Form, Efficiency Factor, découplage, temps par zone
  - [x] 7. Parcours similaires et comparaison des temps, fiche de chaque sortie (carte, profils, temps au km)
  - [x] 8. Détection des courses, validation dans l'admin, page Courses
  - [x] 8 bis. Fiche de sortie : intervalles (tours de la montre ou détection sur l'allure), classement des meilleurs efforts (3 novembre 2026)
  - [x] 8 ter. Modifications notées par Greg (liste du 3 novembre 2026)
    - [x] a. Liste des sorties : sans « vs parcours », curseurs min–max de distance et de D+ (bornes de l'historique), nombre de sorties par page au choix (50 par défaut, mémorisé), pagination en haut et en bas avec la position, lisibilité
    - [x] b. Fiche de sortie : bloc « vs parcours » en bas, dernier km affiché « (682 m) », EF et découplage expliqués, zoom de la carte à la molette
    - [x] c. Performance : records dépliés réorganisés avec la FC moyenne, meilleurs temps par année cliquables (sortie) et année cliquable (top 10 de l'année), top 10 des montées sur 100, 200, 500 m, 1 km de D+
    - [x] d. Forme, Courses, Volume : couleur des jauges selon l'état, périmètre du découplage indiqué (sorties plates d'au moins 1 h), info-bulle « vs habituel », bouton « aujourd'hui » sur les cumuls
    - [x] e. VAP (allure ajustée à la pente, min/km) sur les sorties trail (formule de Minetti, choix de Greg)
    - [x] f. Indicateur de forme du jour sur la fiche de sortie : vitesse et FC face à l'attendu, en tenant compte des intervalles et du dénivelé (FC attendue à la vitesse, choix de Greg)
  - [x] 9. Vérification ordinateur et mobile, v0.2.0 (tag, CHANGELOG, image construite par la CI, mise à jour du Synology)
    - [x] Commit et tag `v0.2.0` (3 novembre 2026), pages vérifiées en local sur ordinateur et en largeur mobile
    - [x] Push du tag, image construite par la CI, mise à jour du Synology et vérification sur le téléphone (3 novembre 2026)
- [x] Phase 3 — Estimateur (v0.3.0, 3 novembre 2026 ; section 5 du brief ; erreur moyenne mesurée sur les courses passées affichée)
  - [x] 1. Forme actuelle : profil calculé sur les 6 à 12 dernières semaines (courbe allure-durée récente, VAM, allure en descente, fitness, EF), fonction pure versionnée, visible sur une page Estimateur minimale (3 novembre 2026)
  - [x] 2. Route : Riegel à exposant personnel calé sur les meilleurs efforts récents, fourchette optimiste / réaliste / prudent, allure cible ; saisie d'une distance (et D+ éventuel), « si je courais maintenant » (3 novembre 2026 ; choix à valider par Greg, section 10 du brief)
  - [x] 3. Validation route : estimateur rejoué sur les courses confirmées avec la forme de la veille, erreur moyenne affichée (3 novembre 2026 : exposant standard 1,06 retenu par Greg, 4,4 % d'erreur sur 3 courses, estimation encore trop lente, biais non corrigé)
  - [x] 4. Modèle allure-pente personnel (allure selon la pente à effort égal, montée et descente), calé sur les sorties ; comparé à la VAP de Minetti (3 novembre 2026 ; choix à valider par Greg, section 10 du brief)
  - [x] 5. Trail sur GPX : import du GPX, découpage en tronçons homogènes, temps par tronçon (modèle allure-pente et facteur de fatigue tiré de la courbe allure-durée), profil et temps de passage (3 novembre 2026 ; choix à valider par Greg, section 10 du brief)
  - [x] 6. Ravitaillements saisis sur un GPX (proposés d'après ses waypoints), arrêts comptés dans les temps de passage (3 novembre 2026 ; trail sans GPX abandonné et barrières horaires reportées par Greg, choix à valider, section 10 du brief)
  - [x] 7. Validation trail : rejeu sur les courses trail passées (leur propre trace sert de GPX), erreur moyenne affichée (3 novembre 2026 : temps total visé, arrêts tirés des courses passées, choix de Greg ; 5,3 % d'erreur sur 5 courses, modèle sur 12 mois ; choix à valider, section 10 du brief)
  - [x] 8. Comparaison avec les courses passées les plus proches (distance, D+) et effet de la forme (temps estimé avec plus ou moins de fitness le jour J) (3 novembre 2026 : −0,81 % de temps par point de fitness sur l'historique ; choix à valider, section 10 du brief)
  - [x] 9. Courses suivies, indépendantes du coach : liste (GPX ou distance, date facultative), prédiction enregistrée chaque semaine, graphique par course avec fourchette et objectif, vue d'ensemble sur 4 semaines (3 novembre 2026 ; enregistrement le lundi et 12 semaines rejouées à l'ajout, choix de Greg ; reste à valider, section 10 du brief)
  - [x] 10. Après la course : activité reliée automatiquement, écart prédiction / résultat, calibration (3 novembre 2026 ; correction proposée et activée dans l'admin, choix de Greg ; reste à valider, section 10 du brief)
  - [x] 10 bis. Fiche d'une course réalisée : bouton qui lance l'estimation sur la trace de la sortie (forme de la veille et forme d'aujourd'hui), graphique de l'écart cumulé au fil des km (choix de Greg) (demande de Greg du 3 novembre 2026, fait le même jour)
  - [x] 10 ter. Niveau ajusté par la FC (vitesse à 85 % de la LTHR, références sur 4 mois), réglages figés et vraie précision séparée de l'erreur sur les courses de réglage (3 novembre 2026, choix de Greg ; section 10 du brief)
  - [x] 11. Vérification ordinateur et mobile, v0.3.0
    - [x] Pages vérifiées en local sur ordinateur et à 390 px de large (aucun débordement, menu responsive), commit et tag `v0.3.0`, push, image construite par la CI (3 novembre 2026)
    - [x] Mise à jour du Synology et vérification sur le téléphone (Greg, 4 novembre 2026)
  - [x] 12. VAP selon la courbe de Strava au lieu de Minetti (4 novembre 2026, demande de Greg ; v0.4.0)
  - [x] 13. Limites à 95 % (Bland-Altman) dans la précision de l'estimateur, après comparaison avec la thèse de L. Lerebourg (4 novembre 2026, section 10 du brief ; v0.4.0)
  - [x] 14. Indice de confiance de chaque estimation, avec ses raisons (4 novembre 2026, demande de Greg, section 10 du brief ; v0.4.0)
  - [x] 15. Page Forme : VMA, VO2max estimée, FC au seuil (% de la FC max) et allure au seuil (demande de Greg du 4 novembre 2026, fait le même jour, section 10 du brief ; v0.4.0)
  - [x] 16. v0.4.0 : tag, CHANGELOG, README, image construite par la CI (4 novembre 2026) ; reste la mise à jour du Synology et la vérification sur le téléphone (Greg)
  - Points à trancher avec Greg au fil des étapes : terrain technique et chaleur (étape 6 ou plus tard), forme projetée à la date de la course (le coach de la phase 4 la fournira ; en attendant, forme actuelle maintenue)
  - Tranché : l'estimateur a son propre onglet dans le menu (3 novembre 2026)
- [ ] Phase 4 — Coach (section 6 du brief ; terminé quand un plan est suivi sur 2 semaines réelles sans intervention manuelle ; v1.0.0). Logique de plan à base de règles explicites, en fonctions pures testées ; tout reste utilisable sans LLM
  - [x] 1. Calendrier du coach, séparé des courses suivies (choix de Greg du 4 novembre 2026, section 10 du brief) : échéances A, B ou C (date obligatoire), pré-remplissage possible depuis une course suivie ; démarrage en 5 minutes (disponibilités et habitudes facultatives, déduites de l'historique sinon ; objectif proposé par l'estimateur, accepté ou modifié) (fait le 4 novembre 2026, onglet Coach)
  - [x] 2. Plan périodisé vers une course A : à rebours depuis la date (foncier, développement, spécifique, affûtage de 1 à 2 semaines), charge pilotée par la fitness visée le jour J (hausse hebdomadaire plafonnée, cycle 3 semaines de charge et 1 allégée), séances typées (footing, sortie longue, seuil, fractionné, côtes ; D+ et sorties longues proches du profil pour un trail), 80/20, jamais deux séances dures d'affilée, un jour de repos par semaine (fait le 4 novembre 2026, réglages de Greg : +5 de fitness par semaine, affûtage selon la durée, fitness la plus haute atteignable, allégée −30 % ; section 10 du brief)
  - [x] 3. Écran « Cette semaine » : séances prévues, séances faites détectées automatiquement dans les activités synchronisées, séance clé et ce qui peut sauter, prochaines courses avec compte à rebours et temps prévu (fait le 4 novembre 2026, sous-onglet par défaut du Coach ; semaine figée le lundi, choix à valider, section 10 du brief)
  - [x] 4. Bilan du dimanche (verdict sans jugement, séances faites face aux prévues, charge réalisée face à la prévue, orientation de la semaine suivante) et réajustement automatique : semaine chargée, séances manquées jamais rattrapées, fatigue ou forme trop basse, avance sur le plan ; notification le dimanche soir (fait le 4 novembre 2026 : ntfy, verdict séances et charge, semaine chargée à un tiers des séances en moins, choix de Greg ; plan ancré à sa semaine de départ ; reste à valider, section 10 du brief)
  - [x] 5. Temps prévu chaque semaine avec la fitness projetée au jour J (remplace la forme actuelle maintenue en phase 3), courbe face à l'objectif, objectif réajusté si l'écart dure 3 semaines (fait le 4 novembre 2026 : fitness la plus haute des 2 semaines avant la course, choix à valider, section 10 du brief)
  - [x] 6. Plusieurs courses : priorités A (affûtage complet), B (mini-affûtage), C (semaine allégée), récupération après chaque course selon durée, D+ et intensité, conflits signalés avec solutions au choix de Greg, résultat d'une course qui met à jour les suivantes, plan reconstruit après la course A (fait le 4 novembre 2026, avant l'étape 3 à la demande de Greg ; repères à valider, section 10 du brief)
  - [x] 7. Maintien de forme sans course prévue : plage de fitness tirée des 8 à 12 dernières semaines, semaine type, reprise progressive si la fitness passe durablement sous la plage ; bascules automatiques maintien, préparation, récupération (fait le 4 novembre 2026 ; repères à valider, section 10 du brief)
  - [x] 8. Orientation modifiable (maintien, reprise, foncier, vitesse, route longue, trail) et semaines particulières (vacances, Noël, déplacement, semaine chargée, maladie, blessure) à trois niveaux, avec l'effet affiché sur les échéances ; progression suspendue en cas de douleur (fait le 4 novembre 2026 ; repères à valider, section 10 du brief)
  - [x] 9. Disponibilités et habitudes (sortie habituelle gardée à sa place avec un rôle selon la phase), deux propositions par séance, bibliothèque de séances, variété des séances et des parcours habituels, indicateur de monotonie (fait le 4 novembre 2026 ; repères à valider, section 10 du brief)
  - [x] 9 bis. Fiche d'une échéance : nom cliquable, lien vers l'estimateur, temps de passage km par km pour un temps au choix (demande de Greg du 4 novembre 2026, fait le même jour)
  - [x] Pré-version v1.0.0-alpha (étapes 1 à 9 bis) pour test sur le Synology avant la fin de la phase (demande de Greg du 4 novembre 2026 ; image `1.0.0-alpha`, pas `latest`)
  - [x] 9 ter. Retours de Greg sur le plan (liste du 5 novembre 2026, fait le même jour) : optionnelles, FC d'endurance et VMA réglables dans l'admin, retour au calme, sorties longues, charge par séance, renfo, séances selon la course et la phase, programme du jour (section 10 du brief)
  - [ ] 10. Unités au choix (allure, zones de FC, sensation ; durée ou distance), séance de remplacement avec pourcentage de compatibilité et suggestion d'ajustement, bilan de semaine détaillé
  - [ ] 11. Vérification ordinateur et mobile, plan suivi 2 semaines réelles sans intervention, v1.0.0
  - Points à trancher avec Greg au fil des étapes : pondérations et seuils des règles (hausse de charge, durée d'affûtage, compatibilité) ; tranché : onglet « Coach » dans le menu, notification par ntfy (4 novembre 2026)
  - Hors phase 4 (section 8 du brief, qui fait foi sur la section 6) : envoi des séances vers le calendrier Garmin en phase 5 ; coach conversationnel en phase 4 bis
- [ ] Phase 4 bis — Coach conversationnel (section 6 du brief, LLM OVHcloud AI Endpoints ; accès et modèles à vérifier avant, section 9)
  - [ ] 1. Saisie rapide en langage naturel en haut de l'accueil et de « Cette semaine » : étiquettes modifiables avant validation (fatigue, sommeil, douleur, motivation, disponibilités, période particulière), boutons rapides sans LLM, dictée vocale du navigateur, journal de forme affiché sur la page Forme
  - [ ] 2. Coach conversationnel : le LLM traduit la discussion en actions structurées, le moteur de règles recalcule, le LLM explique ; rien n'est appliqué sans accord de Greg ; initiative mesurée (bilan du dimanche, alerte de fatigue, mot sur un record), mémoire des préférences
  - [ ] 3. Vérification ordinateur et mobile, version mineure
- [ ] Phase 5 — Extensions

## Commandes

- Tests : `.venv/Scripts/python -m pytest -q` ; lint : `.venv/Scripts/python -m ruff check app tests`
- Lancer en local : `DATA_DIR=./data-dev .venv/Scripts/python -m uvicorn app.main:app`
- Serveur de test pour Greg : en arrière-plan, sur `127.0.0.1:8000` avec `DATA_DIR=./data` et les variables de `.env` ; identifiant `greg` et mot de passe temporaire généré à la session (`secrets.token_urlsafe`, haché par `app.auth.hash_password`), passé au seul processus via `ADMIN_USER` et `ADMIN_PASSWORD_HASH`, jamais écrit dans `.env` ni dans le dépôt ; le donner à Greg dans la conversation. Ouvrir l'onglet sur `http://localhost:8000/<page>` et redémarrer le serveur après chaque modification du code Python.
- Pas de Docker sur le poste de dev : l'image est construite par la CI (tag `vX.Y.Z`) ou sur le Synology.

## Structure

- `app/` : nouvelle application (FastAPI). `app/migrations/NNNN_nom.sql` : migrations, jamais modifiées une fois commitées.
- `tests/` : pytest. `tests/fit_builder.py` fabrique des FIT de test : jamais de vrai FIT de Greg dans le dépôt (traces GPS).
- `.github/workflows/` : CI (lint, tests) et publication de l'image sur tag `vX.Y.Z`.
- Dépôt : `github.com/georgieboyfr/garmin-fitness-trend` (public), poussé en SSH via l'alias `github-garmin-fitness-trend` (clé de déploiement du serveur de dev).

## Données locales (poste de dev)

`data/trend.db`, `data/fit/`, `data/series/`, `data/dem/`, `data/strava/`, `data/garmin_tokens/`, `data/gpx/` (parcours importés dans l'estimateur). L'ancienne application (supprimée en 0.1.0, voir l'historique Git) utilisait `data/fitness.db` et `data/garth_tokens/`.
