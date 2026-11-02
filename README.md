# Garmin Fitness Trend

Récupère tes activités Garmin Connect (via FIT), calcule un stress score
(TRIMP / HRSS) par activité, et affiche une courbe Fitness / Fatigue / Form
(modèle de Banister, façon TrainingPeaks / Elevate) sur une page web,
le tout en Docker — sur le même principe que ton `strava-heatmap-proxy`.

## Ce que ça fait

- Se connecte à Garmin Connect et liste les activités de la période demandée
  (la librairie Garmin pagine automatiquement les résultats par blocs de 20)
- Télécharge le fichier FIT original de chaque activité
- Conserve chaque FIT dans `/data/fit/<activityId>.fit` (donc dans
  `./data/fit` sur l'hôte grâce au volume Docker)
- Calcule le TRIMP puis le HRSS à partir de tes échantillons de FC,
  ta FC max, ta FC repos et ta LTHR (formules Banister/TrainingPeaks)
- Agrège un stress score quotidien, et en déduit Fitness / Fatigue / Form
  jour par jour
- Sert une page web (Chart.js) avec :
  - la courbe Fitness / Fatigue / Form et ses zones d'entraînement
  - des cartes de synthèse (distance/dénivelé cumulés sur l'année, avec
    variation en % vs la même période l'an dernier)
  - un graphique de distance cumulée par année, toutes années superposées
    (pour comparer visuellement ta progression d'une année sur l'autre)
  - le même graphique pour le dénivelé cumulé
  - des histogrammes distance/dénivelé par mois, groupés par année
  - un encart records (plus longue distance, plus gros dénivelé, effort
    HRSS le plus intense)
  - le tableau des dernières activités (distance, D+, durée, FC, HRSS)
- Re-synchronise automatiquement toutes les `SYNC_INTERVAL_HOURS` heures

## Installation

1. **Configure tes paramètres physiologiques**

   ```bash
   cp .env.example .env
   ```

   Renseigne `HR_MAX`, `HR_REST`, `LTHR` et `SEX` (m/f) dans `.env`.
   Ce sont ces valeurs qui déterminent la précision du HRSS — une LTHR
   mal réglée fausse toute la courbe.

2. **Authentification Garmin (étape à faire une seule fois)**

   Renseigne `GARMIN_EMAIL` et `GARMIN_PASSWORD` dans `.env`, puis lance
   l'authentification **dans le conteneur** (mêmes versions de
   `garminconnect`/`garth` que le service en continu — pas de risque
   d'incompatibilité de version entre un script local et l'image Docker) :

   ```bash
   docker compose build
   docker compose run --rm garmin-fitness-trend python generate_token.py
   ```

   Saisis le code MFA si Garmin le demande. Le jeton est écrit dans
   `./data/garth_tokens` (volume partagé avec le service principal), qui
   pourra ensuite le recharger sans interaction à chaque synchro.

3. **Lancer le service**

   ```bash
   docker compose up -d
   ```

   La page est ensuite accessible sur `http://<ip-du-nas>:8090`.

4. **Exposition à l'extérieur**

   Comme pour `strava-heatmap-proxy`, ajoute une entrée de reverse proxy
   sur ton Synology pointant vers le port `8090` du conteneur, pour y
   accéder depuis ton téléphone hors réseau local.

## Limites connues / points à vérifier

- **API Garmin non testée en direct ici** : ce code a été écrit sans accès
  réseau à garmin.com dans cet environnement. Les noms de méthodes de
  `garminconnect`/`garth` (`login`, `download_activity`,
  `ActivityDownloadFormat.ORIGINAL`, gestion MFA) peuvent avoir légèrement
  changé selon la version installée — vérifie le dépôt
  [cyberjunky/python-garminconnect](https://github.com/cyberjunky/python-garminconnect)
  si une erreur apparaît au premier lancement.
- **RFTP/pace non utilisés** : le calcul se base uniquement sur la FC
  (HRSS), pas sur l'allure (RSS), car c'est la méthode la plus fiable
  sans capteur de puissance.
- **Activités sans FC** : ignorées (pas de stress score calculable).
- **Constantes 42/7 jours** : ce sont les valeurs standard du modèle de
  Banister, pas calibrées spécifiquement sur ton profil.

### Erreurs rencontrées et déjà corrigées

- **Flux d'authentification cassé (bug principal, v1)** : la première
  version utilisait deux clients `Garmin` différents (un pour recharger
  le token, un autre pour le login frais) avec un `dump()` manuel
  déconnecté du reste. Remplacé par un seul client construit avec
  `email/password/prompt_mfa`.
- **`FileNotFoundError: .../oauth1_token.json` au tout premier lancement
  (bug principal, v2)** : dans la version installée de `garminconnect`
  (`>=0.2.30,<0.3`), `client.login(tokenstore)` ne fait **aucun
  fallback automatique** vers un login complet si le dossier de token
  n'existe pas encore — il essaie juste de le charger et plante si rien
  n'est là (contrairement à d'autres versions/forks de la lib où ce
  fallback est intégré). `_login_with_fallback()` dans `garmin_sync.py`
  gère maintenant explicitement les deux cas : token déjà là → simple
  rechargement ; pas de token → `client.login()` sans argument (login
  complet email/mdp + MFA), puis `client.garth.dump(tokenstore)` à la
  main. `generate_token.py` et `get_client()` réutilisent tous les deux
  cette même fonction, pour ne jamais diverger.
- `AssertionError: assert isinstance(self._profile, dict)` dans
  `garth/http.py` au login : bug connu (issues #73, #312, #349 de
  cyberjunky/python-garminconnect), généralement causé par une version
  de `garminconnect`/`garth` trop ancienne face à un changement de l'API
  Garmin. Si ça revient après une mise à jour de Garmin, refais
  `docker compose build --no-cache` pour prendre la dernière version de
  la lib, puis régénère le token.
- `pydantic.ValidationError: ... for OAuth1Token` au chargement du token
  en cache : le fichier dans `./data/garth_tokens` a été écrit par une
  version différente de `garth`. Supprime le contenu de ce dossier
  (`rm -rf ./data/garth_tokens`) et relance `generate_token.py`.
- Si le compte a une vérification MFA active, le conteneur qui tourne en
  continu ne peut pas la saisir seul (pas de terminal) : c'est pour ça
  que l'authentification passe toujours par `generate_token.py`, lancé
  ponctuellement en interactif via `docker compose run`.
- **Note pour la suite** : `garminconnect` a connu une réécriture plus
  récente (0.3.x) qui abandonne complètement `garth` au profit d'un flux
  d'auth mobile différent (fichier `garmin_tokens.json`, méthodes
  `return_on_mfa`/`resume_login`). Si une future mise à jour bascule sur
  cette version, `garmin_sync.py` devra être adapté en conséquence — la
  fourchette `garminconnect>=0.2.30,<0.3` dans `requirements.txt` évite
  ce saut de version pour l'instant.

## Prochaines pistes possibles

- Ajouter une analyse par tronçon (montée/descente) en réutilisant les
  données GPS + FC du FIT
- Comparer plusieurs courses sur un même parcours
- Exporter les stress scores en CSV pour croiser avec tes plans
  d'entraînement Excel


## Correction importante : import qui semblait se bloquer

La version précédente téléchargeait les FIT **uniquement en mémoire** :

```text
Garmin -> raw bytes -> extraction ZIP -> fitparse -> SQLite
                                  └-> supprimé
```

Il n'y avait donc aucun `.fit` visible sur le NAS.

Elle avait également deux problèmes qui pouvaient donner l'impression que
l'import s'était arrêté :

1. les écritures SQLite n'étaient faites qu'à la fin de toute la synchro.
   Si un gros FIT bloquait le parsing, les activités déjà traitées restaient
   non validées en base ;
2. le bouton web et le scheduler pouvaient lancer deux synchronisations
   simultanément ;
3. les activités sans FC n'étaient pas mémorisées comme telles et pouvaient
   être retéléchargées à chaque synchro ;
4. le parser parcourait tous les champs de chaque `record` alors que seuls
   `timestamp` et `heart_rate` sont nécessaires.

La version corrigée :

- écrit le FIT de façon atomique dans `./data/fit/` ;
- réutilise un FIT déjà téléchargé après un redémarrage ;
- committe chaque activité immédiatement ;
- empêche les synchronisations concurrentes ;
- affiche dans `/api/status` l'ID de l'activité, l'étape et le chemin du FIT
  actuellement traité ;
- mémorise les activités sans FC ;
- réduit le travail du parser en ne lisant que `timestamp` et `heart_rate`.

### Où regarder pendant une synchro

```bash
docker compose logs -f garmin-fitness-trend
```

Tu verras notamment :

```text
[12/47] activité 123456789 : début ...
[123456789] téléchargement FIT...
[123456789] FIT écrit : 842.3 Ko
[123456789] parsing FIT...
[123456789] parsing terminé : 7214 échantillons FC
[12/47] activité 123456789 OK : HRSS=83.4
```

Et les FIT seront sur l'hôte dans :

```text
./data/fit/
```

### Importer tout l'historique

Le bouton **Importer l'historique** demande 3650 jours (10 ans).
La librairie `garminconnect` pagine les activités par blocs, donc il ne s'agit
pas d'une limite arbitraire de 20 activités.

Pour une première récupération très importante, laisse le conteneur tourner
jusqu'à la fin et surveille :

```bash
docker compose logs -f garmin-fitness-trend
```

Les activités déjà en base ne seront pas retraitées.
