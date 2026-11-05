# Fitness Trend : brief de refonte pour Claude Code

Nov 1, 2026 · @Greg

Cahier des charges de la refonte d'un projet existant de statistiques de course à pied à partir des données Garmin, écrit pour être exécuté par Claude Code phase par phase.

## 0. Mode d'emploi pour Claude Code

- **Lecture** : sections 1 à 3 = cadre et décisions à respecter ; 4 à 6 = fonctionnalités (phases 2 à 4 de la section 8) ; 7 = idées pour plus tard, à ne pas implémenter sans demande ; 8 = plan de livraison ; 9 = points à vérifier avant de coder.
- **Une phase à la fois** (section 8), terminée, testée et taguée avant de passer à la suivante.
- **En cas d'ambiguïté**, poser la question plutôt que supposer. Les points de la section 9 se vérifient dans le code ou la documentation avant d'implémenter.
- **Conventions** : Conventional Commits, petites étapes, tests unitaires pour chaque calcul (D+, records, charge, détection des courses, estimations), `README` à jour (installation, `.env`, mise à jour), et un `CLAUDE.md` à la racine du dépôt qui pointe vers ce brief et résume conventions et état d'avancement, pour que chaque nouvelle session reparte avec le contexte. Ce brief reste la référence : toute décision qui le contredit y est reportée avant d'être codée.
- **« Terminé »** = tests verts, image Docker construite, fonctionnalité visible dans l'interface sur ordinateur et mobile, `CHANGELOG.md` mis à jour.

### Point de départ

On part de la stack actuelle pour garder ce qui fonctionne, sans s'interdire une refonte profonde quand elle est justifiée.

1. **Auditer le projet existant** avant toute modification : stack, structure, dépendances, ce qui fonctionne, dette technique.
2. **Proposer un plan module par module** (synchro, parsing, calculs, stockage, interface) : garder, refactorer ou réécrire, avec la raison de chaque choix. Faire valider ce plan avant de coder.
3. **Garder la stack par défaut.** En changer seulement si elle bloque une exigence (responsive, admin, Docker, versionnement) ou si la réécriture coûte moins cher que l'adaptation, et le dire explicitement.

## 1. Contexte et décisions déjà prises

Ces choix sont arrêtés : ne pas les remettre en cause sans le signaler.

- **Utilisateur** : Greg, coureur amateur route et trail, vie de famille, semaines inégales. Tout doit être simple et automatique. Course à pied uniquement (route, trail, tapis) : les autres sports, vélo compris, sont ignorés dans les statistiques et la charge.
- **Hébergement** : Docker sur un NAS Synology, accès distant via le reverse proxy.
- **Source des activités** : Garmin Connect, via la librairie déjà utilisée par le projet : elle télécharge les FIT et les métadonnées, premier import compris. Rien d'autre côté Garmin. Les activités partent automatiquement de Garmin vers Strava dès la synchro.
- **Strava** : pas d'abonnement, donc pas d'API. Strava ne fournit que les noms des activités, via l'export de compte Strava : c'est le seul fichier importé à la main.
- **Dénivelé** : l'altimètre fait foi quand la montre en a un, sinon MNT. Le D+ est toujours recalculé par l'application.
- **Courses** : ni Garmin ni Strava ne les identifient comme courses ; l'application les détecte automatiquement, puis Greg les confirme dans l'admin.
- **LLM** : pour dialoguer avec Greg et mettre en mots des résultats, jamais pour calculer.

## 2. Données et calculs

Garmin reste la source unique des activités ; le D+ est recalculé par le script, et Strava ne fournit que les noms, via l'export de compte.

### Récupération des données

Le FIT brut est la source de vérité : téléchargé une seule fois, tout le reste en est recalculé. Chaque étape est idempotente, donc relançable sans risque.

**Déclenchement** : une tâche planifiée quotidienne dans le conteneur, plus le dossier surveillé pour l'export Strava.

1. **Synchro Garmin incrémentale**
   - Connexion via `garminconnect`, avec la session mise en cache sur le volume pour éviter de se reconnecter à chaque fois.
   - Liste des activités depuis la dernière date connue en base (`get_activities_by_date`), plus les 30 derniers jours pour capter les renommages et suppressions.
   - Pour chaque activité absente en base : téléchargement du FIT original (zip), stocké tel quel dans `/data/fit/<activity_id>.fit`. Jamais retéléchargé ensuite.
   - Métadonnées enregistrées en base : ID, date de départ (GMT), type, nom Garmin, distance, durée.
2. **Premier import** : même logique sur tout l'historique, par tranches d'un mois, avec un délai entre les appels. Une interruption reprend là où elle s'est arrêtée, puisque seules les activités absentes sont téléchargées.
3. **Parsing du FIT** : modèle de montre, puis les séries temps, distance, lat/lon, altitude, FC, stockées par activité (Parquet ou table SQLite).
4. **Altitude et D+** : choix altimètre ou MNT, puis calcul (voir Dénivelé), enregistrés avec la version de l'algorithme.
5. **Métriques par activité** : HRSS, meilleurs segments, VAM, Efficiency Factor, découplage, temps par zone. Versionnées, recalculées seulement si la version change.
6. **Noms** : quand un zip d'export Strava est déposé, lecture de `activities.csv`, correspondance par heure de départ, puis renommage dans Garmin ou table locale des noms.
7. **Agrégats** : Fitness/Fatigue/Form jour par jour, cumuls, records et classements, recalculés entièrement à chaque passage (rapide à partir des métriques stockées).
8. **Génération de la page web** à partir de la base.

**Stockage** : une base SQLite et le dossier des FIT sur un volume du Synology, monté dans le conteneur.

### Dénivelé

- **Montre avec altimètre** : l'altitude enregistrée fait foi, mais le D+ est recalculé (le cumul Garmin additionne le bruit du baromètre).
- **Montre sans altimètre** : altitude tirée d'un MNT local dans le conteneur (RGE ALTI IGN pour la France, Copernicus GLO-30 ailleurs), à partir des lat/lon du FIT.
- **Sans GPS** (tapis, indoor) : D+ = 0.
- **Détection de l'altimètre** : table des modèles de montre (`file_id.garmin_product`) équipés d'un baromètre. La présence de `enhanced_altitude` ne suffit pas.
- **Algorithme commun** : rééchantillonnage tous les 10 à 25 m, filtre médian, seuil d'hystérésis propre à chaque source (environ 2,5 m baro, 4 m MNT, à calibrer sur des parcours au D+ connu).
- **Stockage** : ID d'activité, source d'altitude, D+, D−, version de l'algorithme. Changer les seuils = incrémenter la version et tout recalculer.

### Noms des activités

- L'API Strava n'est pas utilisée : depuis juin 2026, un script personnel exige un abonnement Strava.
- **Export de compte Strava** demandé à la main une fois par mois (`activities.csv`). L'automatiser demanderait du scraping, interdit par les conditions Strava.
- **Dossier surveillé sur le Synology** : déposer le zip déclenche l'import.
- **Correspondance** par heure de départ, tolérance de 2 min.
- **Renommage dans Garmin Connect** via `garminconnect` (`set_activity_name`), avec un délai entre les appels et un premier passage en simulation. Alternative : une table locale `activity_id → nom`.
- En attendant l'export suivant, les activités récentes gardent le titre Garmin.

### Records

- Meilleurs segments en fenêtre glissante dans les activités, pas activités entières.
- Filtrage des pics GPS avant calcul.
- Classement séparé route et trail (seuil de D+ par km).

### Détection automatique des courses

Un score combine plusieurs indices ; au-delà d'un seuil, l'activité est proposée comme course probable.

- **Nom** (issu de Strava) : mots-clés comme marathon, semi, trail du, trail de, ultra, 10 km de, corrida, cross. Liste modifiable dans l'admin.
- **Effort cardiaque** : FC moyenne élevée pour la durée de la sortie, et charge (HRSS) par heure bien au-dessus de tes sorties habituelles.
- **Distance ronde** : 5, 10, 21,1 ou 42,2 km à quelques pourcents près, courue à un effort soutenu.
- **Allure** : nettement plus rapide que tes sorties habituelles sur une distance comparable, ou record ou quasi-record sur un segment.
- **Contexte** : départ loin de tes lieux habituels, souvent le week-end en matinée ; peu ou pas d'arrêts sur route.

Ces indices sont des hypothèses de départ, à affiner sur tes vraies courses.

**Validation** : les candidates apparaissent dans l'admin sous « Courses probables », à confirmer ou rejeter en un clic. Comme il y en a peu, une seule revue de tout l'historique suffit, puis seulement les nouvelles activités.

## 3. Exigences techniques

Interface soignée et responsive, page d'admin protégée, exécution sous Docker, dépôt Git avec image versionnée, LLM réservé à la rédaction.

### Interface

- **Pas austère** : thème clair et sombre, cartes de chiffres clés en tête de page, graphiques interactifs (survol, zoom, filtres par année et par sport), couleurs cohérentes par année et par type d'activité, typographie soignée, transitions légères.
- **Responsive, mobile d'abord** : graphiques qui se redimensionnent, tableaux en défilement horizontal ou en cartes sur mobile, navigation compacte (menu ou barre en bas d'écran).
- **Pages** : Volume et régularité, Performance, Forme, Courses, Sorties, Admin.

### Page d'admin protégée

- **Authentification** : identifiant et mot de passe hashé (argon2 ou bcrypt) fournis par variables d'environnement, session en cookie HttpOnly et Secure, limitation des tentatives de connexion. Accès en HTTPS via le reverse proxy du Synology.
- **Fonctions** :
  - lancer une synchro Garmin manuelle, voir l'état et les logs des dernières synchros ;
  - déposer le zip d'export Strava (upload, en plus du dossier surveillé) et voir les correspondances trouvées ou manquantes ;
  - gérer la liste des montres avec altimètre ;
  - régler les seuils d'hystérésis et lancer un recalcul complet (nouvelle version d'algorithme) ;
  - marquer une activité comme course, corriger un nom ou un D+ à la main.
- Les identifiants Garmin restent dans les variables d'environnement, jamais en base ni dans le dépôt.

### Docker

- **Dockerfile** multi-étapes, image légère, utilisateur non root, healthcheck.
- **docker-compose.yml** : un volume `/data` (base SQLite, FIT, tuiles MNT, session Garmin), un fichier `.env` pour les secrets, le port exposé, `restart: unless-stopped`.
- Planificateur interne au conteneur pour la synchro quotidienne.
- Migrations de la base appliquées automatiquement au démarrage.
- Doit tourner sur le Synology (Container Manager) : image construite pour amd64 et arm64.

### Git, image et versions

- Dépôt GitHub avec un `.gitignore` excluant `.env` et `/data`.
- **Versionnement sémantique** (vX.Y.Z), messages au format Conventional Commits, `CHANGELOG.md` tenu à jour.
- **GitHub Actions** :
  - à chaque push : lint et tests ;
  - à chaque tag `v*` : build multi-architecture et publication sur GitHub Container Registry (`ghcr.io/<utilisateur>/<projet>:X.Y.Z` et `:latest`).
- Version injectée au build et affichée dans le pied de page et l'admin.
- Mise à jour sur le Synology : changer le tag dans le compose, puis pull et redémarrage.

### LLM : OVHcloud AI Endpoints

Les fonctions rédactionnelles s'appuient sur OVHcloud AI Endpoints : modèles open source hébergés en Europe, sans infrastructure à gérer. Tarification au token, avec un accès gratuit limité sur certains modèles : à vérifier au moment de l'implémentation.

- **Usages** : dialogue avec le coach (comprendre les demandes et les traduire en actions sur le plan), explications et recommandations du coach, bilan hebdomadaire rédigé, assistant en langage naturel, textes du bilan annuel.
- **Configuration** : URL de base, clé et nom du modèle dans le `.env`, client compatible OpenAI, pour pouvoir changer de fournisseur ou passer à un modèle local sans toucher au code.
- **Le LLM ne calcule rien** : plan, charge, temps prévus et records restent calculés par le code. Le LLM ne fait que comprendre les demandes et mettre en mots des résultats déjà calculés.
- **Fonctionnement sans LLM** : si l'API est indisponible ou le quota atteint, l'application affiche des textes génériques à la place.
- **Économie** : réponses mises en cache, appels limités en fréquence.
- **Aucun nom issu de Strava** dans les données envoyées.

## 4. Pages de statistiques (phase 2)

Chaque indicateur affiché a une courte explication (info-bulle) : ce qu'il montre et pourquoi il est utile.

### Volume

Distance, D+ et nombre d'activités par année et de tous les temps, avec trois ajustements.

- **Cumul jour par jour, année N contre années précédentes à la même date** : un total annuel ne se compare qu'en fin d'année ; la courbe dit en novembre si tu es en avance ou en retard.
- **Km-effort = km + D+/100** (convention ITRA) : seule unité qui rend comparables une année route et une année trail. Sans elle, une année montagne paraît « petite » en kilomètres.
- **Ratio D+/km par année** : le profil de ta pratique en un chiffre, et l'évolution de ta part de trail.

### Régularité

La régularité prédit mieux la progression que les gros pics de volume.

- **Calendrier en heatmap**, une case par jour : les trous et les blocs d'entraînement se voient tout de suite.
- **Semaines actives par an** et **plus longue série de semaines consécutives** : souvent plus révélateur que le kilométrage.

### Performance

Les records se calculent sur des segments à l'intérieur des activités, et séparément pour la route et le trail.

- **Top 10 sur 1, 3, 5, 10, 21 et 42 km**, par année et de tous les temps, en **fenêtre glissante** : ton meilleur 5 km est peut-être au milieu d'un 15 km.
  - Filtrer les pics GPS, sinon faux records.
  - Séparer route et trail (par exemple au-delà de 20 m de D+ par km) : un 10 km trail n'est pas comparable à un 10 km route.
- **Courbe allure-durée par année** : meilleure allure tenue sur 1 min, 5 min, 20 min, 1 h, 2 h. Elle généralise les records et montre si tu as gagné en vitesse ou en endurance.
- **VAM** (vitesse ascensionnelle, m/h) : meilleure VAM sur les montées de plus de 200 m de D+, par année. L'équivalent trail d'un record de vitesse.

### Forme et physiologie

Ces indicateurs mesurent la progression aérobie sans avoir besoin de courses.

- **Fitness / Fatigue / Form** (modèle de Banister) : ajouter le **pic de fitness par année** et le **taux de montée hebdomadaire**. Au-delà de +5 à 8 points par semaine, le risque de blessure augmente.
- **Efficiency Factor** = vitesse / FC moyenne, sur les sorties faciles et plates. S'il monte, tu cours plus vite pour le même effort cardiaque.
- **Découplage cardiaque** sur les sorties de plus d'1 h : dérive de la FC à allure constante. Sous 5 %, la base d'endurance est solide pour cette durée.
- **Temps par zone FC, par année** : vérifier si tu cours vraiment en 80/20 ou si tout se fait en tempo.

### Courses

Un tableau de tes courses avec fitness et forme le jour J relie l'entraînement au résultat.

- Tu découvres à quel niveau de forme tu performes le mieux, et si ton affûtage fonctionne.
- Ni Garmin ni Strava n'identifient les activités comme courses : l'application les détecte automatiquement, puis Greg les confirme en un clic (voir section 2).

### Sorties et parcours similaires

Idée de Greg (3 novembre 2026) : la liste de toutes les sorties, et pour chacune, comment elle se situe face aux passages précédents sur le même parcours.

- **Liste paginée des sorties** : date, nom (et description Strava au survol), route ou trail, distance, D+ recalculé, temps en mouvement, allure, FC moyenne, HRSS. Filtres par année et par type, tri par colonne ; en cartes sur mobile.
- **Parcours similaires** : regroupement automatique des sorties qui suivent le même tracé.
  - Présélection : départ à moins de 300 m et distance à ±5 %.
  - Comparaison du tracé : chaque trace réduite à une cinquantaine de points répartis le long du parcours, écart moyen entre les deux tracés sous un seuil (distingue les variantes et le sens de parcours). Seuils à calibrer sur les vraies données.
  - Réutilisé ensuite par le coach (parcours habituels, variété) et première brique de l'idée « Montées et parcours récurrents » (section 7).
- **Pour chaque sortie** : écart au temps moyen des autres passages sur ce parcours, en temps et en pourcentage (« −1 min 32, −3 % sur 12 passages »), rang et record du parcours ; « parcours unique » s'il n'y en a pas d'autre. Comparaison sur le **temps en mouvement** (feux, pauses exclus).
- **Fiche parcours** : évolution des temps au fil des passages.
- Hors périmètre pour l'instant : les segments communs à des sorties différentes (montée au milieu d'une sortie plus longue), à voir avec l'idée des montées récurrentes.
- Difficulté : liste facile ; parcours similaires moyenne.

### Organisation et exclusions

Trois pages : **Volume et régularité**, **Performance**, **Forme**, avec le tableau des courses comme pont entre les deux dernières, plus une page **Sorties** (liste paginée et parcours similaires).

À laisser de côté : calories, nombre de pas, « X fois la tour Eiffel ». Amusant une fois, mais ça n'apprend rien.

## 5. Estimateur de course (phase 3)

Un temps de course estimé à partir d'un GPX, ou d'une distance avec un D+ éventuel, et de ta forme actuelle. C'est le moteur commun aux lignes de prédiction de la roadmap et au coach adaptatif.

Plusieurs courses s'estiment en parallèle : chacune a sa propre estimation, recalculée chaque semaine, que la course fasse partie ou non du plan d'entraînement.

### Courses suivies et historique des prédictions

- **Liste de courses à estimer, indépendante du coach** : ajouter une course juste pour voir (GPX ou distance avec un D+ éventuel, date facultative). Le coach n'en tient compte que si Greg la passe en échéance A, B ou C.
- Les échéances du coach apparaissent automatiquement dans cette liste.
- **Historique** : chaque semaine, la prédiction de chaque course est enregistrée avec sa date et la forme du moment.
- **Graphique par course** : temps prédit au fil des semaines avec sa fourchette, objectif éventuel, puis résultat réel une fois la course courue.
- **Vue d'ensemble** : toutes les courses suivies dans un tableau, avec le temps prédit actuel et son évolution sur les 4 dernières semaines.
- **Après la course**, l'activité correspondante est reliée automatiquement ; l'écart entre prédiction et résultat sert à calibrer l'estimateur.

### Entrées

- **Parcours** : GPX uploadé, ou distance plus D+ optionnel et type de terrain (route, chemin, technique).
- **Date** : aujourd'hui (« si je courais maintenant ») ou date de la course (avec la forme projetée par le coach).
- **Forme actuelle**, calculée automatiquement sur les 6 à 12 dernières semaines : courbe allure-durée, VAM, allure en descente, fitness, Efficiency Factor.

### Méthode

- **Route** : formule de Riegel avec un exposant personnel, calibré sur tes propres records récents plutôt que la valeur standard.
- **Trail** : GPX découpé en tronçons homogènes, temps de chaque tronçon selon sa pente à partir de ton modèle allure-pente personnel, plus un facteur de fatigue qui croît avec la durée (tiré de ta courbe allure-durée).
- **Ajustements optionnels** : chaleur prévue, terrain technique.
- **Validation** : l'estimateur est rejoué sur tes courses passées pour afficher son erreur moyenne. Tu sais ainsi quel crédit accorder à l'estimation.

### Sorties

- Temps estimé avec une fourchette (optimiste, réaliste, prudent) et l'allure cible.
- Pour un GPX : temps de passage par tronçon et aux points de ravitaillement, comparés aux barrières horaires si tu les saisis.
- Comparaison avec tes courses passées les plus proches (distance, D+).
- Effet de la forme : temps estimé si tu arrives avec plus ou moins de fitness le jour J.

### Difficulté

| Partie | Difficulté |
| --- | --- |
| Route : Riegel personnalisé et fourchette | Moyenne |
| Trail : découpage du GPX et modèle allure-pente personnel | Difficile |
| Validation sur les courses passées | Moyenne |
| Courses suivies hors coach et historique des prédictions | Moyenne |

## 6. Coach adaptatif (phase 4)

Un seul coach, qui s'adapte au nombre d'échéances : aucune, une ou plusieurs. Le plan se réajuste chaque semaine selon ce que tu as réellement fait et le temps dont tu disposes. Pensé pour un coureur amateur avec une vie de famille : jamais de rattrapage forcé, toujours un objectif réaliste. Il discute avec Greg et conseille sans jamais forcer : Greg reste maître de ses choix. Difficulté globale : difficile, à livrer par étapes.

| Échéances à venir | Ce que fait le coach |
| --- | --- |
| Aucune | Maintien de forme sur la durée, à partir des habitudes réelles |
| Une | Préparation périodisée vers cette course, affûtage, puis récupération |
| Plusieurs | Plan construit autour de la course A ; courses B et C intégrées avec mini-affûtage ou semaine allégée, et récupération après chacune |

**Passage d'une situation à l'autre, automatique** :

- ajout, suppression ou changement de date d'une course : plan recalculé à partir de la forme actuelle ;
- après la dernière course du calendrier : récupération, puis retour au maintien de forme ;
- en maintien, dès qu'une course est ajoutée : bascule en préparation.

### Un coach qui discute, conseille et ne force pas

- **Discussion**, sur mobile d'abord. Greg écrit comme à un coach : « grosse semaine au boulot », « je suis malade », « on part en vacances du 20 au 27 », « je préfère courir mardi », « je me sens bien, on peut pousser ? ».
- **Le coach propose, Greg décide** : il comprend la demande, propose un ajustement, explique son effet sur les échéances et n'applique qu'après accord.
- **Des conseils, pas des obligations** : une séance sautée ou remplacée n'est jamais un échec. Le coach dit ce qu'il recommande et pourquoi ; si Greg choisit autrement, le plan s'adapte sans reproche.
- **Ton** : bienveillant, direct, concret, phrases courtes. Honnête quand un objectif devient irréaliste ou qu'un choix met une course en risque, mais il le dit une fois, sans insister.
- **Initiative mesurée** : bilan du dimanche sous forme de courte conversation, alerte en cas de fatigue ou de charge anormale, mot sur un record. Quelques messages par semaine au plus.
- **Mémoire des préférences** exprimées (jours possibles, durées, séances appréciées ou détestées), réutilisées dans les plans suivants.
- **Fonctionnement** : le LLM traduit la conversation en actions structurées (ajouter une période, changer l'orientation, déplacer une séance, ajouter une course), le moteur de règles recalcule le plan, puis le LLM explique le résultat. Tout reste faisable sans LLM depuis l'interface classique.

### Saisie rapide en langage naturel

Une boîte de message toujours visible en haut de l'accueil et de l'écran « Cette semaine » : Greg y dit en une phrase comment il va et quand il peut courir, sans ouvrir une conversation complète.

- **Exemples** : « mal dormi, jambes lourdes », « dispo mardi midi 45 min et samedi matin, sinon rien », « petite gêne au mollet gauche depuis hier », « en vacances la semaine prochaine, je courrai peut-être deux fois ».
- **Traduction en informations structurées**, affichées sous forme d'étiquettes modifiables avant validation : fatigue, sommeil, douleur (localisation), motivation, disponibilités par jour avec durée, période particulière.
- **Effet immédiat** sur le plan, avec une phrase d'explication : séance du jour allégée, séances déplacées sur les créneaux libres, progression suspendue en cas de douleur.
- **Dictée vocale** possible via le micro du téléphone (clavier ou reconnaissance vocale du navigateur).
- **Journal de forme** : chaque saisie est datée et conservée, pour croiser le ressenti avec la charge, et l'afficher sur la page Forme.
- **Sans LLM**, la même boîte propose des boutons rapides : frais, normal, fatigué ; disponibilités jour par jour.
- Elle remplace les deux questions du bilan du dimanche, qui devient une simple invitation à écrire une phrase.

### Orientation et semaines particulières

- **Orientation de l'entraînement**, choisie et modifiable à tout moment : maintien, reprise, foncier, vitesse (10 km et moins), route longue (semi, marathon), trail. Avec une course A, l'orientation découle de la course ; Greg peut la nuancer (« plus de côtes »), et le coach signale si ce choix éloigne de l'objectif.
- **Semaines particulières**, posées à l'avance ou au dernier moment : vacances, Noël, déplacement, semaine chargée, maladie, blessure. Pour chacune, un niveau : pas de course à pied, minimum (1 ou 2 footings) ou normal allégé.
- **Le plan anticipe** : pas de séance dure juste avant, reprise progressive après, et vérification face aux échéances. Par exemple, une coupure à Noël 4 semaines avant une course A : le coach indique l'effet sur le temps prévu et propose un ajustement, sans l'imposer.
- **Maladie ou blessure** : progression suspendue, reprise prudente, invitation à consulter en cas de douleur.

### Choix et variété des séances

- **Deux propositions par séance prévue**, qui jouent le même rôle dans la semaine. Par exemple : seuil 3 × 10 min sur le plat, ou côtes sur la montée de la Bastille. Greg choisit, et le plan tient compte de son choix.
- **Habitudes respectées** : la sortie habituelle reste à sa place (le lundi, la Bastille) ; le coach lui donne un rôle selon la phase : footing, côtes, progressif, sortie plus longue.
- **Variété contre la monotonie** :
  - bibliothèque de séances par type : fartlek, pyramide, côtes courtes ou longues, progressif, tempo, sortie longue avec fin rapide ;
  - pas deux fois la même séance de qualité à quelques semaines d'intervalle ;
  - parcours variés, piochés parmi les parcours habituels détectés dans l'historique ;
  - un indicateur de monotonie qui alerte si les semaines se ressemblent trop.

### Unités, séance de remplacement et bilan de semaine

Précisions sur le fonctionnement au quotidien.

- **Unités au choix** : les séances sont décrites en allure (min/km) par défaut. Greg peut choisir à la place les zones de FC ou la sensation (effort perçu), et la durée plutôt que la distance. Réglage modifiable à tout moment.
- **Proposer une séance de remplacement**, en langage naturel (« je préfère faire 1 h tranquille avec la Bastille ») ou en remplissant des champs (type, durée ou distance, intensité, D+, jour).
  - L'outil affiche un **pourcentage de compatibilité avec le plan** et une phrase d'explication.
  - Le calcul compare la séance proposée à celle prévue : même rôle (type et intensité), charge proche, placement compatible avec la récupération et les séances voisines, effet sur les échéances. La pondération de départ est à calibrer.
  - Le coach suggère, si possible, une petite modification qui augmente la compatibilité.
  - Greg valide ou non ; dans tous les cas, le reste de la semaine se réajuste.
- **Bilan de fin de semaine**, automatique le dimanche :
  - verdict simple : semaine bien suivie, partiellement suivie ou peu suivie ;
  - séances faites face aux séances prévues, compatibilité moyenne des remplacements, charge réalisée face à la charge prévue ;
  - effet sur la forme et sur les temps prédits des échéances ;
  - sans jugement : une semaine peu suivie est un fait, le plan suivant en tient compte.
- **Orientation de la semaine suivante** : à la fin du bilan, le coach demande comment l'aborder (fatigué, normal, en forme, semaine chargée), via la boîte de saisie rapide ou des boutons. La réponse oriente la semaine qui vient.

### Démarrage (5 minutes)

1. **Disponibilités, facultatives** : jours possibles et temps maximal par jour, ou simplement un nombre moyen de séances par semaine. Sans réponse, elles sont déduites de l'historique.
2. **Habitudes, facultatives** : séances récurrentes à garder telles quelles, par exemple « je cours le lundi et je fais presque toujours la Bastille ». Elles sont aussi détectées dans l'historique (jour, parcours récurrent) et proposées pour confirmation.
3. **Les courses, facultatives** : aucune, une ou plusieurs. Pour chacune : GPX (trail : profil, D+, tronçons) ou distance avec un D+ éventuel, date et priorité (A, B ou C).
4. **L'objectif proposé pour chaque course** : l'outil estime un temps réaliste à partir de ta forme actuelle (fitness, courbe allure-durée, VAM), que tu acceptes ou modifies. Sans course, il propose la plage de forme à maintenir.

### Construction du plan

- **Périodisation à rebours depuis la date** : foncier, développement, spécifique, affûtage. L'affûtage dure 1 à 2 semaines selon la distance (plus long pour un trail long).
- **Progression de la charge** pilotée par la fitness visée le jour J, avec une hausse hebdomadaire plafonnée et un cycle 3 semaines de charge et 1 semaine allégée.
- **Séances typées** : footing, sortie longue, seuil, fractionné, côtes. Pour un trail, D+ hebdomadaire et sorties longues dont le profil se rapproche de celui du GPX.
- **Intensité 80/20** : la majorité du temps en endurance fondamentale, peu de séances dures mais bien placées.
- **Règles de récupération** : jamais deux séances dures d'affilée, un jour de repos complet minimum par semaine.

### Suivi chaque semaine

1. **Détection automatique** des séances faites, à partir des activités Garmin synchronisées : rien à saisir.
2. **Bilan du dimanche** en deux questions : comment s'annonce la semaine prochaine (chargée, normale, libre) et comment tu te sens (frais, normal, fatigué).
3. **Réajustement** :
   - semaine chargée : moins de séances, mais on garde la plus utile (sortie longue ou séance clé) ;
   - séances manquées : jamais rattrapées, la progression est simplement décalée ;
   - fatigue ressentie, forme trop basse ou VFC en baisse : semaine allégée ;
   - en avance sur le plan : progression maintenue, sans accélérer.
4. **Recommandations courtes** : la séance clé de la semaine et pourquoi, ce qui peut sauter si le temps manque.

### Estimation du temps et objectif

- **Temps prévu recalculé chaque semaine** à partir de la forme actuelle et de la fitness projetée au jour J, affiché en courbe au fil des semaines face à l'objectif.
- **Objectif réajusté** quand l'écart devient durable (par exemple trois semaines consécutives), avec une explication en une phrase.
- Pour un trail : temps prévu par tronçon du GPX, pour préparer les ravitaillements et les barrières horaires.

### Simplicité

- Un seul écran **« Cette semaine »** : les séances prévues, ce qui est fait, la séance clé, le temps prévu.
- Une notification le dimanche soir pour le bilan, et c'est tout.
- Option : envoyer les séances dans le calendrier Garmin pour les retrouver sur la montre (faisabilité à vérifier avec `garminconnect`).
- Logique de plan à base de règles explicites, pour un résultat cohérent et explicable. Un LLM peut éventuellement rédiger les explications, sans données issues de Strava.

### Plusieurs courses en même temps

Le coach gère un calendrier de courses, pas une seule : par exemple une course dans 3 semaines, une dans 3 mois et une dans 6 mois. Le plan d'entraînement est construit pour l'ensemble.

- **Calendrier des courses** : chaque course a son parcours (GPX, ou distance avec un D+ éventuel), sa date et une priorité.
- **Priorités** :
  - **A**, objectif principal : le plan entier est périodisé pour elle, avec un affûtage complet ;
  - **B**, course importante : mini-affûtage de quelques jours, puis récupération ;
  - **C**, course de préparation : courue comme une grosse séance, sans affûtage, juste une semaine un peu allégée.
- **Récupération après chaque course**, proportionnelle à sa durée, son D+ et son intensité, avant de reprendre la progression.
- **Conflits signalés** : deux courses A trop rapprochées, ou une course B en pleine phase de charge. L'outil propose une solution (passer une course en B ou C, décaler un bloc) et c'est Greg qui choisit.
- **Les courses s'informent entre elles** : le résultat d'une course proche sert de test et met à jour l'estimation et l'objectif des suivantes.
- **Après la course A**, le plan se reconstruit automatiquement autour de la course suivante du calendrier.
- **Écran « Cette semaine »** : les prochaines courses avec compte à rebours, priorité et temps prévu de chacune.

### Sans course prévue : maintien de forme

Quand le calendrier est vide, ou après la récupération de la dernière course, le coach passe en mode maintien : garder une forme durable plutôt que progresser vers une date.

- **Point de départ réel** : le niveau et les habitudes des 8 à 12 dernières semaines (nombre de séances, volume, D+, sortie longue), pas un niveau théorique.
- **Cible** : une plage de fitness stable à tenir, plutôt qu'une courbe qui monte, avec le cycle 3 semaines normales et 1 semaine allégée.
- **Semaine type** : surtout de l'endurance fondamentale, une séance de qualité qui varie (seuil, fractionné, côtes), une sortie longue un peu plus courte qu'en préparation.
- **Adaptation à ce qui est fait** :
  - séances manquées jamais rattrapées ;
  - si la fitness passe durablement sous la plage (vacances, période chargée, coupure), reprise progressive proposée, sans à-coups ;
  - si Greg en fait spontanément plus, la plage remonte doucement ;
  - les périodes calmes récurrentes (été, fêtes) sont acceptées comme telles, sans culpabiliser.
- **Repères légers** : un test facultatif de temps en temps (par exemple un 5 km ou une montée connue) pour suivre la forme sans dossard.
- **Envie de courir une course** : l'outil peut suggérer une distance cohérente avec la forme du moment. Dès qu'une course est ajoutée, le plan de préparation part de la forme actuelle.

### Mise en œuvre progressive

| Étape | Contenu | Difficulté |
| --- | --- | --- |
| 1 | Saisie de la course (GPX ou distance), date, rythme ; génération du plan périodisé | Moyenne |
| 2 | Détection des séances faites et écran « Cette semaine » | Moyenne |
| 3 | Bilan du dimanche et réajustement automatique | Difficile |
| 4 | Objectif initial et temps prévu semaine après semaine | Difficile |
| 5 | Temps prévus par tronçon pour le trail | Difficile |
| 6 | Envoi des séances vers le calendrier Garmin | Moyenne |
| 7 | Calendrier de plusieurs courses avec priorités A, B, C, conflits et récupération | Difficile |
| 8 | Mode maintien de forme sans course prévue, adapté aux séances réellement faites | Moyenne |
| 9 | Orientation modifiable et semaines particulières (vacances, Noël, maladie) | Moyenne |
| 10 | Coach conversationnel : discussion, actions validées par Greg, conseils non contraignants | Difficile |
| 11 | Saisie rapide en langage naturel (forme, disponibilités) avec étiquettes modifiables et journal de forme | Moyenne |
| 12 | Disponibilités et habitudes facultatives, deux séances au choix, variété des séances et des parcours | Moyenne |
| 13 | Unités au choix, séance de remplacement avec pourcentage de compatibilité, bilan de semaine et orientation de la suivante | Moyenne |

Ce n'est pas un avis médical : en cas de douleur ou de blessure, l'outil suspend la progression et invite à consulter.

## 7. Idées pour la suite

20 idées, classées par thème, à trier ensuite par priorité. La difficulté est une estimation pour un développement assisté par Claude Code sur la base décrite plus haut.

| Thème | Idée | Ce que ça apporte | Difficulté |
| --- | --- | --- | --- |
| Course et prédiction | Prédiction de temps sur route | Temps estimés du 5 km au marathon, à partir de ta courbe allure-durée et de ta forme du moment | Moyenne |
| Course et prédiction | Prédiction trail sur un GPX | Importer le parcours d'une course : temps par tronçon selon ta VAM et ton allure en descente, barrières horaires, plan de ravitaillement | Difficile |
| Course et prédiction | Simulateur d'affûtage | Saisir les séances prévues et projeter fitness et forme jusqu'au jour J pour arriver frais au bon moment | Moyenne |
| Course et prédiction | Page « Prochaine course » | Compte à rebours, profil du parcours, prédiction, forme projetée, historique sur la même course | Moyenne |
| Analyse | Allure ajustée à la pente personnelle | Modèle calibré sur tes propres données plutôt qu'une formule générique ; rend trail et route comparables | Difficile |
| Analyse | Montées et parcours récurrents | Détection automatique des mêmes montées et boucles, classement de tes passages dans le temps, comme des segments privés | Difficile |
| Analyse | Météo de chaque sortie | Température, vent et humidité via une API d'archives météo ; allure et FC corrigées de la chaleur | Moyenne |
| Analyse | Sommeil, VFC et forme | Croiser les données santé Garmin avec la charge d'entraînement et les performances | Moyenne |
| Analyse | Alertes intelligentes | Charge qui monte trop vite, monotonie, dérive cardiaque inhabituelle | Facile |
| Cartes | Carte de toutes les traces | Heatmap personnelle auto-hébergée depuis les FIT, filtrable par année et par type | Moyenne |
| Cartes | Tuiles explorées | Carrés explorés, plus grand carré, nouvelles tuiles par année, en local | Moyenne |
| Cartes | Replay « fantôme » | Rejouer deux passages sur le même parcours, animés côte à côte | Difficile |
| Partage et usage | Bilan annuel façon « Wrapped » | Page ou image de fin d'année : chiffres marquants, records, meilleure sortie | Moyenne |
| Partage et usage | Rapport hebdomadaire automatique | Résumé par mail ou notification (Telegram, ntfy) : volume, forme, alertes | Facile |
| Partage et usage | Suivi du matériel | Kilomètres par paire de chaussures, alerte de remplacement | Facile |
| Partage et usage | Assistant en langage naturel | Interroger ta base en français (« mon meilleur 10 km en hiver ? ») via un LLM qui génère les requêtes SQL | Difficile |
| Partage et usage | Application installable (PWA) | Icône sur l'écran d'accueil du téléphone, consultation hors ligne | Moyenne |
| Plateforme | Multi-utilisateurs | Plusieurs comptes Garmin (famille, club) avec des pages séparées | Difficile |
| Plateforme | Sauvegarde automatique | Base et FIT sauvegardés hors du conteneur (Hyper Backup, stockage externe) | Facile |
| Plateforme | Autres sources | Import de FIT ou GPX d'autres montres ou d'archives par simple dépôt de fichier | Moyenne |

Pour l'assistant en langage naturel, exclure par prudence les noms issus de Strava des données envoyées au LLM : les conditions Strava interdisent l'usage de ses données dans des applications d'IA.

**Autres idées tirées des contraintes de Greg**

- **Page « Qualité des données »** dans l'admin : activités sans FC ou sans GPS, pics GPS filtrés, noms Strava non associés. Facile.
- **Bouton « semaine chargée »** accessible d'un geste sur mobile, sans attendre le bilan du dimanche. Facile.
- **Semaine type de disponibilités** (jours possibles, durée maximale par jour) servant de base au coach. Moyenne.
- **Accueil en un coup d'œil** : forme du jour, cumul de l'année face à l'an dernier à la même date, prochaine séance prévue. Moyenne.
- **Notifications via ntfy** auto-hébergé sur le Synology. Facile.
- **Jeu de données de démonstration** et fichiers FIT de test, pour les tests automatiques et pour montrer l'application sans exposer les données réelles. Facile.

**Idées notées en cours de route (non implémentées)**

Idées de Greg ou limites relevées pendant le développement, à reprendre seulement sur demande. Chaque entrée porte sa date.

- *3 novembre 2026* — Intervalles très courts (30/30, 45/40…) : la détection sur l'allure exige 40 s d'effort minimum et ne les voit pas ; seuls les tours de la montre les décrivent. Piste : abaisser le seuil pour les séances nommées « 30/30 » ou détecter sur la FC. Facile à moyenne.
- *3 novembre 2026* — **Planifiée en phase 3, étape 10 bis (choix de Greg).** Fiche d'une course réalisée : superposer le temps estimé par l'estimateur (avec la forme de la veille) et le temps réel dans un graphique, format à définir avec Greg (par exemple temps de passage estimés et réels le long du parcours, ou écart cumulé au fil des kilomètres, avec le profil d'altitude). Le calcul se lance depuis la fiche de la course elle-même, par un bouton, sans passer par la page Estimateur ni importer de GPX (la trace de la sortie sert de parcours) ; deux estimations possibles : avec la forme de la veille de la course et avec la forme d'aujourd'hui (« que ferais-je maintenant sur ce parcours »). S'appuie sur le rejeu des courses (étapes 3 et 7 de la phase 3) et sur le lien course / prédiction de l'étape 10. Moyenne.
- *3 novembre 2026* — **Abandonné (décision de Greg).** Estimateur trail sans GPX (distance, D+ et type de terrain) : sans intérêt, la trace d'une course est toujours disponible. Le terrain technique et la chaleur restent à trancher plus tard.
- *3 novembre 2026* — **Reporté (décision de Greg).** Barrières horaires saisies sur un GPX et comparées aux temps de passage estimés (prévues à l'étape 6 de la phase 3, seuls les ravitaillements ont été faits). Facile.
- *3 novembre 2026* — **En partie traité le même jour (ajustement par la FC, références sur 4 mois, section 10).** **Niveau de l'estimateur trop dépendant d'une séance** (remarque de Greg : une séance rapide fait passer la prédiction de Côte rouge de 3 h 51 à 3 h 27 d'une semaine à l'autre, à fitness égale ; sans séance intense dans les 12 semaines, la prédiction est trop lente). Le niveau vient du meilleur effort route de la fenêtre, extrapolé. Pistes : niveau tiré de la relation FC / vitesse de toutes les sorties extrapolée à la LTHR (allure seuil estimée même avec des footings seulement), seul ou combiné aux meilleurs efforts ; moyenne des 2 ou 3 meilleures références ; poids décroissant avec l'ancienneté. À choisir sur le rejeu des courses passées. Moyenne.

- *4 novembre 2026* — Fourchette de l'estimateur calée sur les limites à 95 % mesurées (Bland-Altman) au lieu de l'hypothèse ±2 % + 3 % par facteur e, une fois assez de courses par terrain (une dizaine). Sur les données de Greg au 4 novembre : trail ±10 % mesuré pour ±10 % affiché (5 courses sur 5 dedans), route trop peu de courses (3). Facile.
- *4 novembre 2026* — Progression d'une saison à l'autre (thèse de L. Lerebourg, 2021) : meilleur temps route de chaque année sur 5 km, 10 km, semi, avec l'écart en %, sur la page Performance ou pour le bilan du coach. Facile.
- *4 novembre 2026* — Sortie moyenne (entre footing et sortie longue, environ 25 % du volume de la semaine) dans le plan du coach à partir de 5 séances par semaine (idée de Running-Plan-Generator). Facile.
- *4 novembre 2026* — Zones de forme de la page Forme en % de la fitness, comme le jour J du plan du coach : les seuils absolus (+5, −10, −30) sont faits pour de gros volumes ; à faible charge, une forme de +3 est déjà « frais ». Facile.
- *4 novembre 2026* — **Fait le même jour (section 10).** Indice de confiance de chaque prédiction, avec ses raisons (demande de Greg). Moyenne.
- *4 novembre 2026* — **Fait le même jour, page Forme (section 10).** VMA, VO2max estimée et FC au seuil (en % de la FC max) sur le tableau de bord (demande de Greg). Moyenne.
- *4 novembre 2026* — **Fait le même jour (section 10).** Dans les disponibilités du coach, ajouter ou supprimer des périodes particulières (vacances, maladie), avec un nombre de séances prévu pendant la période, sans obligation de le suivre (demande de Greg ; relève de l'étape 8 de la phase 4, semaines particulières, à traiter après l'étape 3). Moyenne.

## 8. Plan de livraison

Cinq phases après l'audit, chacune close par un tag de version mineure ; la v1.0.0 arrive à la fin de la phase 4.

| Phase | Contenu | Terminé quand |
| --- | --- | --- |
| 0. Audit | Audit de l'existant, plan module par module (garder, refactorer, réécrire) | Plan validé par Greg |
| 1. Socle | Synchro Garmin et premier import, parsing FIT, D+ (altimètre ou MNT), noms Strava, SQLite, Docker, CI, admin minimale | Historique importé sans doublon, relance idempotente, D+ calibré sur au moins 3 parcours connus, image multi-architecture publiée, admin protégée accessible |
| 2. Statistiques | Pages Volume et régularité, Performance, Forme, Courses, Sorties (liste et parcours similaires) ; détection des courses | Pages vérifiées sur mobile, records en fenêtre glissante séparés route et trail, courses probables validables dans l'admin |
| 3. Estimateur | Estimation route et trail depuis un GPX ou une distance | Erreur moyenne affichée, mesurée sur les courses passées |
| 4. Coach | Plan depuis GPX ou distance, séances détectées, bilan du dimanche, réajustement, temps prévu chaque semaine | Un plan suivi sur 2 semaines réelles sans intervention manuelle |
| 5. Extensions | Temps par tronçon en trail, envoi des séances vers Garmin, idées retenues en section 7 | Selon l'idée retenue |

### Durées indicatives

Environ 6 mois au total, en temps de loisir (quelques soirées par semaine), Claude Code écrivant l'essentiel du code. Des statistiques utilisables arrivent au bout de 1 à 2 mois. Ces durées sont des ordres de grandeur, pas des engagements.

| Phase | Durée indicative |
| --- | --- |
| 0. Audit | 1 séance |
| 1. Socle | 2 à 4 semaines |
| 2. Statistiques | 2 à 3 semaines |
| 3. Estimateur et historique des prédictions | 3 à 5 semaines |
| 4. Coach : plan, plusieurs courses, maintien, habitudes, variété | 2 à 3 mois |
| 4 bis. Coach conversationnel et saisie en langage naturel | 1 à 2 mois |

### Risques et parades

- **Qualité du coach** : la difficulté est dans les règles, pas dans le code. Commencer par un coach simple, l'utiliser réellement chaque semaine, l'enrichir à partir des retours de Greg.
- **API Garmin non officielle** : peut casser ou bloquer temporairement le compte. Appels espacés, FIT conservés en local, mise à jour de la librairie en cas de rupture, erreurs visibles dans l'admin.
- **Peu de courses dans l'historique** : marge d'erreur de l'estimateur large au début, surtout sur route. L'afficher honnêtement ; les nombreuses montées aident à calibrer le modèle trail.
- **LLM en français avec appels d'outils** : tester tôt sur OVHcloud ; tout doit rester utilisable sans LLM.
- **Éparpillement** : une phase à la fois, chacune utilisable avant la suivante ; les idées de la section 7 attendent une demande explicite.

## 9. Points à vérifier avant de coder

- [x] Format et fuseau horaire de `Activity Date` dans `activities.csv` (export Strava), à comparer avec une activité connue. Voir section 10, « Export Strava ».
- [ ] Fonctions disponibles dans la version de `garminconnect` utilisée : téléchargement du FIT original, `set_activity_name`, création et planification de séances.
- [ ] Durée du premier import complet via Garmin Connect et pause nécessaire entre deux téléchargements.
- [ ] Liste des montres de Greg et présence d'un baromètre sur chacune.
- [x] Source du MNT : téléchargement et licence des tuiles RGE ALTI et Copernicus, ou limites de l'API altimétrie IGN. Voir section 10.
- [ ] Conditions de l'accès gratuit OVHcloud AI Endpoints et modèles disponibles.
- [ ] Seuils d'hystérésis, de détection des courses et de séparation route/trail : valeurs de départ à calibrer sur les données réelles.
- [ ] Modèle OVHcloud AI Endpoints capable d'appels d'outils (function calling) en français, pour le coach conversationnel.

## 10. Décisions de la phase 0 (validées par Greg le 2 novembre 2026)

Audit de l'existant et plan module par module, validés avant la phase 1.

- **Synchro Garmin** : refactorée sur le modèle du projet `wmts-gpx-heatmap` de Greg. On garde le verrou et l'écriture atomique des FIT ; on sépare la synchro des calculs.
- **Connexion Garmin depuis l'admin** (comme `wmts-gpx-heatmap`) : email et mot de passe saisis dans l'admin, code MFA saisi dans l'admin si Garmin le demande (connexion en attente quelques minutes), puis jeton de session enregistré sur le volume et renouvelé par la librairie. Au moment de la connexion, Greg **choisit** : ne pas mémoriser le mot de passe (recommandé, il sert seulement à obtenir le jeton) ou le mémoriser dans un fichier privé du dossier des jetons pour une reconnexion automatique. `GARMIN_EMAIL`/`GARMIN_PASSWORD` dans `.env` restent possibles et valent mémorisation. Le mot de passe n'est jamais en base ni dans le dépôt. Cela remplace `generate_token.py`.
- **`garminconnect` 0.3.x** (0.3.20, déjà en production dans `wmts-gpx-heatmap`), qui abandonne garth : le jeton actuel `data/garth_tokens` devra être régénéré une fois via l'admin. Fonctions vérifiées en 0.2.40 : `set_activity_name`, `upload_running_workout`, `schedule_workout`, `download_activity` ; à revérifier en 0.3.20.
- **Réglages de synchro dans l'admin** : activation, heure ou intervalle, profondeur du premier import.
- **Parsing FIT** : réécrit (modèle de montre et séries complètes) avec **`fitdecode`** plutôt que fitparse : un peu plus rapide (environ 20 %) et toujours maintenu, alors que fitparse ne l'est plus depuis 2020. Lecture répartie sur plusieurs processus : l'historique complet (671 FIT) prend 7 min sur 2 cœurs, une seule fois ; ensuite seuls les nouveaux FIT sont lus. La Forerunner 255 enregistre un point toutes les quelques secondes seulement (enregistrement intelligent) : les calculs rééchantillonnent par distance.
- **Séries par activité** : fichiers **Parquet**, `/data/series/<activity_id>.parquet`, régénérables depuis les FIT.
- **Calculs** : réécrits en fonctions pures testées et versionnées. TRIMP/HRSS et Banister repris tels quels.
- **Stockage** : SQLite gardé, nouveau schéma, migrations numérotées appliquées au démarrage. La base actuelle est **reconstruite depuis les FIT** (et une nouvelle liste des métadonnées Garmin), pas migrée.
- **Planificateur** : APScheduler gardé ; tâche quotidienne et scrutation périodique du dossier d'export Strava (inotify peu fiable sur les volumes Synology).
- **Interface** : réécrite. FastAPI, templates Jinja et JavaScript simple sans étape de build ; **ECharts** remplace Chart.js (calendrier heatmap, zoom et thème sombre natifs).
- **Zones FC** : calées sur la **LTHR** (modèle de Friel), plus sur la FC max.
- **LTHR** : `LTHR` dans `.env` reste la valeur de référence. L'application en propose une estimation à partir des efforts soutenus de 30 à 60 min (fenêtre glissante dans les FIT), affichée dans l'admin à côté de la valeur réglée. Elle ne la remplace jamais automatiquement.
- **Montres** (lues dans les FIT de course, modèles confirmés par Greg) :

  | `garmin_product` | Modèle | Période | Sorties | Baromètre | Source d'altitude |
  | --- | --- | --- | --- | --- | --- |
  | 2503 | Forerunner 35 | déc. 2020 → déc. 2021 | 112 | non (aucune altitude dans le FIT) | MNT |
  | 3076 | Forerunner 245 | déc. 2021 → sept. 2024 | 264 | non (altitude GPS seulement) | MNT |
  | 3992 | Forerunner 255 | depuis sept. 2024 | 258 | oui | altimètre |

  La Forerunner 245 illustre la règle de la section 2 : son FIT contient une altitude, mais d'origine GPS, donc le MNT fait foi.
- **FC max** : la valeur de `.env` (190) est dépassée dans l'historique (195 observé) ; l'admin signalera le maximum observé.
- **GitHub** : dépôt `georgieboyfr/garmin-fitness-trend`, image `ghcr.io/georgieboyfr/garmin-fitness-trend`.
- **Export Strava** (vérifié le 2 novembre 2026 sur deux archives, 693 activités) :
  - export **localisé en français** : en-têtes traduits (`ID de l'activité`, `Date de l'activité`, `Nom de l'activité`, `Type d'activité`…), certains en double (`Distance` en km avec virgule puis en m, `Temps écoulé` deux fois). Le parseur reconnaît les en-têtes français et anglais et prend la première occurrence ;
  - `Date de l'activité` au format `7 nov. 2020, 15:54:37`, mois abrégés en français, **en UTC** (identique à la seconde au `start_time` du FIT, en hiver comme en été) ;
  - appariement par heure UTC avec 2 min de tolérance : 660 activités appariées sur 682 dans la période couverte par Garmin. Les 22 restantes : séances de PPG et randonnées sans équivalent, une saisie manuelle, une dizaine de sorties qui semblaient absentes. Le premier import réel (2 novembre 2026) a montré que 8 d'entre elles (août–sept. 2026) étaient bien dans l'ancienne base mais **sans FIT** : téléchargés par la nouvelle synchro, elles sont désormais appariables. Celle du 27 août 2021 était une sortie sans FC, écartée par l'ancienne application et désormais comptée. Trois sorties Strava (13 et 28 sept. 2021, 14 avr. 2025) n'existent pas dans Garmin : courues sans montre, la trace étant partagée depuis la montre d'une autre personne. Elles restent hors statistiques ;
  - 435 des noms appariés sont les noms génériques de Strava (« Course à pied le midi »…) : ils ne sont pas repris, le nom Garmin est gardé ;
  - **dépôt léger** : le dossier surveillé et l'upload de l'admin acceptent l'archive zip complète **ou** le seul `activities.csv` extrait (quelques centaines de Ko au lieu de 200 Mo et plus) ;
  - quand plusieurs fichiers sont déposés, seul le plus récent compte (date de dernière activité qu'il contient, pas date du fichier). Un fichier déjà traité n'est pas relu.
- **Calibration du D+** (décision de Greg, 2 novembre 2026) : pas de parcours de référence pour l'instant. Le critère de fin de phase 1 « D+ calibré sur au moins 3 parcours connus » est remplacé par une calibration croisée sur les sorties Forerunner 255 : sur une même sortie, D+ baromètre et D+ MNT, et le seuil MNT est réglé pour que les deux concordent. Ajustement possible plus tard depuis l'admin.
- **Réglages du D+ retenus** (3 novembre 2026, à la demande de Greg : « se fier au baromètre ») : pas de 10 m, filtre médian de 3 points, **seuil baromètre 1 m** (au lieu de 2,5 m proposé au départ, qui retirait 5 à 7 % du D+ mesuré par la montre), **seuil MNT 3,5 m**. Résultats : Forerunner 255 à 0,4 % du D+ Garmin au total (1,1 % d'écart médian par sortie) ; MNT à 0,2 % du baromètre au total sur 177 sorties Forerunner 255 (4 % d'écart médian). Comparaison annuelle avec Strava (Statshunter) : −0,1 % (2021), +5,7 % (2022), +2,0 % (2023), +7,3 % (2024), −1,9 % (2025), −0,2 % (2026). Le D+ Garmin des Forerunner 35 et 245 (altitude GPS) était gonflé d'environ 70 %.
- **Source du MNT** (point de la section 9) : service de calcul altimétrique IGN de la Géoplateforme (RGE ALTI, gratuit, sans clé, 5 requêtes/s) interrogé une fois par activité, profil mis en cache ; Copernicus GLO-30 hors de France (4 sorties : Rome, Madrid, Brühl), dalles téléchargées une fois depuis le dépôt public AWS. Évite de stocker plusieurs Go de dalles RGE ALTI sur le NAS.
- **Import Strava** (3 novembre 2026) :
  - noms (et **descriptions**, à la demande de Greg, affichables là où le nom apparaît) stockés **dans l'application** (table locale, vue `activity_names`) ; rien n'est renommé dans Garmin Connect ;
  - sorties de course Strava sans équivalent Garmin, d'au moins 1 km et avec une trace dans l'archive : importées comme activités « source Strava » (id négatif), trace lue et D+ calculé comme les autres (MNT). Cela couvre les 11 sorties de nov.–déc. 2020 (avant la première montre Garmin) et les 3 sorties partagées sans montre ; « Passage Fabien » (0,3 km) est écarté par le seuil de 1 km. Si Garmin fournit plus tard la même sortie, la copie Strava est remplacée ;
  - résultat sur l'export du 29 octobre 2026 : 670 activités appariées, 179 noms repris (les autres sont les noms génériques de Strava), 14 sorties importées ;
  - le D+ de Strava de chaque sortie est conservé, pour comparaison seulement.
- **Accès aux pages de statistiques** (décision de Greg, 3 novembre 2026) : protégées par la même connexion que l'admin (session de 30 jours), car elles montrent FC, lieux, noms et descriptions. Une page non connectée renvoie vers la connexion puis revient à la page demandée.
- **Choix de la phase 2, étapes 2 à 5** (faits en autonomie le 3 novembre 2026, à valider par Greg) :
  - temps en mouvement : segments à au moins 0,5 m/s (la marche en forte pente compte) ; il colle au temps en mouvement Garmin à 0,5 % près ;
  - zones de FC de Friel sur la LTHR (Z1 < 85 %, Z2 85–89 %, Z3 90–94 %, Z4 95–99 %, Z5 ≥ 100 %) ;
  - LTHR estimée = meilleure FC moyenne tenue une heure sur 12 mois : **178** (Trail de côte rouge, 11 juillet 2026, FC moyenne 171 sur 3 h 35), contre 170 dans `.env`. Non appliquée automatiquement ; FC max observée 192 sur 12 mois (199 sur tout l'historique, probablement un artefact). **Décision de Greg** : LTHR, FC max et FC repos sont **modifiables dans l'admin** (bouton « Utiliser l'estimation »), le `.env` ne donne plus que les valeurs par défaut ; toute modification relance le calcul des sorties ;
  - terrain d'une sortie : trail au-delà de 20 m de D+ par km sur l'ensemble de la sortie (pas par segment), sinon route ; tapis à part ;
  - records : temps écoulé dans la fenêtre (arrêts compris), segments à plus de 7 m/s ignorés (pics GPS), tapis exclus ;
  - VAM : meilleure montée de plus de 200 m de D+ (descentes de moins de 20 m ignorées), route et trail confondus, à partir de l'altitude retenue pour le D+ ;
  - Copernicus est un modèle de surface (bâtiments compris) qui surestimait le D+ des 4 sorties en ville à l'étranger (Marathon de Madrid : 797 m). **Décision de Greg** : hors de France, le D+ de Strava est préféré quand l'activité est appariée (Madrid : 356 m) ; pas de VAM sur ces sorties.
- **Page Forme** (3 novembre 2026) : Efficiency Factor sur les sorties faciles et plates = route, moins de 10 m de D+ par km, au moins 30 min en mouvement, FC moyenne sous 90 % de la LTHR ; découplage = baisse de l'EF entre les deux moitiés du temps en mouvement, sorties d'au moins 1 h sur le plat ; zones de forme (TSB) : > +25 très frais, +5 à +25 frais, −10 à +5 neutre, −30 à −10 entraînement productif, < −30 surcharge.
- **Parcours similaires** (3 novembre 2026) : signature de 100 points le long de la trace ; même parcours si départ à moins de 300 m, distance à ±5 % et écart de forme (distance moyenne au point le plus proche de l'autre trace, dans les deux sens) sous 40 m, et même sens de parcours. Sur les vraies données, un même parcours donne 10 à 30 m d'écart, une variante plus de 60 m.
- **Fiche de sortie** (demande de Greg) : toutes les sorties sont cliquables ; fonds de carte Plan IGN et photos aériennes (Géoplateforme) en France, OpenStreetMap ailleurs ; Leaflet et ECharts embarqués dans l'application.
- **Repères de la page Forme** (demande de Greg) : chaque indicateur est situé dans l'historique (jauge minimum–maximum, plage habituelle des 12 derniers mois, rang, valeur un an plus tôt, record) ; tendance linéaire de l'EF sur 12 mois et depuis le début.
- **Détection des courses** (3 novembre 2026) : score par indice (nom ou description 3, FC moyenne au-dessus d'un seuil selon la durée 2, distance ronde à effort soutenu 2, allure 8 % plus rapide que les sorties comparables 2, top 3 sur une distance 2, charge par heure dans les 10 % les plus élevées 1, départ à plus de 25 km du lieu habituel 1, week-end en matinée 1, moins de 2 % d'arrêts sur route 1) ; proposée à partir de 5 points (réglable). Sur l'historique : 23 candidates, dont toutes les courses connues ; les faux positifs sont surtout des séances de fractionné de préparation. Une course se marque aussi depuis la fiche de la sortie.
- **Accueil** (demande de Greg) : l'écart avec l'an dernier n'est affiché que s'il dépasse 2 % ; à la place, projection de fin d'année au rythme actuel, record annuel, sorties par semaine.
- **Intervalles d'une séance** (demande de Greg, seuils choisis en autonomie le 3 novembre 2026, à valider) : tours de la montre s'ils décrivent la séance (tours marqués effort / récupération par un entraînement structuré, ou au moins 3 tours manuels ; les tours automatiques au km sont ignorés) ; sinon, sur route seulement, détection sur l'allure lissée sur 20 s : deux groupes de vitesse écartés d'au moins 25 %, au moins 3 efforts de 40 s à 20 min, de durées régulières (écart-type sous 35 % de la moyenne), couvrant moins de 60 % de la sortie. Sur l'historique : 39 sorties décrites par les tours, 74 détectées, dont les séances nommées (« 2x8 45/40 » → 16 efforts, « 3x8' » → 3) ; quelques sorties sans nom de séance détectées avec 3 efforts, à surveiller.
- **Classement des meilleurs efforts** sur la fiche de sortie (demande de Greg) : rang dans l'année de la sortie et sur toute la période, parmi les sorties de même terrain ; VAM route et trail confondus.
- **Modifications de Greg du 3 novembre 2026** (étape 8 ter de la phase 2) :
  - liste des sorties : curseurs minimum et maximum de distance et de D+ (choix de Greg), 50 sorties par page par défaut, choix mémorisé dans un cookie ;
  - découplage affiché seulement sur route plate (moins de 10 m de D+ par km) d'au moins une heure, comme sur la page Forme, et signalé comme non pertinent sur une séance fractionnée ; repère de l'EF sur la fiche : médiane des sorties de même terrain dans les 12 mois précédents (au moins 5) ;
  - paliers de montée (100, 200, 500, 1 000 m de D+) : portion la plus rapide pour s'élever de ce dénivelé à l'intérieur d'une même montée (descentes de moins de 20 m tolérées) ; FC moyenne de chaque effort, pondérée par le temps ;
  - VAM : sauts d'altitude de plus de 1 m/s ignorés (GPS ou MNT), et temps lu sur la distance brute du profil (une VAM de 9 195 m/h apparaissait après un pic GPS) ;
  - jauges de la page Forme : forme verte en entraînement productif et frais, jaune en neutre et très frais, rouge en surcharge ; fitness jaune sous la plage habituelle des 12 mois, fatigue jaune au-dessus, montée sur 7 jours rouge au-delà de +8 et jaune au-delà de +5 ou sous −3 ;
  - **VAP** (choix de Greg : formule générique) : coût énergétique de Minetti (2002), pente lissée sur 50 m et bornée à ±45 %, sur le temps en mouvement ; affichée sur les sorties trail. Le modèle allure-pente personnel reste l'idée de la section 7, utile à l'estimateur trail (phase 3) ;
  - **forme du jour** (choix de Greg : FC attendue à la vitesse) : minutes stables (vitesse ajustée régulière à 15 % près par tranches de 20 s, stable depuis 90 s, pas plus lente de 10 % que les 3 minutes précédentes, après 10 min d'échauffement, au moins 1,5 m/s) ; droite FC = a + b × vitesse sur les 90 jours précédents (au moins 60 minutes) ; verdict sur l'écart moyen, conforme à moins de 3 bpm. Sur les 120 dernières sorties : 41 plus en forme, 32 conformes, 28 moins en forme, 19 sans assez de minutes stables (trail en marche surtout).

- **Estimateur dans le menu** (choix de Greg, 3 novembre 2026) : page à part, dans un nouvel onglet « Estimateur » de la navigation.
- **Estimateur, étapes 1 et 2 de la phase 3** (choix faits en autonomie le 3 novembre 2026, à valider par Greg et à confronter à l'erreur mesurée à l'étape 3) :
  - forme actuelle sur une seule fenêtre de 12 semaines, au soir du jour donné (sorties du jour comprises) ; allure en descente = allure habituelle en mouvement par bande de pente (−4 à −10 %, −10 à −20 %, au-delà de −20 %), toutes sorties confondues, pas un effort maximal ; pente lissée sur 50 m, tranches de 2 % stockées par sortie ;
  - exposant de Riegel : pente de log(temps) selon log(distance) sur la frontière des meilleurs efforts route des 2 dernières années (le meilleur de chaque distance de 3 km et plus et de chaque durée de 20 min et plus), borné entre 1,02 et 1,20, 1,06 faute d'au moins 3 efforts couvrant un rapport 3 entre distances. Sur l'historique : 1,165, nettement au-dessus du standard, car les efforts longs sont des sorties d'entraînement (le marathon estimé, 4 h 40, est sans doute pessimiste) ;
  - niveau : chaque meilleur effort route des 12 dernières semaines (6 mois à défaut) est extrapolé, l'estimation la plus rapide est retenue ;
  - fourchette : ±(2 % + 3 % × |ln(distance visée / distance de référence)|) ;
  - D+ sur route : chaque mètre de D+ compte pour environ 6 m de plat (coût de Minetti d'une montée à 5 %), descente neutre, en attendant le modèle allure-pente personnel (étape 4).
- **Validation route** (étape 3 de la phase 3, 3 novembre 2026) : rejeu sur les 3 courses route confirmées (semi 2021, marathons 2022 et 2023), sorties jusqu'à la veille, temps écoulé comme référence. Exposant personnel : erreur moyenne 8,4 %, biais +8,4 % (toujours trop lent), 0 course sur 3 dans la fourchette ; exposant standard 1,06 : erreur et biais +4,4 %. Les références sont des efforts d'entraînement, plus lents que le jour de course : la correction (choix de l'exposant, correction du biais, fourchette) est à trancher avec Greg, la calibration automatique relevant de l'étape 10.
- **Exposant de Riegel** (choix de Greg, 3 novembre 2026, après la validation route) : exposant standard 1,06 au lieu de l'exposant personnel ; l'exposant personnel reste calculé et affiché pour comparaison. Le biais restant (+4,4 %, estimation trop lente) n'est pas corrigé pour l'instant.
- **Modèle allure-pente personnel** (étape 4 de la phase 3, choix faits en autonomie le 3 novembre 2026, à valider) : sorties des 12 derniers mois, route et trail ; dans chaque sortie, vitesse de chaque tranche de 2 % (au moins 1 min) rapportée à la vitesse sur le plat (−2 à +2 %, au moins 5 min) de la même sortie, ce qui neutralise l'intensité ; moyenne géométrique pondérée par le temps (plafonné à 10 min par sortie), tranche retenue à partir de 3 sorties, lissage sur les tranches voisines, facteur de la dernière tranche conservé au-delà. Ce n'est pas un effort strictement égal mais la façon habituelle de courir les pentes (marche, retenue en descente). Sur l'historique (127 sorties) : ×1,36 à +10 %, ×2,01 à +20 %, ×2,63 à +30 % (Minetti : ×1,66, ×2,50, ×3,49) ; ×0,95 à −10 %, ×1,23 à −20 %, ×1,63 à −30 % (Minetti : ×0,60, ×0,50, ×0,68). Limite : en très forte montée, une marche sous 0,5 m/s à l'horizontale est comptée comme un arrêt.
- **Périodes réglables** (demande de Greg, 3 novembre 2026) : sur la page Estimateur, fenêtre de la forme actuelle (6, 8, 10 ou 12 semaines, 12 par défaut ; sert aussi aux références de l'estimateur route et à sa validation) et période du modèle allure-pente (6 mois, 12 mois, 2 ans ou tout l'historique, 12 mois par défaut), mémorisées dans un cookie. Erreur route sur les 3 courses : 6,8 % à 6 semaines, 5,2 % à 8, 4,4 % à 10 et 12. Les autres seuils du modèle restent fixes.
- **Estimateur trail sur GPX** (étape 5 de la phase 3, choix faits en autonomie le 3 novembre 2026, à valider) : altitude du GPX (filtre médian sur 3 points à pas de 10 m, pas de MNT) ; distance équivalente plat = somme des pas de 10 m × facteur du modèle allure-pente ; temps = Riegel 1,06 depuis le meilleur effort route récent tant que la course dure moins de 2 h, puis T = T(2 h) × (distance équivalente / distance équivalente à 2 h)^k, k exposant de fatigue = pente log(temps) / log(distance équivalente) de la meilleure sortie par tranche de durée à partir de 2 h (toutes années jusqu'au jour donné, au moins 3 tranches, borné entre 1,06 et 1,35, 1,15 par défaut) ; passages à allure régulière (à pente égale) pendant 2 h puis allure ∝ t^((k−1)/k), sans saut ; fourchette de la route plus 5 % par facteur e au-delà de 2 h ; tronçons coupés aux sommets et creux de plus de 25 m, « plat » sous 3 % ; temps en mouvement, ravitaillements non comptés. Pourquoi la fatigue : avec Riegel seul, les courses trail de plus de 3 h étaient sous-estimées de 17 à 32 %. Essai sur les 5 courses trail rejouées avec leur propre trace et la forme de la veille : +8,4 %, +4,6 %, +1,2 %, +6,9 %, −6,9 % (erreur moyenne 5,6 %, validation formelle à l'étape 7). GPX envoyé brut par la page (pas de dépendance d'upload), stocké sous l'empreinte de son contenu.
- **Altitude des GPX** (signalé par Greg le 3 novembre 2026 : 983 m de D+ affichés contre 873 m sur Tracedetrail pour le Trail des Petites Roches) : l'altitude du GPX est bruitée (1 566 m de D+ brut) et l'estimateur ne la filtrait que par une médiane sur 3 points. Désormais, comme pour les sorties sans baromètre : altitude du MNT le long de la trace (IGN, Copernicus ailleurs ; MNT retenu s'il couvre 90 % du parcours, mis en cache à côté du GPX), celle du GPX à défaut, filtrée avec les réglages de D+ de l'admin (médiane, seuil d'hystérésis du MNT de 3,5 m). Résultat : 900 m (MNT IGN) ; l'altitude du GPX filtrée de la même façon donne 873 m. Distance : 14,4 km en distance horizontale (comme la montre et le modèle allure-pente) contre 14,6 km annoncés par le site.
- **Tronçons du GPX** (demande de Greg, 3 novembre 2026 : une montée faible suivie d'une forte apparaissait comme une seule montée à pente moyenne ; ajouter « vallonné ») : le profil (un point tous les 50 m) est approché par une suite de droites, découpage optimal par programmation dynamique (chaque coupure doit réduire l'écart quadratique au profil d'au moins 2 000 m², tronçons de 100 m à 6 km) ; classes de pente : plat sous 3 %, douce sous 8 %, moyenne, forte à partir de 15 % ; voisins de même classe fusionnés ; « vallonné » = suite de bosses de moins de 500 m (pas en forte pente, montées et descentes mêlées) ou tronçon plat ou doux, cumulant au moins 20 m de montée et 20 m de descente. Trail des Petites Roches : 10 tronçons, dont plat du km 2,0 au 3,5 (+1 %) puis forte montée du km 3,5 au 5,4 (+20 %), et vallonné du km 5,4 au 8,3 (+124 / −101 m).
- **Ravitaillements sur un GPX** (étape 6 de la phase 3, 3 novembre 2026 ; périmètre réduit par Greg aux ravitaillements, sans estimation sans GPX ni barrières horaires ; choix faits en autonomie, à valider) : ravitos proposés d'après les points nommés (waypoints) du GPX à moins de 200 m de la trace, hors des 300 premiers et derniers mètres, sans arrêt ; Greg les corrige et les enregistre (km, nom, arrêt en minutes, 0 à 120 ; 50 au plus), avec le parcours dans `data/gpx/<id>.json`. Chaque arrêt s'ajoute aux passages qui suivent et au temps final ; la fourchette et les allures portent sur le temps en mouvement, les arrêts étant ceux que Greg prévoit. Pour chaque ravito puis l'arrivée : distance, D+ et D− et temps en mouvement depuis le point précédent, arrivée avec sa fourchette, arrêt et départ ; repères sur le profil.
- **Arrêts et temps total** (décision de Greg, 3 novembre 2026 : « un arrêt permet de recharger les batteries, ce n'est pas anodin ») : l'estimation trail vise le temps total, arrêts compris. Faute d'arrêt saisi aux ravitos, une part d'arrêt est ajoutée : part du temps total = a × (heures en mouvement)², a calé par moindres carrés sur les courses trail confirmées jusqu'à la veille (choix de Greg : historique plutôt qu'arrêts saisis seulement) ; 0,0015 faute de course (1,4 % à 3 h, 5,4 % à 6 h), plafonnée à 30 %. Choix faits en autonomie, à valider : le carré plutôt qu'une part proportionnelle à la durée (proportionnelle, calée sur l'historique à 1,3 % par heure, elle donnait 9 % d'arrêt au Néron pour 2,1 % réels, et 6,8 % d'erreur au lieu de 5,3 %) ; courses seulement, car les sorties trail d'entraînement s'arrêtent bien plus (médiane de 23 à 25 % au-delà de 2 h, contre 0,2 à 2,8 % en course jusqu'à 5 h 30 et 18 % sur les 11 h des Mystères du Drac). Arrêts répartis au prorata du temps dans les passages. La valeur par défaut est proche de l'historique de Greg : le rejeu des Mystères du Drac (première course trail, sans course antérieure) n'en est pas tout à fait indépendant.
- **Validation trail** (étape 7 de la phase 3, 3 novembre 2026) : rejeu sur les 5 courses trail confirmées, leur propre trace servant de GPX (altitude retenue pour le D+ de la sortie, baromètre ou MNT, filtrée avec le seuil de sa source), avec la forme de la veille (niveau route, modèle allure-pente, exposant de fatigue et part d'arrêt jusqu'à la veille) ; référence = temps écoulé (temps total), avec pour diagnostic l'écart du temps en mouvement estimé au temps en mouvement réel. Modèle allure-pente sur 12 mois : erreur moyenne 5,3 % en temps total, biais +2,0 %, 5 courses sur 5 dans la fourchette (Côte rouge −8,3 %, Vizille 30 km +8,2 %, Néron +3,6 %, Vizille court +1,2 %, Drac +5,4 %) ; en mouvement 4,0 %, biais +1,2 %. Sur tout l'historique : 5,6 %, 4 sur 5. Sans arrêts, l'erreur en temps total était de 7,8 % (Drac −15,4 %).
- **Courses proches et effet de la forme** (étape 8 de la phase 3, 3 novembre 2026 ; méthode choisie par Greg : relation personnelle entre fitness et niveau ; seuils choisis en autonomie, à valider) : sous chaque estimation (route et GPX), les 3 courses confirmées les plus proches, écart = |ln(distance / distance visée)| + |ln((D+ + 100) / (D+ visé + 100))|, avec le temps réel (arrêts compris) et la fitness du jour. Effet de la forme : chaque semaine de l'historique jusqu'au jour donné, niveau = 10 km estimé par l'estimateur route sur la fenêtre de la forme, mis en face de la fitness du jour ; pente de log(niveau) selon la fitness, au moins 26 semaines, bornée entre −2 % et 0 par point, −0,8 % faute d'historique. Sur l'historique de Greg : −0,81 % par point (r = −0,40 sur 269 semaines ; de −0,45 à −1,1 % selon les années). Scénarios : fitness −10, −5, +5 et +10 le jour J. En attendant la fitness projetée du coach (phase 4), c'est une tendance moyenne, sans fraîcheur ni affûtage.
- **Courses suivies** (étape 9 de la phase 3, 3 novembre 2026 ; historique choisi par Greg : enregistrement hebdomadaire et rejeu des semaines passées ; le reste en autonomie, à valider) : carte « Courses suivies » en haut de la page Estimateur (vue d'ensemble : date et compte à rebours, parcours, prédiction réaliste et fourchette, évolution sur 4 semaines, objectif et écart) et une page par course (`/estimateur/courses/<id>` : prédiction semaine après semaine avec sa fourchette et l'objectif, historique, courses proches et effet de la forme, modification, suppression). Parcours : un GPX importé (estimateur trail, temps total avec les ravitos du parcours) ou une distance avec D+ (estimateur route). Chaque lundi, après la synchro du jour (ou à partir de l'heure de synchro si elle est désactivée ou sans compte Garmin), le planificateur enregistre la prédiction de chaque course à venir avec la forme du dimanche soir ; à l'ajout ou au changement de parcours, les 12 semaines précédentes sont rejouées et marquées « rejouées ». Périodes fixes (forme sur 12 semaines, pentes sur 12 mois), indépendantes des réglages de la page, pour une courbe comparable d'une semaine à l'autre. Plus de prédiction après la date de la course ou une fois la sortie reliée.
- **Après la course et calibration** (étape 10 de la phase 3, 3 novembre 2026 ; calibration choisie par Greg : correction proposée, activée par lui ; le reste en autonomie, à valider) : une course suivie passée est reliée à la sortie du jour (à un jour près), de distance à ±15 % de celle du parcours et, pour un GPX, partie à moins de 3 km de son départ ; la plus proche en distance l'emporte, et la sortie est confirmée comme course si elle n'était pas classée. Liaison à la synchro quotidienne et à l'ouverture des pages ; Greg peut relier une autre sortie (± 3 jours) ou délier, choix que l'automatique ne touche plus (migration `0015`). Résultat : temps écoulé face à la dernière prédiction enregistrée avant la course, écart en %, fourchette, objectif. Calibration : sur le rejeu de toutes les courses confirmées (périodes par défaut), facteur = 1 / moyenne géométrique de (estimé / réel), proposé par terrain à partir de 3 courses ; dans l'admin, Greg l'applique (facteur figé dans les réglages, entre 0,8 et 1,2), le met à jour ou le retire. Il multiplie toutes les durées estimées de ce terrain (estimations, tableau, tronçons, ravitos, courses suivies, à l'affichage : l'historique enregistré reste brut) ; les mesures de précision restent sans correction.
- **Estimé et réel sur la fiche d'une course** (étape 10 bis de la phase 3, 3 novembre 2026 ; graphique choisi par Greg : écart cumulé au fil des km) : sur la fiche d'une sortie confirmée comme course, un bouton rejoue l'estimateur trail sur sa propre trace (altitude retenue pour son D+), avec la forme de la veille et avec celle d'aujourd'hui, en temps total (part d'arrêt habituelle comprise) et sans correction ; calcul à la demande (environ 0,7 s), lancé d'office depuis le lien « Comparer l'estimé et le réel » d'une course suivie. Tableau des deux estimations face au temps réel, puis courbe de l'écart cumulé (temps réel − temps estimé, tous les 100 m, positif = en retard), profil d'altitude en fond. Les distances de la montre sont ramenées à celle du profil au prorata. L'estimateur trail sert aussi pour une course sur route (sur le plat, il revient à Riegel jusqu'à 2 h).
- **Niveau ajusté par la FC** (3 novembre 2026, à la suite de la remarque de Greg sur les sauts de prédiction et le manque de séance rapide) : chaque référence route (meilleurs efforts de 3 km et plus, de 20 min et plus) est ramenée à l'aérobie du jour, son temps multiplié par le rapport de la vitesse à FC de référence à sa date et au jour de l'estimation ; vitesse lue sur la droite FC / vitesse des minutes stables des 12 mois précédents (hr_speed.SpeedTrend), FC de référence = 85 % de la LTHR (151 bpm pour Greg). Références cherchées sur 4 mois (REFERENCE_DAYS, choix de Greg), 6 mois à défaut, quelle que soit la fenêtre de la forme. Essais sur le rejeu des 8 courses (3 route, 5 trail), forme de la veille : extrapoler la droite FC / vitesse jusqu'à la LTHR donne des temps 13 à 27 % trop rapides (relation non linéaire, LTHR tirée d'un trail) et a été écarté ; ajustement des références : 12 semaines 3,6 % d'erreur (aussi instable qu'avant), 4 mois 4,6 % (15 sauts de plus de 5 % d'une semaine à l'autre au lieu de 20), 6 mois 6,2 % (7 sauts, biais −3,6 %), 12 mois 8,6 %. Sans ajustement : 5,0 %, biais +2,9 %. Après intégration : route 5,0 % (−0,6, −13,4, +1,0), trail 3,7 % (−7,9, +3,6, +3,3, +1,4, −2,4). Limite : avec 4 mois, une prédiction reste lente tant qu'aucune séance rapide n'entre dans la fenêtre (saut de 3 h 51 à 3 h 27 sur Côte rouge en septembre 2026), seuls 6 mois le suppriment. Écarté aussi : ajustement par la fitness au moment de la référence (4,3 %, moins stable) ; fitness réelle du jour J, même connue d'avance, n'apporte presque rien (4 semaines avant : 5,9 → 5,6 % ; la veille, elle dégrade car l'affûtage baisse la fitness) : la forme du jour J (fitness et fraîcheur) relève du coach, phase 4.
- **Surajustement** (remarque de Greg, 3 novembre 2026 : « on ajuste un peu au pif pour tomber sur les données que l'on veut ») ; décision de Greg : garder les réglages, les figer et les généraliser. Les réglages de l'estimateur (fenêtres, exposant de Riegel standard, part d'arrêt au carré de la durée, ajustement par la FC) ont été choisis en rejouant les courses de Greg jusqu'au 3 novembre 2026 (estimator.TUNED_UNTIL) : l'erreur mesurée sur ces courses est flatteuse. Ils sont désormais figés ; la page sépare cette erreur de la vraie précision, mesurée sur les prédictions des courses suivies enregistrées avant le départ et sur le rejeu des courses suivantes. Ce qui est appris automatiquement sur les données de chaque coureur (modèle allure-pente, exposant de fatigue, part d'arrêt, droite FC / vitesse, pente fitness / niveau) se recalcule pour toute autre personne ; les valeurs par défaut, utilisées seulement faute de données, ne sont plus tirées de l'historique de Greg : part d'arrêt 0,1 % par heure² (au lieu de 0,15), effet de la forme −0,5 % par point (au lieu de −0,8), FC de référence relative à la LTHR. Pour une autre personne avec peu de courses, la précision n'est pas mesurable au début.
- **VAP selon Strava** (demande de Greg du 4 novembre 2026 : allures VAP trop lentes dans les grosses descentes ; remplace la VAP de Minetti décidée le 3 novembre) : facteur d'effort selon la pente de la GAP de Strava (« An improved GAP model », 2017, calé sur la FC), valeurs relevées par Aaron Schroeder (paquet specialsauce, MIT) de −45 à +45 % et interpolées linéairement ; pente toujours lissée sur 50 m et bornée à ±45 %. Minetti donnait 0,68 à −30 % (une descente à 6:00/km valait 8:47/km de VAP), Strava 1,50 (4:00/km). Sur les 12 dernières sorties trail de Greg, la VAP globale gagne 12 à 60 s/km. Le modèle allure-pente de l'estimateur est comparé à cette courbe ; l'équivalent plat du D+ de l'estimateur route (réglage figé) garde Minetti (6 m par mètre de D+, 3,6 m avec Strava).
- **Principe d'adaptation au coureur** (Greg, 4 novembre 2026) : les calculs s'adaptent aux courses et aux sorties de chaque coureur, et leur paramétrage évolue avec le temps et les données ; on ne suroptimise pas sur les données de Greg, tout doit marcher pour quelqu'un d'autre. Un réglage n'est retenu que s'il s'appuie sur un principe général (physiologie, statistique) ou s'il est appris automatiquement sur les données du coureur ; l'historique de Greg sert à vérifier, pas à caler des constantes.
- **Thèse de L. Lerebourg** (*Prédiction de la performance en course à pied : demi-fond et fond*, Rouen, 2021), comparée à l'estimateur le 4 novembre 2026, sept pistes rejouées sur les 8 courses confirmées de Greg (3 route, 5 trail) :
  - retenue : limites à 95 % de Bland-Altman (biais ± 1,96 écart-type) à côté de l'erreur moyenne, pour la route, le trail et la vraie précision, indicatives sous 10 courses (règle statistique). Données de Greg : route −20 à +12 % (écart-type 8,1), trail −10 à +10 % (5,1), tout −14 à +10 % (6,1) ; erreur moyenne 4,2 %, dans la fourchette de la thèse (±4 à 9 % avec deux courses à fond) ;
  - notées en section 7 : fourchette calée sur ces limites, progression d'une saison à l'autre ;
  - écartées pour Greg, à revoir avec d'autres coureurs ou plus de courses : interpolation entre deux références (ses courses route sont toujours plus longues que ses références d'entraînement, 22 km au plus), exposant tiré des courses (deux paires semi / marathon seulement, k = 1,22 et 1,27 ; rejeu : k = 1,06 → 4,9 % d'erreur, 1,10 → 8,5 %, 1,15 → 12,0 %), exposant de fatigue au-delà de 2 h sur route (9,1 %, le marathon de 2023 passe de 3:49 à 4:27 : l'exposant, tiré de sorties en montagne, convient au trail), indice d'endurance (l'exposant personnel passe de 1,06 à 1,17 de 2024 à 2026 parce que le marathon de 2023 sort de la fenêtre de 2 ans, pas parce que l'endurance change). Le marathon de 2022 (−13,5 %, 3:56 trois mois après un semi en 1:38) porte presque toute l'erreur route ;
  - écartées : nomogrammes (équivalents à la loi puissance une fois automatisés), vitesse critique (valable de 3,5 à 35 min), KNN et réseaux de neurones (une population de coureurs est nécessaire), équation du steeple.
- **Indice de confiance d'une prédiction** (demande de Greg, 4 novembre 2026 ; règles générales, aucune constante calée sur Greg) : chaque critère défavorable retire un point ; 0 : élevée, 1 ou 2 : moyenne, 3 et plus : faible ; les raisons sont affichées sous l'estimation (route et GPX). Critères : distance visée plus de 2 fois celle de la référence (un point) ou plus de 4 fois (deux points ; en trail, distance où Riegel s'arrête, à 2 h, la courbe de fatigue prenant le relais), l'extrapolation dégradant la prédiction (Lerebourg 2021) ; référence de plus de 8 semaines (adaptations et désentraînement aérobies en 6 à 8 semaines) ; ajustement par la FC de plus de 5 % ; fenêtre de secours de 6 mois ; moins de 3 courses du terrain pour mesurer la précision, ou limites à 95 % au-delà de ±10 % (±4 à 9 % pour les bonnes méthodes, Lerebourg 2021) ; course 50 % plus longue que la plus longue sortie ; moins de 90 % du parcours sur des pentes couvertes par le modèle allure-pente ; exposant de fatigue par défaut. Données de Greg au 4 novembre : 10 km moyenne, marathon faible (référence de 20 min, ×9,8), ses trois GPX moyenne (×4,5 à 5,4 jusqu'à 2 h, précision trail ±10 %).
- **Repères physiologiques sur la page Forme** (demande de Greg, 4 novembre 2026, avec l'allure au seuil ; méthodes générales) : VMA = vitesse du meilleur effort route de 5 min sur 12 semaines, 6 mois à défaut (VMA tenue de 4 à 11 min, 6 en moyenne, Billat) ; VO2max = 3,5 ml/kg/min par km/h de VMA (Léger et Mercier) ; FC au seuil = meilleure FC moyenne tenue une heure sur 12 mois, en % de la FC max réglée ; allure au seuil = distance tenue une heure d'après le niveau de l'estimateur (références route sur 4 mois ajustées par la FC, Riegel). Données de Greg au 4 novembre : VMA 13,7 km/h (5 min du 3 septembre, sans doute sous-estimée : son meilleur 5 km 2025 est à 13,3 km/h, couru à environ 93 % de la VMA), VO2max 48, FC au seuil 178 bpm soit 94 % de la FC max (trail du 11 juillet, chaleur et dérive possibles : au-dessus du repère de 85 à 92 %), allure au seuil 4:58 /km (88 % de la VMA).
- **Coach, étape 1 de la phase 4** (choix de Greg, 4 novembre 2026) : onglet « Coach » dans le menu, après Estimateur ; **calendrier du coach séparé des courses suivies** de l'estimateur (remplace « une course suivie passe en échéance » du plan) : chaque échéance a un nom, une date obligatoire, une priorité A, B ou C obligatoire, un parcours (GPX importé ou distance et D+) et un objectif ; une course suivie peut servir à pré-remplir la saisie. Objectif proposé : temps réaliste de l'estimateur au jour de la saisie (correction de l'admin comprise), accepté ou modifié. Disponibilités facultatives, par jour (jour possible et durée maximale), pré-remplies depuis les 12 dernières semaines : un jour est habituel si une sortie y a eu lieu au moins une semaine sur deux (règle de majorité), durée habituelle = médiane du temps en mouvement ce jour-là. Habitudes : parcours (détection des parcours similaires) qui fait au moins la moitié des sorties d'un jour habituel, proposé pour confirmation. Règles de majorité générales, aucune constante calée sur Greg.
- **Coach, habitudes et disponibilités revues** (remarques de Greg du 4 novembre 2026 : sa Bastille du lundi ne ressortait pas, ses tracés changent mais passent par le sommet ; besoin d'un jour « optionnel ») : une habitude est un lieu de passage, plus un tracé identique. Carte découpée en cases de 200 m (ordre de grandeur de la précision des tracés résumés) ; pour un jour possible, la case traversée par au moins la moitié des sorties de ce jour sur les 26 dernières semaines (une demi-année, pour voir un lieu revenir), la plus éloignée du départ, hors de ses abords (400 m) ; nom repris de la dernière sortie, modifiable. Données de Greg : lundi, 13 sorties sur 15 passent par le sommet de la Bastille, à 0,9 km du départ, alors que 9 tracés différents. Disponibilités par jour : oui, optionnel ou non ; déduites : oui au moins une semaine sur deux, optionnel au moins une semaine sur quatre (règles de proportion générales). Nombre maximal de séances par semaine, facultatif (Greg, même jour : 3 jours oui et 2 optionnels mais 4 séances au plus) : le coach remplit d'abord les jours oui, puis les optionnels, sans dépasser ce nombre ; vide, pas de limite autre que les jours.
- **Coach, étape 2 : plan périodisé vers la course A** (choix de Greg du 4 novembre 2026 : les quatre réglages recommandés ; le reste en autonomie sur des repères généraux, à valider) : plan recalculé à chaque ouverture (fonction pure versionnée, coach_plan.py), de la semaine en cours à celle de la course A.
  - Affûtage selon la durée estimée de la course : une semaine sous 1 h 30, deux au-delà (Bosquet 2007 : 8 à 14 jours), charge réduite de 40 puis 60 % (une semaine : 50 %), intensité gardée ; veille de course au repos.
  - Avant l'affûtage, phases à rebours : spécifique, développement, foncier, environ 30 / 30 / 40 % des semaines (spécifique seul sous 3 semaines, sans foncier sous 6) ; cycle 3 semaines de charge et 1 allégée à −30 %, compté à rebours depuis l'affûtage (la dernière semaine avant l'affûtage est une semaine de charge).
  - Charge : fitness (modèle de Banister de la page Forme) montée d'au plus +5 par semaine de charge, visée la plus haute atteignable et jamais plus de 10 % au-dessus du pic des 12 derniers mois ; charge hebdomadaire (HRSS) qui produit cette fitness, bornée par le temps disponible (durées maximales des jours retenus).
  - Séances : nombre = maximum par semaine (sinon jours possibles), jours « oui » d'abord puis optionnels, un jour de repos au moins ; sortie longue le jour au temps maximal le plus long ; une séance de qualité, deux à partir de 5 séances, jamais la veille ou le lendemain d'une autre séance dure ni de la sortie longue ; habitude gardée à sa place, avec un rôle selon la phase ; types selon la phase (foncier : lignes droites ou côtes courtes ; développement : seuil, fractionné ; spécifique : allure course sur route, côtes longues et sortie longue avec D+ en trail ; affûtage : rappel d'allure).
  - Durées : charge convertie en minutes avec la charge par heure du coureur, médiane HRSS par heure de ses sorties faciles (moins de 10 % du temps en zone 3 et plus) et de ses séances (au moins 20 %), sur 12 mois ; à défaut, 60 et 85 HRSS par heure (endurance et séance au voisinage du seuil, 100 = une heure au seuil).
  - Données de Greg au 4 novembre (Trail des petites roches, A, 25 novembre, 14,4 km, 900 m D+, objectif 1:38:58) : 4 semaines (2 de spécifique, affûtage, course) ; charge par heure mesurée 37 en endurance (77 sorties) et 59 en séance (31) ; ses 4 jours (50, 50, 70 et 120 min) plafonnent la charge à 175 par semaine, soit une fitness d'environ 25, sous son pic des 12 mois (27,4) : le plan le signale. Côtes longues sur la Bastille du lundi, sortie longue le samedi avec 930 m de D+.
  - Remarques de Greg du même jour : le plan affichait une fitness qui baisse (21,6 → 19,0), décourageant et mal expliqué ; un rappel d'allure en min/km pour un trail n'a pas de sens ; page trop mélangée. Corrigé : fitness et fatigue simulées jour par jour (charge réelle avant aujourd'hui, séances prévues ensuite), affichées en trois temps (aujourd'hui, au plus haut avant l'affûtage, jour J avec la fraîcheur) et expliquées ; fraîcheur du jour J en % de la fitness (mêmes seuils que la page Forme, rapportés à la fitness pour valoir quel que soit le volume, convention d'intervals.icu ; au-delà de 25 % « très frais, bien reposé ») ; en trail, rappel en côte à l'effort de course et aucune allure course en min/km (le seuil et le fractionné sur le plat restent en développement) ; page Coach en sous-onglets Plan (par défaut, course A en tête), Échéances, Disponibilités et habitudes. Données de Greg : fitness 21,4, au plus haut 21,7, jour J 20,6 avec +3,5 de fraîcheur, soit 17 % : frais.
  - Séances revues (remarque de Greg du même jour : durées pas rondes, récupérations absentes ; inspirations demandées : time-to-run, Running-Plan-Generator, trail-running-planner, OpenAthlete) : bibliothèque de séances structurées (coach_workouts.py) en étapes typées (échauffement, effort, récupération, retour au calme) avec la récupération toujours dite (durée et façon : trot, marche, redescente) et une cible par étape : allure en plage (±2 %, ±1 % pour l'allure course), FC en plage en % de la LTHR (zones de Friel), effort perçu sur 10 (seul repère avec la FC en côte et en trail). Paliers de progression par type (seuil 3 × 8 min à 2 × 20 min ; VMA 30/30 puis 400 à 1 000 m ; côtes courtes 8 à 12 × 30 s ; côtes longues 4 × 4 à 3 × 8 min ; allure course 3 × 10 à 3 × 15 min) ; palier ramené au temps du jour, échauffement raccourci en dernier recours. Durées arrondies à 5 min ; footing d'au moins 30 min, sinon un footing saute ; sortie longue d'abord ; une seule séance de qualité quand deux prendraient plus de 60 % de la charge ; distance approximative des footings et sorties longues sur route avec l'allure d'endurance du coureur (sorties faciles sur route plate). Repris : présentation de time-to-run (type, volume rond, structure), étapes et cibles en plage d'OpenAthlete (idée seulement, AGPL), volume en temps, km et D+ de trail-running-workout-planner ; Running-Plan-Generator (répartition fixe des volumes, sans licence) n'apporte que l'idée d'une sortie moyenne, notée en section 7.
  - Variété et cohérence trail (remarque de Greg du même jour : séances répétitives ; sortie longue « en endurance » avec le D+ par heure de la course, contradictoire ; récupérations des côtes mal dites ; recherche demandée) : catalogue de variantes par créneau et par phase, route ou trail, qui tournent d'une semaine à l'autre (le palier monte à chaque tour). Qualité trail : côtes courtes, fartlek, marche rapide en côte (foncier) ; seuil, VMA en côte, montée continue au seuil (développement) ; côtes longues, montée continue, descente travaillée, marche rapide (spécifique). Route : fartlek, côtes courtes ; seuil, tempo ; allure course, tempo. Semaine allégée : sprints en côte (10 s, récupération complète en marchant) ou fartlek. Sorties longues : classique, progressive (route) ; vallonnée, avec descentes, spécifique (une montée de 15 à 20 min à l'effort de course au milieu) en trail. D+ des sorties en endurance tiré de la vitesse de montée du coureur en endurance (médiane D+ par heure de ses sorties faciles de plus de 15 m/km sur 12 mois ; 300 m/h à défaut), avec la consigne de marcher dans les montées raides pour rester sous la FC visée ; footings vallonnés et sur le plat en alternance, lignes droites une semaine sur deux. Récupération des côtes : redescente au trot, de 1 à 3 fois l'effort, chiffrée. Repères : World Athletics, TrainingPeaks, vert.run, campus.coach, u-run (sprints de moins de 10 s, côtes de 30 s à 1 min, côtes longues de 3 min et plus, montée continue, descente à introduire progressivement, récupération en descente). Données de Greg : 359 m/h en endurance (39 sorties), contre 545 m/h en course : 105 min en endurance, environ 630 m de D+.
  - Bénéfice du plan en un coup d'œil (remarque de Greg du même jour : impression de régresser avec le plan) : comparaison « avec le plan » et « sans plan » (charge moyenne des 12 dernières semaines pleines, celle qui entretient la fitness actuelle, sans affûtage ; même modèle de Banister, même départ) : fraîcheur le jour J, régularité (charge d'une semaine de charge face à la semaine médiane des 12 semaines), travail spécifique (séances en côte, sorties longues), fitness au plus haut ; graphique jour par jour de la fitness et de la fraîcheur, avec et sans plan. Aucun gain de temps affiché : l'effet de la fraîcheur sur le temps n'est pas modélisé. Données de Greg (course à 5 semaines) : jour J +6,1 (31 %, très frais) contre −0,2 sans plan ; 172 par semaine contre une semaine médiane de 92 (moyenne 154, portée par trois grosses semaines en montagne) ; 4 séances en côte et 5 sorties longues ; fitness 21,4 → 21,9 contre 22,0 sans plan : en 5 semaines avec l'affûtage et 290 min de disponibilités, le plan ne peut pas faire monter la fitness, son bénéfice est la fraîcheur, la régularité et le travail spécifique.
  - Correction (remarque de Greg du même jour : « 290 min par semaine et la fitness ne progresse pas ») : le cycle 3 + 1 compté à rebours plaçait une semaine allégée dès la première semaine du plan ; une semaine allégée ne vient plus qu'après au moins 2 semaines de charge du plan. Analyse sur les préparations de Greg : Madrid 2023, fitness 15,0 → 23,8 en 8 semaines à environ 230 min par semaine (3 ou 4 sorties, environ 47 HRSS par heure, route) ; Rome 2022, 13,9 → 23,4 en 6 semaines. Aujourd'hui, départ à 21,4 (déjà proche de ce qu'entretiennent 255 min d'endurance sur sentier, environ 24), 37 HRSS par heure en endurance (sentier, marche), plan de 5 semaines dont 2 d'affûtage : gain faible. La montée de la fitness dépend de l'écart entre la charge et la fitness de départ, de la charge par minute (intensité) et de la durée du plan.
  - Choix de Greg à la suite : affûtage d'une semaine pour une course de moins de 2 h (au lieu de 1 h 30), deux au-delà ; une semaine de charge sur deux, la sortie longue finit par 15 à 20 min en allure soutenue (zone 3), sa durée réduite de l'équivalent de cette charge en plus ; plafond de charge calculé sur le temps disponible réparti en 80/20 (et non tout en endurance), les jours restant bornés par leurs durées maximales ; charge d'une séance facile comptée avec ses étapes d'effort. Données de Greg : 270 à 280 min par semaine sur 290, fitness 21,4 → 24,3 au plus haut, 23,2 le jour J, frais (17 %) ; sans plan 22,0 et −0,2 ; équilibre à ce temps environ 28.
  - Plan de la course de mai de Greg (Raidlight Semi Trail, 24 km, 1 400 m de D+, 22 mai 2027, 29 semaines) : trois choix de Greg du 4 novembre 2026, les deux premiers posés à chaque coureur dans l'onglet Disponibilités et habitudes (« Ton plan ») car ils dépendent de lui. Montée du volume : charge d'une semaine de charge au plus +10 % (prudent, par défaut) ou +15 % (choix de Greg) sur la précédente, en partant de la charge qui entretient la fitness actuelle (7 × fitness) ; après une allégée, retour au niveau d'avant. Sorties longues allongées (oui par défaut) : une semaine de charge spécifique sur deux, la dernière juste avant l'affûtage, la sortie longue dépasse le jour le plus long, en progression régulière jusqu'à 90 % de la durée de la course, 3 h au plus, prise sur les footings et signalée « à caler ». D+ de chaque semaine affiché (somme des séances : montées à la vitesse de montée en endurance, × 1,3 dans les efforts en côte) et, en phase spécifique d'un trail, le D+ de la course visé, avec tous les footings vallonnés. Rappel de la semaine de course 3 jours avant, sinon 4, 2 en dernier recours : les deux derniers jours restent faciles (remarque de Greg du même jour sur la fraîcheur ; garder un peu d'intensité en coupant le volume, Bosquet 2007). Données de Greg : 255 à 295 min par semaine, sorties longues de 145 et 160 min en S25 et S27, 1 100 à 1 380 m de D+ par semaine en spécifique pour 1 440 visés, fitness 21,4 → 26,0, 23,5 le jour J, très frais (31 %) ; rappel le mardi (pas de mercredi possible).
- **Coach, étape 6 : plusieurs courses** (demande de Greg du 4 novembre 2026 : l'ajout d'une échéance doit recalculer le plan ; repères généraux choisis en autonomie, à valider) : le plan vise la prochaine course A, sans A la prochaine course du calendrier (après la course A, il se reconstruit ainsi autour de la suivante) ; les autres courses, à venir et passées depuis moins de 21 jours, y sont placées à leur date (la course prend son jour, même hors disponibilités, et sa charge s'ajoute à la semaine). Course B : mini-affûtage, 3 jours sans séance dure ni sortie longue, veille au repos, une seule séance de qualité dans la semaine, entraînement autour réduit de moitié. Course C : courue comme une grosse séance, elle remplace la séance clé (et la sortie longue si elle dure au moins 1 h), entraînement autour −30 %. Récupération après chaque course : un jour sans séance dure ni sortie longue par 3 km d'effort (distance + 1 km par 100 m de D+ ; repère de Daniels, un jour facile par 3 000 m de course), moitié pour une C, de 2 à 21 jours ; charge réduite au prorata (une semaine entière : −50 %), affichée dans la semaine. Conflits signalés avec des solutions au choix du coureur (boutons) : deux courses A à moins de 8 semaines (passer l'une en B), une B moins de 3 semaines avant une A (passer en C), une C dans la semaine d'une A (la retirer). Les courses s'informent entre elles : l'estimation de chaque échéance suit la forme du jour, résultats des courses passées compris ; un objectif à plus de 3 % de l'estimation est signalé « à revoir », avec la dernière course passée depuis moins de 4 semaines. Données de Greg : Trail des petites roches (B, dimanche 8 novembre, 1 h 39) dans le plan de la course de mai : semaine de la course 239 min dont la course, puis 8 jours de récupération (jusqu'au 16 novembre), semaine suivante en footings (160 min), fitness 21,4 → 21,9 puis 20,7, plan inchangé ensuite (pic 26,0, jour J 23,4, très frais).
- **Coach, jours optionnels** (remarque de Greg du 4 novembre 2026 : disponible un weekend sur trois seulement ; choix de Greg : en bonus, hors du plan) : le plan (sortie longue, séances, footings, capacité de charge, sorties allongées) tient sur les jours « oui » ; le jour optionnel le plus long reçoit une sortie bonus marquée « optionnelle », sortie longue en endurance ou, les semaines où la sortie longue est allongée, l'allongée elle-même ; elle n'entre ni dans la charge prévue ni dans la fitness simulée. Sans aucun jour « oui », les jours optionnels portent le plan. Données de Greg : 170 min de jours « oui » (lundi 50, mardi 50, jeudi 70) : la fitness simulée baisse de 21,4 à environ 17, 13,6 le jour J ; aujourd'hui elle tient grâce aux weekends. Courses mises en avant en tête du plan (demande de Greg du même jour).
- **Coach, fréquence des jours optionnels** (choix de Greg du 4 novembre 2026, à la suite : un weekend sur trois) : chaque jour optionnel a une fréquence, une semaine sur 1 à 4, pré-remplie d'après l'historique (1 / part des semaines avec une sortie ce jour, entre 2 et 4) ; les semaines n, 2n..., il entre dans le plan comme un jour « oui » (sortie longue s'il est le plus long, charge comptée), les autres il disparaît. Sorties allongées de la phase spécifique placées ces semaines-là. Plafond de charge semaine par semaine ; la montée (+ramp_pct %) suit la charge visée, pas le temps de la semaine. Sans fréquence, un jour optionnel reste un bonus hors du plan. Données de Greg (samedi 120 min, 1 sur 3) : 175 à 190 min les semaines sans weekend, 260 à 275 avec ; fitness autour de 20, 19,1 le jour J, frais (26 %) ; sortie allongée de 160 min en S27, la seule tombée un weekend libre de la phase spécifique.
- **Coach, mélange appris sur les hausses de fitness du coureur** (demande de Greg du 4 novembre 2026 : regarder les périodes où sa fitness a monté, hors courses et sorties exceptionnelles ; accord le même jour sur les trois propositions) : périodes de 8 semaines où la fitness, calculée sans les courses confirmées ni les sorties exceptionnelles (pics de charge, voir plus bas), gagne au moins 5 points, sans chevauchement, au moins 2 (sinon 80/20 par défaut). On en tire le nombre de sorties, le temps et la charge par semaine, et la part du temps (et des sorties) faciles (moins de 10 % en zone 3 et plus), soutenues (10 à 20 %) et en séance (20 % et plus). Le plafond de charge du temps disponible suit cette part avec les charges par heure actuelles du coureur (facile, soutenue, séance) ; les sorties soutenues (15 min faciles, bloc en zone 3, 5 min de retour au calme) prennent la place d'un footing dans la même proportion de sorties, réparties au fil des semaines ; les séances des semaines de charge sont prolongées d'un footing jusqu'au temps du jour (20 min au plus), car les séances des hausses sont comptées sortie entière. Données de Greg : 13 périodes (2021 à 2026), 2,9 sorties, 191 min et 161 de charge par semaine, 50,5 de charge par heure ; 49 % du temps facile, 12 % soutenu, 39 % en séance ; weekend 6 à 32 % des sorties, sorties longues de 0 à 7 par période (la fitness monte sans elles, elles servent la course) ; aujourd'hui 37 par heure en endurance (sentier et marche) contre 43 sur route avant Rome et Madrid. Plan de mai : semaines sans weekend de 130 à environ 145 de charge pour 190 à 200 min, fitness de 21 à 22,5, 21,0 le jour J, fraîcheur 21 %.
- **Coach, périodes particulières** (demande de Greg du 4 novembre 2026 ; une partie de l'étape 8, avancée) : dans Disponibilités et habitudes, périodes ajoutées ou supprimées : vacances, maladie, blessure, déplacement, semaine chargée, avec dates, séances prévues par semaine (une intention, pas une obligation) et durée maximale, facultatives. Pendant une période, ses jours remplacent les disponibilités : le nombre de séances par semaine, au prorata des jours de la période dans la semaine, placées d'abord sur les jours habituels et jamais deux jours de suite si possible, avec la durée saisie, sinon celle du jour, sinon la plus longue. Sans nombre : aucune séance pour une maladie ou une blessure, les séances habituelles sinon. Charge de la semaine bornée par ces séances ; semaine de reprise à −30 % après une maladie ou une blessure. Plan recalculé aussitôt. Reste de l'étape 8 (orientation, niveaux, effet sur les échéances, douleur) à faire.
- **Coach, bénéfice du plan revu** (remarques de Greg du 4 novembre 2026 : graphique démotivant, fitness « sans plan » meilleure qu'avec le plan ; « 29 semaines d'entraînement doivent avoir un intérêt » ; un séjour de 3 jours en montagne ne reflète pas une année ; un footing le lendemain d'une course n'est pas sérieux) : « sans plan » = charge moyenne d'une période passée aussi longue que le plan (12 semaines au moins, 52 au plus), sans les sorties exceptionnelles (pics de charge ramenés à la borne, voir plus bas ; courses gardées) : prolonger les 12 semaines d'un été en montagne sur un hiver surestimait la référence. Tableau « Prêt pour le jour J » : 8 dernières semaines pleines (sans l'exceptionnel), plan et besoin de la course : sortie la plus longue (90 % de la durée, 3 h au plus), D+ par semaine (médiane, besoin = D+ de la course), sorties d'au moins la moitié de la durée de la course sur les 8 semaines avant l'affûtage, séances par mois, semaines avec au moins autant de sorties que de jours « oui ». En tête : fraîcheur et fitness du jour J, face à sans plan. Lendemain d'une course B, ou C d'au moins une heure, au repos. Données de Greg : sans plan 88 par semaine sur 29 semaines, fitness 12,6 et fraîcheur nulle le jour J ; plan 21,2 (au plus haut 23,3), très frais (24 %) ; sortie la plus longue 136 → 160 min (besoin 161) ; D+ 300 → 840 m par semaine (besoin 1 440, non atteint avec les seuls jours de semaine) ; sorties de 90 min 1 → 4 ; semaines de 3 sorties 2 → 8 sur 8.
- **Coach, pics de charge** (remarques de Greg du 4 novembre 2026 : tout doit rester générique et valable dans le temps, sans correctifs pour l'instant T ; c'est l'accumulation de grosses sorties d'affilée qui est anormale, pas une sortie longue) : une semaine est un pic quand sa charge dépasse la borne haute de Tukey (Q3 + 1,5 × écart interquartile) des semaines courues des 52 semaines précédentes (au moins 8), règle standard des valeurs aberrantes, sans seuil à régler, qui suit l'évolution du coureur. Pour la fitness de référence (« sans plan », hausses passées), la charge d'un pic est ramenée à la borne ; ses sorties sont écartées des repères « aujourd'hui » et du mélange des hausses. Remplace les seuils par sortie (97e centile, 3 h) essayés le même jour. Données de Greg : un seul pic en 2026, la semaine du 5 octobre (561, trois sorties de 3 h 05 à 3 h 45 d'affilée, ramenée à environ 375) ; la sortie isolée de 4 h 30 du 27 septembre reste ordinaire. Sans plan : 118 par semaine, fitness 16,9 et fraîcheur nulle le jour J ; plan 21,1, très frais (28 %) ; 15 périodes de hausse.
- **Coach, sortie longue progressive et séances à la durée du coureur** (demandes de Greg du 4 novembre 2026 : « gérer la progressivité, respecter les standards » ; remplacer la séance prolongée de 20 min au plus, réglage ad hoc) : la plus longue sortie d'une semaine ne dépasse pas la plus longue des 4 semaines précédentes (réelles au départ, hors pics de charge, puis prévues) plus 10 % ou 10 min, le plus grand (repère courant) ; en semaine de charge, elle vise ce palier, le jour le permettant ; le palier compte la durée avant la fin soutenue. Sorties allongées : semaines de charge du développement et du spécifique (celles où un jour plus long est libre, sinon une sur deux depuis l'affûtage), visant 90 % de la durée de la course (3 h au plus), la progression faisant les paliers. Séance de qualité aussi longue que les séances du coureur (médiane de ses sorties de qualité sur 12 mois, dans le temps du jour ; aucune prolongation sans historique), la partie structurée complétée d'un footing. « Disponibilités limitantes » seulement quand la charge visée bute sur le temps de la semaine. Données de Greg (samedi 1 sur 2, vacances du 24 au 31 décembre sans séance) : sorties longues des weekends libres 90, 100, 110, 120, 130, puis 140 min en S26 (besoin 161, non atteint en respectant la progression) ; fitness 21,0 le jour J, très frais (28 %).
- **Coach, revue de la recherche** (demande de Greg du 4 novembre 2026 : « regarde les recherches scientifiques, résume, implémente ») :
  - Progression d'une séance : risque de blessure de surmenage accru dès qu'une sortie dépasse de plus de 10 % la plus longue des 30 derniers jours (Frandsen et al., BJSM 2025, 5 205 coureurs Garmin ; corrélation, critiquée sur l'attribution à la dernière sortie). **Appliqué** : sortie la plus longue au plus +10 % sur la plus longue des 4 semaines précédentes (durée, faute de distance prévue), sans le « +10 min » précédent. Plan de mai de Greg : sortie la plus longue 120 min (au lieu de 140), fitness 20,7 le jour J, très frais (25 %).
  - Progression hebdomadaire : plus de blessures au-delà de +30 % sur 2 semaines chez les débutants (Nielsen et al., JOSPT 2014) ; preuves faibles sur les variations de charge en général (revue de Damsted). **Déjà respecté** : +10 ou +15 % par semaine au choix du coureur.
  - Ratio charge aiguë / chronique (ACWR) : couplage mathématique et théorie contestée (Lolli ; Impellizzeri et al., Sports Medicine 2020). **Non utilisé**, à dessein.
  - Affûtage : environ 2 semaines, volume réduit de 41 à 60 % en décroissance, intensité et fréquence gardées (Bosquet et al., MSSE 2007 ; méta-analyse sur l'endurance de 2023 : jusqu'à 21 jours, mêmes règles). **Appliqué** : la fréquence est gardée, footings raccourcis jusqu'à 20 min plutôt qu'un jour supprimé ; volumes déjà à −40 puis −60 % ; une semaine sous 2 h de course reste le choix de Greg.
  - Répartition de l'intensité : polarisée ou pyramidale plus efficaces que le seuil ; polarisée surtout chez les plus compétitifs, pyramidale chez les coureurs de loisir (Rosenblat et al., Sports Medicine, méta-analyse en réseau ; Oliveira et al., Sports Medicine 2024). **Déjà couvert** : mélange appris sur les hausses du coureur (pour Greg, pyramidal).
  - Renforcement : 2 à 3 séances par semaine pendant 8 à 12 semaines améliorent l'économie de course (Balsalobre-Fernández et al., 2016, méta-analyse). **Appliqué** : consigne de renforcement chaque semaine (2 en foncier et en développement, 1 en spécifique et en semaine allégée, aucune en affûtage, en semaine de course, pendant une maladie ou une blessure), hors charge, avec de l'excentrique en préparation de trail.
  - Descente : l'effet de séances répétées (« repeated bout effect ») réduit les courbatures après une descente (Bontemps et al., EJSS 2024). **Déjà couvert** : séance de descente et sortie longue avec descentes en trail, progressives.
  - Monotonie et contrainte (Foster, MSSE 1998 : moyenne / écart-type des charges quotidiennes) : liées aux maladies au-delà de seuils individuels ; le seuil de 2 souvent cité n'est pas confirmé. **Noté pour l'étape 9** (indicateur de monotonie).
  - Entraînement guidé par la VFC : avantage faible ou non significatif sur la performance, moins de non-répondeurs (méta-analyses 2020 et 2021). **Noté pour la phase 4 bis** (journal de forme), sans priorité.
- **Coach, variété des séances** (remarque de Greg du 4 novembre 2026 : trop de séances identiques, surtout dans le fractionné) : la rotation des séances clés ne compte plus que les semaines de charge de la phase qui ont eu une séance (une semaine allégée, de course ou de récupération n'en fait plus sauter : les côtes longues du spécifique tombaient toujours sur une allégée) ; catalogue élargi, chaque phase faisant un tour complet avant toute répétition, le palier montant au tour suivant. Trail : foncier côtes courtes, fartlek, marche en côte, VMA, pyramide ; développement seuil, VMA en côte, VMA, montée continue, pyramide, tempo ; spécifique côtes longues, montée continue, descente, seuil, marche en côte, VMA en côte. Route : foncier fartlek, côtes courtes, VMA, pyramide ; développement seuil, VMA, tempo, pyramide, VMA en côte ; spécifique allure course, seuil, tempo, VMA. Nouvelle séance : pyramide de 1 à 4 min entre l'allure 5 km et le seuil, récupération de la moitié de l'effort. Plan de mai de Greg : 14 séances clés différentes, aucune répétée dans une phase avant le tour complet.
- **Coach, écran « Cette semaine »** (étape 3 de la phase 4, 4 novembre 2026 ; choix faits en autonomie, à valider par Greg) : la semaine affichée est celle du plan calculé le lundi (forme et estimation de la veille), pour qu'elle ne bouge pas au fil des sorties ; un changement de réglages ou de calendrier la recalcule. Rapprochement des sorties : couple le plus proche d'abord, coût = 1,5 par jour d'écart + 1 si le rôle diffère + |ln(durée faite / durée prévue)|, 2 jours d'écart au plus, une sortie par séance ; rôle d'une sortie lu sur le temps par zone de FC (seuils du plan : moins de 10 % en zone 3 et plus = facile, 20 % et plus = séance dure), sortie longue à partir de 80 % de la durée prévue, course si confirmée ; une sortie soutenue vaut pour un footing, une course pour une séance dure. Écarts notés sous 80 % ou au-delà de 125 % de la durée prévue. Ce qui peut sauter : au plus 2 séances, les optionnelles puis les footings du plus court au plus long (habitudes en dernier), jamais la séance clé, la sortie longue ni une course. Temps prévu des courses : l'estimateur sur la forme du jour, en attendant la fitness projetée (étape 5).
- **Trail et travail sur le plat** (question de Greg du même jour) : pour les trails courts, la VO2max (et la vitesse associée), le seuil ventilatoire et l'endurance musculaire prédisent la performance ; l'économie de course mesurée sur le plat la prédit mal ; les mesures en montée ajoutent parfois de l'information (Ehrström et al., MSSE 2018 ; études du groupe de G. Millet ; trail de 15 km et 750 m de D+, 2021). Le travail sur le plat garde donc sa place pour la VO2max et le seuil, la montée et la descente pour la spécificité. Plan de mai de Greg : environ 45 % des séances clés sur le plat (VMA, pyramide, seuil, fartlek, tempo), les autres en côte ; footings surtout vallonnés (alternance en foncier et en développement, tous en spécifique pour le D+, et l'habitude du lundi à la Bastille) ; sorties longues sur sentier.
- **Coach, plan ancré à sa semaine de départ** (4 novembre 2026, correction trouvée en préparant le bilan du dimanche) : le plan repartait chaque lundi de la semaine en cours, si bien qu'une semaine allégée ne tombait jamais sur la semaine en cours (règle « pas d'allégée avant 2 semaines de charge du plan »), que la séance clé de la semaine était toujours la première de la phase avec son premier palier, que les alternances (footing vallonné, lignes droites, fin soutenue) changeaient d'un lundi à l'autre et qu'un jour optionnel « une semaine sur 3 » glissait sans jamais arriver. Le plan part désormais de sa semaine de départ : le jour où la course principale a été ajoutée, ou le lendemain de la dernière course A passée si elle est plus récente. Les semaines passées comptent pour les phases, le cycle, la rotation et l'affûtage ; seules les semaines à venir sont construites et la charge suit toujours la forme réelle. Données de Greg : plan du jour identique (course ajoutée cette semaine) ; vu du 16 novembre, les 27 semaines gardent leur phase et leur type.
- **Coach, bilan du dimanche et réajustement** (étape 4 de la phase 4, 4 novembre 2026 ; trois choix de Greg le même jour : notification par ntfy, verdict sur les séances et la charge, semaine chargée à un tiers des séances en moins ; le reste en autonomie, à valider) :
  - Bilan affiché en tête de « Cette semaine » : le dimanche celui de la semaine en cours (provisoire tant qu'une séance reste à faire ou n'est pas synchronisée), du lundi au samedi celui de la semaine dernière (replié une fois répondu). Seulement pour les semaines où le plan existait (course principale ajoutée au plus tard le dimanche).
  - Verdict : le plus bas de la part des séances prévues faites et de la part de la charge prévue réalisée, chacune plafonnée à 100 % ; bien suivie dès 80 %, partiellement dès 50 %, peu en dessous ; sans séance prévue, dit tel quel. Lignes sans jugement : séances et charge, séance clé, séances non faites (pas de rattrapage), séances faites un autre jour, fitness réelle du dimanche soir face à celle que prévoyait le plan du lundi (comme prévu à moins d'un demi-point), temps prévu de chaque échéance au début et à la fin de la semaine. La compatibilité des remplacements viendra avec l'étape 10.
  - Deux questions (brief, « Suivi chaque semaine »), chacune facultative, enregistrée au clic et modifiable : semaine qui vient chargée, normale ou libre ; ressenti frais, normal ou fatigué. Sans réponse, la semaine suit le plan, la forme réelle comptant quand même.
  - Réajustement de la semaine suivante, expliqué dans la semaine et dans le plan : chargée, un tiers des séances en moins arrondi à l'inférieur, au moins 2 gardées, optionnelles retirées, puis footings du plus court au plus long (habitudes en dernier), puis une séance dure qui n'est pas la séance clé ; jamais la séance clé, la sortie longue ni une course. Libre : jours optionnels dans le plan (dans la limite du nombre maximal de séances), charge visée inchangée, la sortie longue pouvant s'allonger sur le jour libéré ; sans effet pendant une période particulière. Fatigue ressentie, ou forme du dimanche soir en zone de surcharge (sous −30 % de la fitness, seuil de la page Forme rapporté à la fitness) : une semaine de charge devient allégée (−30 %), la suivante repart du niveau d'avant (progression décalée). En avance (fitness réelle au-dessus de la prévue) : la charge ne dépasse pas celle que le plan du lundi précédent prévoyait pour cette semaine. Séances manquées : jamais rattrapées, le plan repart de la forme réelle. Pas de VFC dans les données : critère laissé de côté.
  - Bilan recalculé tant que la semaine n'est pas close, puis figé en base (table `coach_reviews`, avec les réponses) : le lundi une fois la synchro du jour faite, sinon le mardi. Le plan d'une semaine dépend du bilan de la précédente ; au-delà d'un niveau, seuls les bilans figés servent (pas de calcul en cascade).
  - Notification (choix de Greg : ntfy) : le dimanche à 19 h par défaut (réglable dans l'admin, désactivable), une fois par semaine, après une synchro Garmin qui rapporte les sorties du jour : « Bilan : semaine bien suivie », séances et charge, invitation à répondre, lien vers le bilan si l'adresse publique de l'application est réglée. L'adresse du sujet ntfy vaut mot de passe : elle est dans le `.env` (`NTFY_URL`, `NTFY_TOKEN` facultatif), jamais en base. Aucun nom Strava dans le message. Une notification en échec n'est pas relancée la même semaine (journalisée).
  - Données de Greg (simulation sans sorties après le 4 novembre) : semaine du 2 novembre, 1 séance faite sur 4 et charge 37 pour 176, peu suivie, provisoire le dimanche (la course B du jour pas encore synchronisée) ; fitness 19,0 pour 22,2 prévue. Réponse « fatigué » : semaine du 16 novembre allégée, charge 77 au lieu de 107 ; « chargée » : rien à retirer (2 séances) ; « libre » : la sortie longue passe du jeudi (80 min) au samedi (100 min).
- **Coach, « Cette semaine » allégé** (remarques de Greg du 4 novembre 2026 : écran trop chargé ; une course n'est pas une « séance clé » mais un jour important ; aperçu de la semaine suivante souhaité) : seules les courses dont la date tombe dans la semaine affichée sont mises en avant, en encadré « Course A/B/C » (date, compte à rebours, temps prévu, objectif) ; une course n'est plus jamais étiquetée « séance clé » (pastille « jour de course », jour encadré ; dans le bilan « Course B : … : courue / encore à courir ») ; carte « La semaine prochaine » sous la semaine : type et phase, minutes, charge, D+, courses, réajustement et séances jour par jour, détail dans le Plan. Le dimanche, l'aperçu est la semaine telle que lundi l'affichera (réponses du bilan comprises), sinon celle du plan du lundi.
- **Coach, fraîcheur le jour de la course** (demande de Greg du 4 novembre 2026) : pour une course du jour, l'encadré donne la fraîcheur du matin, forme de la page Forme (fitness − fatigue de la veille), en points et en % de la fitness, avec la zone du jour J du plan (mêmes seuils que la page Forme, rapportés à la fitness ; au-delà de 25 % « très frais, bien reposé »). Données de Greg (dimanche 8 novembre simulé, sans sorties après le 4) : +10,2, soit +53 %, très frais.
- **Coach, temps prévu le jour J et objectif réajusté** (étape 5 de la phase 4, 4 novembre 2026 ; choix faits en autonomie, à valider par Greg) : remplace « la forme actuelle maintenue » de la phase 3.
  - Temps prévu = temps réaliste de l'estimateur (route ou GPX, correction de l'admin comprise) avec la forme du dimanche soir, multiplié par exp(pente × (fitness du jour J − fitness du dimanche)), la pente étant la relation personnelle entre fitness et niveau de l'étape 8 de la phase 3 (−0,81 % par point pour Greg, bornée de −2 % à 0, −0,5 % faute d'historique). Fourchette déplacée du même facteur.
  - Fitness du jour J : la plus haute des 14 jours avant la course dans la simulation jour par jour du plan calculé le lundi. Le matin même, l'affûtage a fait baisser la fitness d'un ou deux points, mais il garde le niveau construit et retire la fatigue (Bosquet 2007) : prendre la fitness du matin pénalisait l'affûtage (Trail des petites roches : 1:39:54 au lieu de 1:38:58 avec la forme du moment). La fraîcheur n'est toujours pas convertie en temps. Course au-delà de la course principale : forme du moment maintenue.
  - Enregistré chaque lundi après la synchro (planificateur, avec les courses suivies) et à l'ouverture du coach s'il manque ; la semaine en cours seulement une fois la semaine d'avant close (sorties du dimanche arrivées). À l'ajout d'une course, les semaines depuis son ajout sont rejouées (12 au plus) ; parcours ou date changés : temps prévus effacés et rejoués.
  - Affichage : temps prévu dans Cette semaine (course de la semaine), en tête du Plan et dans les Échéances (fourchette, fitness du dimanche et du jour J, temps avec la forme du moment) ; courbe par échéance semaine après semaine (fourchette, temps avec la forme du moment en pointillé, objectif), à partir de 2 semaines.
  - Objectif réajusté quand l'écart dure (brief : « par exemple trois semaines consécutives ») : les 3 derniers temps prévus, semaines consécutives, tous à plus de 3 % de l'objectif dans le même sens. Une phrase, la dernière course passée depuis moins de 4 semaines citée comme cause possible, et deux boutons : prendre le dernier temps prévu comme objectif, ou garder le sien (pas de nouvelle proposition avant 3 nouvelles semaines d'écart : le coach le dit une fois, sans insister). Remplace le signal immédiat à 3 % de l'étape 6.
  - Données de Greg (semaine du 2 novembre) : Trail des petites roches 1:38:42 (fitness 21,6 → 21,9 ; 1:38:58 avec la forme du moment) ; Raidlight 2:57:07 (21,6 → 23,1 avant l'affûtage ; 2:59:20 avec la forme du moment).
- **Coach, maintien de forme sans course prévue** (étape 7 de la phase 4, 4 novembre 2026 ; repères généraux choisis en autonomie, à valider par Greg) : sans course à venir, le coach construit 8 semaines (deux cycles) depuis la semaine en cours (coach_plan.build_maintenance) ; « Cette semaine », le bilan du dimanche et sa notification marchent comme avec un plan.
  - Plage de fitness : médiane de la fitness des 12 dernières semaines ± 10 %, pics de charge ramenés à la borne de Tukey (un séjour exceptionnel ne la déplace pas), courses gardées ; au moins 6 semaines courues sur les 12, sinon pas de plage (la fitness du moment est entretenue). Elle suit le coureur : s'il en fait plus, elle remonte doucement.
  - Cycle 3 semaines normales et 1 allégée (−30 %), compté depuis le lendemain de la dernière course du calendrier (sinon depuis un lundi de référence fixe). Semaine normale : charge qui ramène au niveau d'avant la dernière allégée, au centre de la plage au moins ; au-dessus de la plage, la charge qui entretient le haut de la plage (pas de semaine creuse pour faire redescendre un coureur en forme) ; montée de charge au plus +10 % (ou +15 %, réglage du coureur), fitness au plus +5 par semaine.
  - Semaine type : une seule séance de qualité, qui tourne (route : seuil, fartlek, VMA, côtes courtes, tempo, pyramide ; trail : côtes courtes, seuil, côtes moyennes, fartlek, montée continue, VMA) ; sortie longue à la durée habituelle (médiane des plus longues sorties de chaque semaine courue des 12 dernières semaines, hors pics et courses), sans progression au-delà ; le reste en endurance, sorties soutenues et lignes droites comme dans le plan ; un renforcement par semaine.
  - Reprise : fitness sous le bas de la plage 14 jours de suite (« durablement ») ; semaines « reprise » jusqu'au bas de la plage, intensité légère (fartlek, sprints en côte), même montée plafonnée. Creux de saison : si l'an dernier, à 2 semaines près, la fitness était aussi durablement sous sa plage, le coach le dit (« une période calme qui revient, rien d'anormal »).
  - Après la dernière course : récupération d'abord (mêmes règles que l'étape 6 : jours faciles selon les km-effort, lendemain au repos, charge réduite), mode « Récupération » affiché, puis maintien. Bascules automatiques : sans course à venir, maintien ; dès qu'une course est ajoutée, le plan de préparation part de la forme du moment.
  - Test facultatif : une semaine normale sur 8 (la 2e d'un cycle sur deux), la séance clé devient un test (route : 5 km à fond ; trail : une montée connue de 15 à 25 min), la séance habituelle proposée en remplacement ; le résultat entre seul dans les meilleurs efforts.
  - Orientation route ou trail : trail si au moins la moitié des sorties des 12 dernières semaines sont en trail (choix du coureur à l'étape 8).
  - « Envie de courir une course » (vue Plan) : 5 km, 10 km, semi, marathon avec le temps de l'estimateur du jour (en trail, D+ au D+ par km habituel des sorties trail) ; cohérente avec la forme, sans préparation, quand la plus longue sortie ordinaire des 8 dernières semaines atteint les deux tiers de sa durée (repère courant ; d'abord 90 % plafonnés à 3 h comme la sortie longue du plan, trop permissif : un marathon trail de 5 h 22 ressortait pour Greg) ; la plus longue cohérente est suggérée.
  - Données de Greg (calendrier ignoré, 4 novembre 2026) : plage 16,0 à 19,6 (centre 17,8), fitness du jour 21,4 (séjour en montagne compris), au-dessus de la plage ; 8 semaines entre 165 et 180 min par semaine de charge, fitness 19,8 puis environ 18, limitée par les disponibilités (260 min par semaine).
- **Coach, orientation et semaines particulières** (étape 8 de la phase 4, 4 novembre 2026 ; repères choisis en autonomie, à valider par Greg) : complète les périodes particulières déjà faites.
  - Orientation sans course, au choix dans Disponibilités et habitudes (Ton plan) : maintien (par défaut), reprise (intensité légère et montée jusqu'au centre de la plage), foncier (séances du foncier, haut de la plage visé, sortie longue jusqu'à 1,25 fois l'habituelle), vitesse pour le 10 km et moins (route ; VMA, seuil, pyramide, fartlek, tempo ; deux séances de qualité possibles), route longue pour le semi et le marathon (route ; seuil et tempo, sortie longue progressive jusqu'à 1,5 fois l'habituelle, 3 h au plus, haut de la plage visé), trail (côtes, montée continue, marche rapide, descente, seuil ; sorties vallonnées, avec descentes ou spécifiques, jusqu'à 1,25 fois l'habituelle, haut de la plage visé). Le test facultatif suit l'orientation.
  - Avec une course A, l'orientation découle de la course ; nuance au choix : plus de côtes ou plus de vitesse (une semaine de charge sur deux, la séance clé devient une séance de côtes ou de vitesse adaptée à la phase), plus d'endurance (une seule séance de qualité par semaine). Le coach le signale une fois quand la nuance éloigne de la course : côtes pour une course plate, vitesse pour une course de plus de 2 h, endurance pour une course de moins de 45 min.
  - Semaines particulières : types vacances, Noël, déplacement, semaine chargée, maladie, blessure, douleur ; trois niveaux, au choix sinon selon le type : pas de course à pied (maladie, blessure), minimum, 2 footings par semaine au prorata des jours (vacances, Noël, déplacement), normal allégé, jours habituels et charge −30 % sur les jours de la période (semaine chargée, douleur). Un nombre de séances saisi prime sur le niveau.
  - Le plan anticipe : pas de séance dure la veille d'une période sans course ou minimale (ni d'une maladie, blessure ou douleur) ; semaine de reprise allégée (−30 %) après une période sans course ou minimale d'au moins une semaine, et après une maladie, une blessure ou une douleur.
  - Progression suspendue pendant une maladie, une blessure ou une douleur : séances faciles seulement, charge jamais au-dessus de celle d'avant, progression reprise ensuite au même niveau ; invitation à consulter pour une blessure ou une douleur qui dure ou augmente.
  - Effet sur les échéances, sous chaque période à venir : le plan recalculé sans elle, écart de fitness le jour J de la course principale et de temps prévu (relation personnelle fitness / niveau de la phase 3) ; sans course, écart de fitness au bout des 8 semaines du maintien. Données de Greg : Noël en minimum (23 décembre au 1er janvier) −0,1 de fitness, +9 s sur le Raidlight ; 12 jours sans courir trois semaines avant (20 avril au 1er mai) −6,1, +9 min 52 s.
  - Détection des pics de charge rendue linéaire et mémorisée pour les mêmes sorties : la page Coach calcule plusieurs plans (7,4 s ramenées à 0,5 s pour les effets des périodes).
- **Coach, choix et variété des séances** (étape 9 de la phase 4, 4 novembre 2026 ; disponibilités, habitudes et rôle de l'habitude selon la phase faits aux étapes 1 et 2 ; le reste en autonomie, à valider par Greg) :
  - Deux propositions par séance, au même rôle : séance de qualité, la variante suivante du catalogue de la semaine sur l'autre terrain si possible (côtes contre plat), même durée de séance que celles du coureur ; sortie longue, une autre variante de la phase (progressive, classique, vallonnée, avec descentes) ; footing, vallonné au lieu du plat ou l'inverse, même durée. Pas de seconde proposition pour une habitude, une course ni le rappel d'affûtage. Dans « Cette semaine », chaque séance à venir montre l'autre proposition (détail dépliable) et un bouton pour la choisir ; le choix est enregistré par jour (table `coach_choices`, base en version 19) avec le libellé de la proposition du coach, et ne vaut que tant que la séance prévue ce jour reste la même ; charge, minutes et D+ de la semaine recalculés, le bilan et la détection des séances suivent le choix ; retour possible à la proposition du coach.
  - Bibliothèque de séances (sous-onglet « Séances ») : toutes les séances du coach par famille (endurance, sorties longues, fartlek et pyramide, seuil et tempo, VMA, côtes, trail, allure course et tests), au premier palier et au plus haut, avec les allures, la FC et la vitesse de montée du coureur.
  - Parcours habituels variés : parcours (regroupement des parcours similaires de la phase 2) courus au moins 3 fois sur 52 semaines ; pour chaque footing et sortie longue à venir hors habitude, un parcours de durée habituelle à ±20 % de la séance, plat ou vallonné comme elle (D+ par km du seuil plat des statistiques), le moins récemment couru d'abord, en tenant compte des propositions des semaines précédentes du plan.
  - Indicateur de monotonie (Foster 1998, charge moyenne des 7 jours divisée par son écart-type, repos compris) de la semaine dernière et de la semaine prévue, face aux semaines courues de l'année du coureur ; alerte au-delà de sa borne haute de Tukey (seuil de 2 non confirmé par la recherche, section « revue de la recherche »), avec un conseil (alterner facile et dur, un vrai jour de repos, choisir l'autre proposition).
- **Coach, fiche d'une échéance** (demande de Greg du 4 novembre 2026, faite le même jour) : le nom de chaque course du coach (Cette semaine, Plan, Échéances) mène à sa fiche : temps prévu le jour J (sinon estimé aujourd'hui) et fourchette, objectif, lien vers l'estimateur complet (GPX ou distance et D+ pré-remplis) ; temps de passage km par km (temps du km, allure, passage, D+ et D− du km sur un GPX, ravitos signalés) pour le temps choisi : prévu par défaut, objectif, optimiste, prudent ou un temps saisi à la main ; sur un GPX, les passages suivent le profil des temps de l'estimateur trail (pente, fatigue, arrêts) mis à l'échelle du temps choisi ; sur route, une allure régulière.
- **Coach, retours de Greg sur le plan** (liste du 5 novembre 2026, avant l'étape 10 ; choix de Greg sur 4 questions, le reste d'après la littérature de planification) :
  - Sorties optionnelles toujours proposées et marquées comme telles (un footing, ou la sortie longue simple en bonus sur le jour optionnel le plus long), jamais une séance ; un jour optionnel « une semaine sur n » entre dans le plan une semaine sur n, sauf si une sortie optionnelle de ce jour a été faite dans les n − 1 semaines d'avant : elle reste alors optionnelle (règle de Greg). Les sorties optionnelles faites sont notées dans le bilan de chaque semaine.
  - Séance faite un autre jour : reconnue à 1 jour près au plus, pour toutes les séances, dans la semaine (choix de Greg ; c'était 2 jours).
  - FC d'endurance : 60 à 70 % de la FC de réserve (Karvonen, par défaut) ou 65 à 75 % de la FC max, au choix dans l'admin (choix de Greg) ; pour Greg, 134 à 148 au lieu de « sous 160 » (90 % de la LTHR, haut de la zone 2 de Friel). Sans FC max, la zone 1 de Friel. Allure soutenue : de la fin de l'endurance à 92 % de la LTHR ; tempo 90 à 95 %, seuil 95 à 100 %.
  - Cibles structurées à chaque étape (FC, allure, % de la VMA, % de la FC max, effort sur 10, sensation facile, moyen, dur, très dur), texte toujours dans le même ordre (allure, FC, effort) ; l'affichage au choix de l'unité reste pour l'étape 10. Zones de FC affichées avec leurs FC et leur % de la FC max (pages Forme et Sortie, info-bulle des cibles du coach).
  - VMA : allure selon la longueur de la fraction (30/30 et 200 m à 105 % de la VMA, 400 m à 102 %, 600 m à 100 %, 800 m à 98 %, 1 000 m à 95 %, repères courants des plans français), et VMA testée saisie dans l'admin, prioritaire sur l'estimation (choix de Greg).
  - Toute séance finit par au moins 10 min de retour au calme (demande de Greg) ; une séance allongée au temps habituel du coureur l'est d'un tiers à l'échauffement et de deux tiers au retour au calme (au lieu d'un « puis 20 min de footing » après le retour au calme). Footing et lignes droites, sortie soutenue, sorties longues progressives ou à fin soutenue : 10 min au calme à la fin.
  - Sortie longue vallonnée avec bloc soutenu : le bloc au milieu (sur une portion roulante ou en montée douce), puis le retour en endurance, descentes relâchées (remarque de Greg : il faut redescendre). Sur le plat, le bloc reste en fin de sortie, avant le retour au calme.
  - Plus de sorties longues sur le plat avec variations d'allure (blocs de 6 min soutenus, ou à allure semi ou marathon pour ces courses), dans la rotation du foncier et du développement, aussi en trail. Alternative de chaque sortie longue vallonnée : la même charge estimée sur le plat (neige, boue).
  - Charge estimée de chaque séance prévue et de son alternative (HRSS), affichée face à celle de la sortie faite quand elle est liée.
  - Renforcement : 15 à 20 min, aux jours suggérés : un jour de footing (le plus court d'abord), puis un jour de séance dure ou son lendemain, jamais la veille d'une séance dure, d'une sortie longue ou d'une course, jamais deux jours de suite (choix de Greg).
  - Littérature de planification (entonnoir de Canova, du général au spécifique ; Daniels, Pfitzinger ; plans français) : foncier = endurance, force et vitesse légère (côtes courtes, sprints en côte, fartlek, 30/30) ; développement = seuil et VMA, dosés selon la course (plus de VMA pour 5 et 10 km, plus de seuil et de tempo pour semi et marathon) ; spécifique = l'allure de la course en blocs qui s'allongent une semaine sur deux (5 km : 8 × 600 m à 3 × 1 600 m ; 10 km : 5 × 1 km à 3 × 3 km ; semi : 3 × 2 km à 3 × 5 km ; marathon : 3 × 3 km à 3 × 6 km), entre des séances de soutien ; le temps du jour limite le palier. Trail : spécifique en montée, à l'effort ; fatigue neuromusculaire des descentes (jusqu'à 48 h et plus, effet protecteur des répétitions) : descentes introduites progressivement, plus de descente travaillée ni de sortie longue avec descentes dans les 3 semaines avant la course.
  - Écran Cette semaine : le programme du jour en tête, avec une phrase sur son rôle (le repos aussi) ; l'autre proposition d'une séance se choisit aussi dans le Plan, tant qu'elle n'est pas passée, avec le même détail que la première. Plan « en un coup d'œil » repliable, l'état gardé dans le navigateur. Texte de démarrage en info-bulle ; nom du GPX retiré sous les courses du plan.
