# Garmin Fitness Trend

Statistiques de course à pied à partir des activités Garmin Connect, hébergées en
Docker sur un NAS Synology.

- Synchro Garmin quotidienne : métadonnées et FIT originaux, conservés une fois pour toutes.
- Lecture des FIT : séries de points (temps, distance, GPS, altitude, FC…) en Parquet.
- D+ recalculé : altimètre pour les montres à baromètre, sinon modèle numérique de
  terrain le long de la trace (IGN RGE ALTI en France, Copernicus ailleurs).
- Noms et descriptions repris de l'export de compte Strava ; sorties sans montre importées.
- Page d'admin protégée : compte Garmin, synchro, réglages du D+, import Strava.

Le cahier des charges et les décisions sont dans
[`Stats running — idées pertinentes.md`](Stats%20running%20—%20idées%20pertinentes.md),
l'historique des versions dans [`CHANGELOG.md`](CHANGELOG.md).

## Installation sur le Synology

1. **Dossier** : créer un dossier (par exemple `/volume1/docker/garmin-fitness-trend`)
   et y copier [`docker-compose.yml`](docker-compose.yml) et [`.env.example`](.env.example),
   renommé en `.env`.

2. **`.env`** : renseigner `HR_MAX`, `HR_REST`, `LTHR`, `SEX`, et `PUID` / `PGID`
   (propriétaire du dossier `data`, commande `id` en SSH ; souvent 1026 et 100 sur un
   Synology). Le conteneur ne tourne pas en root.

3. **Mot de passe de l'admin** :

   ```bash
   docker compose run --rm garmin-fitness-trend python -m app.auth
   ```

   Copier la ligne `ADMIN_PASSWORD_HASH='…'` affichée dans `.env`, en gardant les
   guillemets simples (le hash contient des `$`).

4. **Démarrer** :

   ```bash
   docker compose up -d
   ```

   L'application écoute sur le port 9193. Pour un accès depuis l'extérieur, ajouter une
   règle de reverse proxy HTTPS dans DSM vers ce port.

5. **Connecter Garmin** : ouvrir `/admin`, se connecter, puis renseigner les identifiants
   Garmin (code MFA saisi dans l'admin si Garmin le demande). Au choix : ne pas mémoriser
   le mot de passe (recommandé, seul le jeton de session est gardé) ou le mémoriser sur le
   serveur. Lancer ensuite le premier import.

   Le premier import liste l'historique mois par mois (quelques minutes), télécharge les FIT
   manquants, lit tous les FIT (10 à 15 min sur un DS218+) et interroge le service
   d'altitude IGN pour les montres sans baromètre (une dizaine de minutes). Tout cela n'a
   lieu qu'une fois ; ensuite, la synchro quotidienne ne traite que les nouvelles sorties.

## Export Strava

Demander l'export de compte sur strava.com (Paramètres > Mon compte > Télécharger ou
supprimer votre compte), puis déposer dans `data/strava/` (ou envoyer depuis l'admin) :

- l'archive `.zip` complète, au moins une fois : elle contient les traces des sorties
  faites sans montre Garmin, qui sont alors importées ;
- ensuite, le seul fichier `activities.csv` extrait de l'archive suffit pour les noms.

Seul l'export le plus récent compte ; un fichier déjà traité n'est pas relu.

## Mise à jour

Changer la version de l'image dans `docker-compose.yml`, puis :

```bash
docker compose pull && docker compose up -d
```

Les migrations de la base sont appliquées automatiquement au démarrage.

## Migration depuis l'ancienne version (backend Chart.js)

- Les FIT déjà téléchargés (`data/fit/`) sont repris tels quels, sans nouveau téléchargement.
- L'ancienne base `data/fitness.db` n'est pas utilisée (la nouvelle est `data/trend.db`) :
  elle peut être supprimée une fois la nouvelle version validée, de même que
  `data/garth_tokens/` et `data/sync.lock`.
- L'ancien conteneur tournait en root : rendre le dossier à l'utilisateur du NAS avant
  de démarrer la nouvelle version, par exemple `sudo chown -R 1026:100 data`.
- La session Garmin est à recréer une fois depuis l'admin (nouvelle version de la
  librairie `garminconnect`).

## Développement

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # .venv/bin/python sous Linux
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check app tests
DATA_DIR=./data-dev .venv/Scripts/python -m uvicorn app.main:app --port 8765
```

La CI (GitHub Actions) lance le lint et les tests à chaque push. Un tag `vX.Y.Z` construit
l'image pour amd64 et arm64 et la publie sur `ghcr.io/georgieboyfr/garmin-fitness-trend`
(`X.Y.Z`, `X.Y` et `latest`), avec la version affichée dans l'admin.

## Limites connues

- L'API Garmin Connect utilisée (`garminconnect`) n'est pas officielle : elle peut changer.
  Les appels sont espacés, les FIT sont conservés en local et les erreurs sont visibles
  dans l'admin.
- Le service d'altitude IGN demande une connexion Internet au moment du calcul ; en cas
  de coupure, le D+ est simplement reporté à la synchro suivante.
