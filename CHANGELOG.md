# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnement sémantique.

## [Non publié]

### Ajouté
- Brief de refonte, décisions de la phase 0, `CLAUDE.md`.
- Nouveau squelette `app/` : configuration par variables d'environnement, base SQLite avec migrations numérotées appliquées au démarrage, table des montres (Forerunner 35, 245, 255), point de santé `/health`.
- Admin protégée (`/admin`) : identifiant et mot de passe hashé argon2 dans `.env`, session en cookie HttpOnly signé (Secure derrière HTTPS), 5 essais par quart d'heure, protection CSRF.
- Connexion Garmin depuis l'admin, reprise de `wmts-gpx-heatmap` : code MFA saisi dans l'admin, choix de mémoriser ou non le mot de passe, `garminconnect` 0.3.20.
- Synchro Garmin : liste des activités mois par mois (premier import complet depuis une date réglable, puis incrémental depuis la dernière activité moins 30 jours), renommages et suppressions détectés, FIT originaux stockés dans `fit/<id>.fit` sans jamais être retéléchargés, FIT existants repris, pauses entre les appels.
- Synchro quotidienne dans le conteneur (heure réglable, rattrapage après un redémarrage), lancement manuel et réimport complet depuis l'admin, progression et historique des synchros.
- Lecture des FIT (fitdecode) après chaque synchro : modèle de montre et séries de points (temps, distance, position, altitude, FC, vitesse, cadence) dans `series/<id>.parquet`, version du lecteur enregistrée, lecture répartie sur plusieurs processus.
- Nouvelle base `trend.db` (l'ancienne `fitness.db` n'est pas touchée).
- Tests unitaires (pytest) et lint (ruff).
- Dockerfile multi-étapes, utilisateur non root, healthcheck, version injectée au build.
