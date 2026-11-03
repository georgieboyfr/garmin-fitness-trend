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

