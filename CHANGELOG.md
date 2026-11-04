# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnement sémantique.

## [Non publié]

## [0.4.0] - 2026-11-04

Compléments de l'estimateur et de la page Forme, après comparaison avec la thèse de L. Lerebourg sur la prédiction de la performance (2021). Au premier démarrage, les sorties sont recalculées (métriques en version 6 : nouvelle VAP).

### Ajouté
- Page Forme : VMA (meilleur effort route de 5 min), VO2max estimée (3,5 × VMA), FC au seuil (meilleure heure sur 12 mois, en % de la FC max) et allure au seuil (une heure d'après le niveau de l'estimateur).
- Indice de confiance de chaque estimation (route et GPX) : élevée, moyenne ou faible, avec ses raisons (extrapolation de distance, ancienneté et ajustement de la référence, précision mesurée sur les courses du terrain, durée au-delà de la plus longue sortie, pentes couvertes par le modèle allure-pente, exposant de fatigue par défaut).
- Précision de l'estimateur (page Estimateur) : limites à 95 % de Bland-Altman (biais ± 1,96 écart-type) et écart-type des écarts, pour la route, le trail et la vraie précision des courses suivies ; indicatives sous 10 courses.

### Modifié
- VAP selon la courbe de la GAP de Strava (calée sur la FC) au lieu de la formule de Minetti : en descente raide, l'effort remonte au lieu de baisser (facteur 0,88 à −9 %, 1,08 à −20 %, 1,50 à −30 %), la VAP des fortes descentes n'est plus plus lente que l'allure réelle. Métriques en version 6 (toutes les sorties sont recalculées : VAP, temps au km, forme du jour). Le modèle allure-pente de la page Estimateur est comparé à cette courbe ; l'équivalent plat du D+ de l'estimateur route reste celui de Minetti.

## [0.3.0] - 2026-11-03

Phase 3 (estimateur) : temps de course estimé sur route et sur un GPX de trail à partir de la forme actuelle, courses suivies semaine après semaine, précision mesurée sur les courses passées. Au premier démarrage, la base passe en version 15 (courses suivies) ; les sorties sont recalculées (métriques en version 5).

### Ajouté
- Métriques en version 5 (toutes les sorties sont recalculées) : temps en mouvement et distance par tranche de pente de 2 %.
- Page Estimateur (nouvel onglet) : forme actuelle sur les 12 dernières semaines (courbe allure-durée route et trail, VAM par palier, allure en descente par bande de pente, fitness et forme, Efficiency Factor comparé aux 12 mois précédents), calculée par une fonction pure versionnée rejouable à n'importe quelle date.
- Estimateur route : formule de Riegel à exposant personnel (calé sur la frontière des meilleurs efforts route des 2 dernières années), niveau tiré des meilleurs efforts route des 12 dernières semaines, fourchette optimiste / réaliste / prudent et allure cible ; saisie d'une distance et d'un D+ facultatif, tableau 5 km, 10 km, semi, marathon.
- Précision de l'estimateur route : rejeu sur chaque course route confirmée avec la forme de la veille, erreur moyenne, biais, part des résultats dans la fourchette, comparaison avec l'exposant personnel.
- Modèle allure-pente personnel (page Estimateur) : facteur de temps selon la pente, de −45 à +45 %, calé sur les sorties des 12 derniers mois (vitesse sur chaque pente rapportée à celle du plat de la même sortie), comparé à la formule de Minetti ; graphique et tableau avec l'allure et la vitesse verticale correspondantes.
- Page Estimateur : période de la forme actuelle (6, 8, 10 ou 12 semaines, aussi utilisée par l'estimateur route et sa validation) et période du modèle allure-pente (6 mois, 12 mois, 2 ans ou tout l'historique) réglables, choix mémorisés dans un cookie.
- Estimateur trail sur GPX (page Estimateur) : import d'un GPX (gardé dans `data/gpx`, derniers parcours rappelés), distance équivalente plat selon le modèle allure-pente personnel, temps total (Riegel jusqu'à 2 h, puis exposant de fatigue calé sur la courbe allure-durée longue), fourchette, profil avec les temps de passage, tronçons homogènes par pente (plat, douce, moyenne, forte, vallonné : découpage optimal du profil en pentes régulières) avec D+ et D−, temps, allure et passage. Altitude du MNT (IGN, Copernicus hors de France) interrogé une fois par parcours et mis en cache, celle du GPX à défaut ; D+ et D− filtrés avec les réglages de l'admin (le D+ brut d'un GPX bruité était surestimé de 10 %).
- Ravitaillements sur le parcours d'un GPX (page Estimateur) : proposés d'après les points nommés du GPX, modifiables et enregistrés avec le parcours (km, nom, durée d'arrêt) ; passage estimé à chaque ravito avec sa fourchette, temps, D+ et D− depuis le point précédent, arrêt et départ ; arrêts ajoutés au temps final ; repères sur le profil.
- Estimation trail en temps total : arrêts saisis aux ravitos, sinon part d'arrêt calée sur tes courses trail passées (croît avec le carré de la durée), répartie dans les temps de passage.
- Précision de l'estimateur trail : rejeu sur chaque course trail confirmée, sa propre trace servant de GPX, avec la forme de la veille ; erreur moyenne et biais face au temps total, part des résultats dans la fourchette, arrêts réels et estimés, écart en mouvement pour diagnostic.
- Sous chaque estimation (route et GPX) : tes 3 courses confirmées les plus proches en distance et en D+ (temps réel, fitness du jour), et l'effet de la forme (temps estimé avec 5 ou 10 points de fitness de plus ou de moins le jour J, d'après la relation entre ton niveau et ta fitness sur ton historique).
- Courses suivies, indépendantes du coach (page Estimateur et une page par course) : parcours GPX ou distance avec D+, date et objectif facultatifs ; prédiction enregistrée chaque lundi par le planificateur (forme du dimanche soir), 12 semaines rejouées à l'ajout ; vue d'ensemble avec l'évolution sur 4 semaines ; graphique par course avec la fourchette et l'objectif. Migration `0014_tracked_races`.
- Après la course : course suivie reliée automatiquement à sa sortie (ou à la main), résultat face à la dernière prédiction (écart, fourchette, objectif), point du résultat sur le graphique. Migration `0015_tracked_link_manual`.
- Calibration de l'estimateur (admin) : correction proposée par terrain d'après le rejeu des courses confirmées, appliquée sur demande et figée, signalée sur les estimations.
- Fiche d'une course réalisée : estimation rejouée sur sa trace avec la forme de la veille et celle d'aujourd'hui, face au temps réel, et courbe de l'écart cumulé le long du parcours sur le profil d'altitude, ou au choix temps de passage réels et estimés.
- Précision de l'estimateur : erreur sur les courses ayant servi au réglage (flatteuse) séparée de la vraie précision (prédictions enregistrées avant le départ des courses suivies, rejeu des courses suivantes).

### Modifié
- Estimateur : chaque référence route est ramenée à ton aérobie du jour d'après l'évolution de ta vitesse à FC égale (85 % de la LTHR, droite FC / vitesse sur 12 mois), et cherchée sur 4 mois au lieu de 12 semaines ; référence affichée avec son ajustement. Semaines rejouées des courses suivies recalculées quand l'estimateur change. Valeurs par défaut génériques (part d'arrêt, effet de la forme).
- Page Estimateur : biais affiché « sans biais » au lieu de « −0,0 % ».
- Estimateur route : exposant standard de Riegel (1,06) au lieu de l'exposant personnel, qui se trompait davantage sur les courses passées (8,4 % d'erreur moyenne contre 4,4 %) ; l'exposant personnel reste affiché pour comparaison.

### Corrigé
- Menu des pages responsive : sur petit écran, un bouton ouvre la liste des pages (elle défilait hors de l'écran) ; blocs dépliés de la page Performance et formulaires des courses suivies tenus dans la largeur du téléphone.
- En développement, scripts et styles rechargés à chaque démarrage (le navigateur gardait d'anciennes versions).

## [0.2.0] - 2026-11-03

Phase 2 (statistiques) : pages Accueil, Volume et régularité, Sorties, Performance, Forme et Courses, fiche de chaque sortie, détection des courses. Au premier démarrage, toutes les sorties sont recalculées (métriques en version 4).

### Ajouté
- Pages de statistiques (templates Jinja, ECharts embarqué, thèmes clair/sombre/automatique, menu compact sur mobile, info-bulles), protégées par la session de l'admin : page d'accueil avec le cumul de l'année face à l'an dernier à la même date (distance, D+, km-effort, sorties), la courbe de distance cumulée, la dernière sortie et les totaux.
- Métriques de chaque sortie, recalculées si la version de l'algorithme ou les paramètres du `.env` changent : temps en mouvement, TRIMP et HRSS, temps par zone de FC (Friel, sur la LTHR), meilleures FC moyennes sur 20, 30 et 60 min, terrain (route, trail au-delà de 20 m de D+ par km, indoor).
- Admin : carte « Physiologie » avec la LTHR estimée (meilleure FC moyenne tenue une heure sur 12 mois) à côté de la valeur réglée, et la FC max observée.
- Page Volume et régularité : filtre route / trail, semaines actives, série en cours et plus longue série de semaines consécutives, D+ par km ; cumul jour par jour de toutes les années (distance, D+ ou km-effort) ; totaux, km-effort et D+ par km par année ; distance ou D+ par mois ; calendrier en heatmap par année.
- Page Sorties : liste paginée (25 par page) avec nom, description Strava, terrain, distance, D+, temps en mouvement, allure, FC moyenne et charge ; recherche dans le nom et la description, filtres par année et terrain, tri par colonne ; une carte par sortie sur mobile.
- Page Performance : records en fenêtre glissante sur 1, 3, 5, 10 km, semi et marathon (route et trail séparés, top 10, filtre par année, pics GPS filtrés), meilleur temps par année, courbe allure-durée par année (1 min à 2 h), VAM sur les montées de plus de 200 m (meilleure par année, top 10).
- Admin : LTHR, FC max et FC repos modifiables (bouton « Utiliser l'estimation », retour aux valeurs du `.env`), avec recalcul automatique des sorties.
- Page Forme : fitness, fatigue et forme (Banister, sur la charge HRSS) avec la zone de forme et la montée sur 7 jours, pic de fitness par année, temps par zone de FC par année (repère 80/20), Efficiency Factor des sorties faciles et plates (médiane mensuelle), découplage cardiaque des sorties de plus d'une heure sur le plat (repère 5 %).
- Parcours similaires : les sorties qui suivent le même tracé (même départ, distance à ±5 %, écart de forme sous 40 m, même sens) sont regroupées ; dans la liste des sorties, écart (temps en mouvement) à la moyenne des autres passages et rang.
- Fiche de chaque sortie (`/sorties/<id>`), accessible depuis toutes les pages : résumé (temps en mouvement et écoulé, allure, FC, charge, EF, découplage), tracé sur fond Plan IGN, photos aériennes ou OpenStreetMap, profils d'altitude, d'allure et de FC synchronisés avec la carte, temps par kilomètre, zones de FC, meilleurs efforts, passages sur le même parcours.
- Liste des sorties : temps écoulé en plus du temps en mouvement.
- Page Forme : repères historiques pour situer fitness, fatigue et forme (jauge entre le minimum et le maximum de l'historique, plage habituelle des 12 derniers mois, rang, valeur il y a un an, record) ; droites de tendance de l'Efficiency Factor (12 derniers mois et depuis le début, en % par an).
- Détection des courses : score combinant nom ou description (mots-clés modifiables), effort cardiaque pour la durée, charge par heure, distance ronde, allure inhabituelle, top 3 sur un segment, départ loin de chez soi, week-end en matinée, absence d'arrêts ; courses probables à confirmer ou rejeter dans l'admin, ou depuis la fiche d'une sortie.
- Page Courses : courses confirmées avec la forme le jour J et une semaine avant, l'allure comparée aux sorties habituelles, et un graphique forme / performance.
- Records et tops 10 : aperçu de la description.
- Accueil : écart avec l'an dernier seulement s'il est notable, projection de fin d'année, record annuel, sorties par semaine.
- Fiche de sortie : intervalles de la séance (tours de la montre si séance structurée ou tours manuels, sinon blocs d'effort détectés sur l'allure, route seulement), résumé « N × durée à allure », efforts surlignés sur le profil d'allure.
- Fiche de sortie : classement de chaque meilleur effort dans l'année et sur toute la période (même terrain ; VAM route et trail confondus).
- Liste des sorties : curseurs de distance et de D+ (minimum et maximum, bornés par l'historique), nombre de sorties par page au choix (25, 50, 100 ou 200, 50 par défaut, mémorisé), position (« 51–100 sur 659 ») et navigation en haut et en bas de la liste, ligne entière cliquable, jour de la semaine dans la date.
- Fiche de sortie : bloc « Efficiency Factor » et « Découplage cardiaque » expliqués (unité, médiane de l'EF des 12 mois précédents sur le même terrain, lecture du découplage, conditions de calcul) ; zoom de la carte avec Ctrl + molette ou au pincement du pavé tactile ; charge par heure.
- Page Performance : FC moyenne de chaque record (et de chaque montée) ; top 10 dépliés présentés en tableau (rang, temps, allure, FC, date, sortie et description) ; meilleurs temps par année cliquables (ouvrent la sortie) et années cliquables (tops 10 de l'année) ; meilleures montées par palier de 100, 200, 500 et 1 000 m de D+ (top 10), aussi classées sur la fiche de sortie. Métriques en version 4 : recalcul automatique de toutes les sorties.
- Page Forme : jauges et chiffres colorés selon l'état (vert favorable, jaune à surveiller, rouge défavorable), zones colorées sur la jauge de forme, position par rapport à la plage habituelle ; périmètre du découplage indiqué (route plate, au moins une heure).
- Page Courses : info-bulle sur « Vs habituel » et allure habituelle au survol.
- Cumuls jour par jour (Accueil, Volume) : repère « aujourd'hui » et bouton qui affiche toutes les années à la date du jour.
- VAP (allure ajustée à la pente, formule de Minetti) des sorties trail, sur la fiche, dans la liste des sorties et dans le tableau par kilomètre.
- Fiche de sortie : « Forme du jour », la FC de la sortie face à celle attendue à sa vitesse ajustée à la pente, d'après les minutes stables des 90 jours précédents (fractionné et dénivelé pris en compte).

### Modifié
- Liste des sorties : colonne « vs parcours » retirée (l'écart au parcours reste sur la fiche de la sortie) ; temps en mouvement et temps écoulé réunis dans une colonne « Temps » (l'écoulé n'apparaît que s'il diffère d'au moins une minute) ; FC et charge en retrait, description sur une ligne.
- Fiche de sortie : bloc « Ce parcours » déplacé en bas de la fiche ; dernier kilomètre incomplet affiché par sa seule distance (« 682 m »).
- Hors de France, le D+ de Strava remplace celui du MNT Copernicus (qui compte les bâtiments) quand l'activité est appariée.
- Le terrain d'une sortie est recalculé quand son D+ change.
- Le cookie de session couvre tout le site (et plus seulement `/admin`) ; après connexion, retour à la page demandée.

### Corrigé
- Fiche de sortie : le découplage n'est plus affiché sur les sorties vallonnées ou trail (comme sur la page Forme), et il est signalé comme non pertinent sur une séance fractionnée.
- Carte : icône du choix des fonds de carte, absente faute des images de Leaflet.
- VAM : le temps des montées était lu sur la distance nettoyée des pics GPS alors que le profil d'altitude suit la distance brute ; après un pic, des VAM invraisemblables apparaissaient (plus de 9 000 m/h). Les sauts d'altitude de plus de 1 m/s sont aussi ignorés.

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
