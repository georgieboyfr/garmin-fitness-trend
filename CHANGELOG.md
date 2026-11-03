# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnement sémantique.

## [Non publié]

### Ajouté
- Pages de statistiques (templates Jinja, ECharts embarqué, thèmes clair/sombre/automatique, menu compact sur mobile, info-bulles), protégées par la session de l'admin : page d'accueil avec le cumul de l'année face à l'an dernier à la même date (distance, D+, km-effort, sorties), la courbe de distance cumulée, la dernière sortie et les totaux.
- Métriques de chaque sortie, recalculées si la version de l'algorithme ou les paramètres du `.env` changent : temps en mouvement, TRIMP et HRSS, temps par zone de FC (Friel, sur la LTHR), meilleures FC moyennes sur 20, 30 et 60 min, terrain (route, trail au-delà de 20 m de D+ par km, indoor).
- Admin : carte « Physiologie » avec la LTHR estimée (meilleure FC moyenne tenue une heure sur 12 mois) à côté de la valeur réglée, et la FC max observée.
- Page Volume et régularité : filtre route / trail, semaines actives, série en cours et plus longue série de semaines consécutives, D+ par km ; cumul jour par jour de toutes les années (distance, D+ ou km-effort) ; totaux, km-effort et D+ par km par année ; distance ou D+ par mois ; calendrier en heatmap par année.
- Page Sorties : liste paginée (25 par page) avec nom, description Strava, terrain, distance, D+, temps en mouvement, allure, FC moyenne et charge ; recherche dans le nom et la description, filtres par année et terrain, tri par colonne ; une carte par sortie sur mobile.
- Page Performance : records en fenêtre glissante sur 1, 3, 5, 10 km, semi et marathon (route et trail séparés, top 10, filtre par année, pics GPS filtrés), meilleur temps par année, courbe allure-durée par année (1 min à 2 h), VAM sur les montées de plus de 200 m (meilleure par année, top 10).
- Admin : LTHR, FC max et FC repos modifiables (bouton « Utiliser l'estimation », retour aux valeurs du `.env`), avec recalcul automatique des sorties.
- Page Forme : fitness, fatigue et forme (Banister, sur la charge HRSS) avec la zone de forme et la montée sur 7 jours, pic de fitness par année, temps par zone de FC par année (repère 80/20), Efficiency Factor des sorties faciles et plates (médiane mensuelle), découplage cardiaque des sorties de plus d'une heure sur le plat (repère 5 %).

### Modifié
- Hors de France, le D+ de Strava remplace celui du MNT Copernicus (qui compte les bâtiments) quand l'activité est appariée.
- Le terrain d'une sortie est recalculé quand son D+ change.
- Le cookie de session couvre tout le site (et plus seulement `/admin`) ; après connexion, retour à la page demandée.

## [0.1.1] - 2026-11-03

### Corrigé
- La racine du site (`/`) renvoyait « Not Found » : elle redirige vers l'admin en attendant les pages de statistiques (phase 2).

## [0.1.0] - 2026-11-03

Phase 1 (socle) : nouvelle application qui remplace l'ancien backend.

### Ajouté
- Brief de refonte, décisions de la phase 0, `CLAUDE.md`.
- Nouveau squelette `app/` : configuration par variables d'environnement, base SQLite avec migrations numérotées appliquées au démarrage, table des montres (Forerunner 35, 245, 255), point de santé `/health`.
- Admin protégée (`/admin`) : identifiant et mot de passe hashé argon2 dans `.env`, session en cookie HttpOnly signé (Secure derrière HTTPS), 5 essais par quart d'heure, protection CSRF.
- Connexion Garmin depuis l'admin, reprise de `wmts-gpx-heatmap` : code MFA saisi dans l'admin, choix de mémoriser ou non le mot de passe, `garminconnect` 0.3.20.
- Synchro Garmin : liste des activités mois par mois (premier import complet depuis une date réglable, puis incrémental depuis la dernière activité moins 30 jours), renommages et suppressions détectés, FIT originaux stockés dans `fit/<id>.fit` sans jamais être retéléchargés, FIT existants repris, pauses entre les appels.
- Synchro quotidienne dans le conteneur (heure réglable, rattrapage après un redémarrage), lancement manuel et réimport complet depuis l'admin, progression et historique des synchros.
- Lecture des FIT (fitdecode) après chaque synchro : modèle de montre et séries de points (temps, distance, position, altitude, FC, vitesse, cadence) dans `series/<id>.parquet`, version du lecteur enregistrée, lecture répartie sur plusieurs processus.
- D+ / D− recalculés : altimètre pour les montres à baromètre (Forerunner 255), sinon MNT le long de la trace GPS (IGN RGE ALTI en France, Copernicus GLO-30 ailleurs, profil mis en cache), D+ = 0 sans GPS. Rééchantillonnage tous les 10 m, filtre médian (3 points), seuil d'hystérésis par source (baromètre 1 m, MNT 3,5 m) ; version de l'algorithme et réglages enregistrés avec chaque résultat. Calibré pour coller au D+ de la montre à baromètre (0,4 % du D+ Garmin) et MNT recalé sur le baromètre (0,2 % au total).
- Admin : carte « Dénivelé » (D+ par source comparé à Garmin, réglages, recalcul sans appel à Garmin).
- Import de l'export Strava (zip complet ou `activities.csv` seul, en français ou en anglais) depuis le dossier surveillé `strava/` ou l'admin : noms et descriptions donnés dans Strava (les noms génériques sont ignorés), appariés aux activités Garmin par heure de départ ; sorties de course sans montre importées depuis leur trace (GPX ou FIT) ; seul l'export le plus récent compte.
- Admin : carte « Noms Strava » (envoi du fichier, noms repris, sorties sans activité Garmin, fichiers traités).
- Nouvelle base `trend.db` (l'ancienne `fitness.db` n'est pas touchée).
- Tests unitaires (pytest) et lint (ruff).
- CI GitHub Actions (lint et tests à chaque push) ; image Docker amd64 et arm64 publiée sur ghcr.io à chaque tag `v*`.
- `docker-compose.yml` utilise l'image publiée, conteneur sous l'utilisateur du NAS (`PUID` / `PGID`).

### Supprimé
- Ancienne application (`backend/`, page unique Chart.js, `generate_token.py`) : remplacée par `app/`.
- Dockerfile multi-étapes, utilisateur non root, healthcheck, version injectée au build.
