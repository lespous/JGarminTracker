# Journal des versions

Numérotation `MAJEUR.MINEUR.CORRECTIF` : une nouvelle fonctionnalité augmente le chiffre du milieu,
une simple correction le dernier. Le numéro vit dans `jgarmintracker/__init__.py` ; chaque version a son tag Git (`v0.1.0`).

## 0.19.3 — 2026-10-04

### Corrigé
- Lecture d'une sortie : la vitesse choisie n'était pas respectée quand Windows demande de réduire les animations
  (lecture forcée à ×300 au moins : 1h15 rejouée en ~15 s même en ×2). Une pause suivie d'une lecture très rapide
  pouvait aussi lancer une deuxième animation et doubler la vitesse.

## 0.19.2 — 2026-10-04

### Modifié
- Lecture d'une sortie (carte 2D et survol 3D) : vitesses ×2 et ×10 en plus de ×30, ×100, ×300 et ×1000.

## 0.19.1 — 2026-10-03

### Corrigé
- Lecture d'une sortie (carte 2D et survol 3D) : le bouton pause ne réagissait pas pendant la lecture. Son icône
  était réécrite à chaque image ; l'élément cliqué disparaissait entre l'appui et le relâchement. L'icône ne
  change plus que lorsque l'état change, et ne capte plus les clics.

## 0.19.0 — 2026-10-03

### Ajouté
- **Survol 3D** d'une sortie (bouton « Survol 3D » sur la fiche d'une sortie et d'un parcours) : carte en relief
  (MapLibre GL, copié dans l'appli ; relief Mapzen / AWS Terrain Tiles, sans compte ni clé), fond plan
  OpenStreetMap ou satellite (Esri), relief accentué réglable (×1 à ×3, ×1,8 par défaut). La caméra suit le point
  en regardant dans le sens de la sortie ; même lecteur que la carte 2D (vitesse, pause, infos du point, profil,
  plein écran) ; tracé déjà parcouru en couleur d'accent.

### Modifié
- Le lecteur de sortie ne dépend plus de Leaflet : la carte 2D et le survol 3D l'utilisent chacun avec leur
  affichage du point.

## 0.18.1 — 2026-10-03

### Ajouté
- Lecture d'une sortie : **Suivre le point** (activé par défaut) : au lancement, la carte zoome sur le point,
  puis le recadre dès qu'il approche du bord, même si on a zoomé ou déplacé la carte.
- **Plein écran** : la carte occupe tout l'écran, commandes, infos du point et profil d'altitude en surimpression
  en bas ; Échap ou le même bouton pour sortir.

## 0.18.0 — 2026-10-03

### Ajouté
- **Rejouer une sortie** (fiche d'une sortie et fiche d'un parcours) : bouton lecture sous la carte, un point
  avance sur le tracé au vrai rythme de la sortie (arrêts et montées compris) ; pause, barre de position, vitesse
  ×30 à ×1000. À chaque instant : coordonnées GPS, altitude, pente, distance, temps, allure ou vitesse, FC, et un
  profil d'altitude dont le curseur suit le point (cliquer ou glisser sur le profil pour s'y déplacer).
  Les données point par point sont téléchargées chez Garmin au premier « lecture » puis gardées en base ; sans
  elles, la sortie est rejouée à vitesse constante (position et distance seulement).
- **Sens du parcours** sur toutes les cartes de tracé : 100 premiers mètres à la couleur du départ (vert),
  100 derniers à celle de l'arrivée (rouge), et une flèche par km.

## 0.17.1 — 2026-10-02

### Modifié
- Paramètres en **onglets**, comme Sports et Tags : Apparence (thème, disposition, palettes, import Labs),
  Sorties et carte (domicile, limites des vérifications), Santé (poids), Synchronisation. Les liens vers une
  section (depuis Santé, Carte, Synchronisation…) et les enregistrements ouvrent le bon onglet.

## 0.17.0 — 2026-10-02

### Modifié
- **Menu réorganisé** en catégories avec une icône par page : Sorties (Activités, Carte, Matériel, Amis), Analyse
  (Progression, Forme), Santé, Données (Synchronisation, Vérifications), Réglages (Sports, Paramètres). Douze
  entrées au lieu de seize ; les alertes (sorties à vérifier, pesée, entretien) restent sur leur page.
- Pages regroupées en **onglets** (leurs adresses ne changent pas) : Carte · Parcours et segments, Progression ·
  Bilan de l'année, Synchroniser · Récupérer l'historique, Sports et règles · Tags.
- Mise en page « En-tête » : une catégorie = un menu déroulant (un seul ouvert, fermé par un clic ailleurs ou
  Échap) ; une alerte remonte sur le titre de la catégorie.

## 0.16.1 — 2026-10-02

### Modifié
- Image du bilan : photo de profil (ronde, initiales s'il n'y en a pas) et nom de l'utilisateur en grand (pseudo,
  sinon prénom et nom), l'année en dessous.

## 0.16.0 — 2026-10-02

### Ajouté
- **Bilan de l'année** (onglet Bilan, une année au choix) : sorties, distance, temps, dénivelé, jours et semaines
  actifs, meilleure série, comparés à l'année précédente (à la même date pour l'année en cours, avec une
  projection de fin d'année au rythme actuel) ; calendrier de l'année (un carré par jour, plus foncé selon la
  charge) ; part de chaque sport avec ses records ; mois par mois et mois record ; records de l'année et records
  de segments ; matériel le plus utilisé, amis les plus fréquents, parcours les plus faits, lieux ; santé (FC de
  repos, sommeil, pas) et météo (sortie la plus froide, la plus chaude, la plus ventée, sous la pluie).
- **Image à partager** : carte PNG 1080 × 1350 du bilan, aux couleurs sombres du thème, créée sur le PC
  (bouton « Télécharger l'image »).

## 0.15.0 — 2026-10-02

### Ajouté
- **Onglet Forme** :
  - **Charge d'entraînement** calculée sur le PC d'après la FC de chaque sortie (TRIMP de Banister) : charge des
    7 derniers jours, condition (42 jours), fatigue (7 jours), fraîcheur (condition − fatigue), sur 3 mois à 2 ans.
  - **Ratio aigu / chronique** avec sa zone idéale (0,8 à 1,3) et un avertissement au-dessus ; pas de ratio pendant
    une reprise après une coupure.
  - **Récupération** : FC de repos, sommeil et Body Battery (moyennes 7 jours) sur le même axe de temps.
  - **VFC de la nuit** (variabilité cardiaque) et statut Garmin, si la montre la mesure : nouvelles nuits à chaque
    synchro, l'année passée petit à petit ; après 14 nuits vides d'affilée, l'historique n'est plus demandé.
  - **Sommeil → vitesse** : chaque sortie comparée à ta vitesse habituelle pour le même sport (±60 jours), selon
    le sommeil de la nuit précédente (nuage de points, moyennes par tranche, force du lien).
  - **Poids → vitesse** : même analyse selon le poids de la dernière pesée, dès 10 pesées sur 8 semaines.

## 0.14.1 — 2026-10-02

### Corrigé
- Page d'un segment : erreur 500 pendant l'analyse en tâche de fond (l'avancement ne recevait pas l'état de la
  tâche). L'analyse elle-même n'était pas touchée.

## 0.14.0 — 2026-10-02

### Ajouté
- **Segments** : sous la carte d'une sortie ou d'un parcours, « Créer un segment sur ce tracé » ; un clic sur le
  départ, un clic sur l'arrivée, un nom. Toutes les sorties de la même famille qui empruntent la portion dans le
  même sens sont retrouvées à partir des tracés (sans appel Garmin), puis chronométrées d'après leurs données
  point par point (temps, position, distance, FC, altitude), téléchargées une fois et seulement pour ces sorties.
- Page d'un segment : record, temps moyen, profil d'altitude (dénivelé, pente moyenne et maximale sur 100 m),
  carte, courbe des temps et classement de tous les passages (écart au record, allure, FC, météo). Renommer,
  supprimer, réanalyser. Liste des segments dans l'onglet Parcours.
- Fiche d'une sortie : « Segments traversés » avec le temps, le rang et le record de chacun.
- Tableau de bord : bandeau « Nouveau record sur … » pendant 7 jours après un record battu.
- La synchro chronomètre les nouvelles sorties sur les segments existants ; une analyse lancée depuis un segment
  apparaît dans le journal des synchros (type « segments »).

## 0.13.0 — 2026-10-02

### Ajouté
- **Parcours répétés** (nouvel onglet Parcours) : les sorties faites sur le même tracé, dans le même sens, sont
  regroupées automatiquement (même famille de sports, distance à 5 % près, départ et arrivée à moins de 300 m,
  80 % du tracé en commun). Pour chaque parcours : passages, meilleur temps, temps moyen, courbe des temps, carte,
  classement de chaque passage avec l'écart au meilleur, et nom modifiable (gardé aux recalculs). Dans la fiche
  d'une sortie : « Même parcours », son rang et l'écart au meilleur. Recalcul après chaque synchro qui apporte de
  nouveaux tracés.
- **Météo au départ** de chaque sortie, récupérée chez Garmin (station la plus proche) : température et ressenti,
  vent et direction, rafales, humidité, point de rosée, ciel. Dans la fiche, à côté de l'heure dans la liste des
  activités et des passages d'un parcours, et dans Progression (« Selon la météo » : allure moyenne par tranche
  de température et de vent). L'historique se complète petit à petit à chaque synchro, après les tracés ; une
  limite Garmin (429) l'arrête sans mettre la synchro en erreur.

## 0.12.0 — 2026-10-02

### Ajouté
- **Objectifs** (page Progression, section Objectifs) : distance, durée, nombre de sorties ou dénivelé, pour tous
  les sports, une famille ou un sport, par semaine, par mois ou par année. Barre de la période en cours avec le
  repère du rythme régulier, avance ou retard, reste à faire par semaine, et périodes précédentes atteintes ou non.
  Les objectifs s'affichent aussi sur le tableau de bord.
- **Carte de chaleur** (page Carte, bouton « Chaleur ») : tous les parcours en traits fins et légers sur un fond
  assombri ; les routes souvent faites deviennent vives, les coins jamais explorés restent sombres. Tout
  l'historique par défaut.
- **Entretien du matériel** (fiche d'un matériel) : entretiens récurrents tous les N km et/ou N mois (le premier
  atteint), suggestions par type (chaîne, pneus, plaquettes…), bouton « Fait » avec date et coût, journal des
  entretiens. Un entretien dû s'affiche en bandeau sur le tableau de bord (« Fait aujourd'hui »), par une
  pastille sur l'onglet Matériel et sur la carte du matériel.
- `TODO.md` : idées de fonctionnalités, à cocher une fois livrées.

## 0.11.1 — 2026-10-02

### Modifié
- Matériel : le choix des sports (affectation en bloc, sports par défaut) reprend les tuiles du menu des sports
  de la page Activités ; un point de couleur marque les sports cochés.

## 0.11.0 — 2026-10-02

### Ajouté
- **Matériel** (nouvel onglet) : vélos, chaussures et « autre », avec photo ronde (comme les amis) ou icône
  colorée, marque et modèle, dates de mise en service et de retrait, alerte d'usure en km et prix d'achat
  (coût au km). Fiche par matériel : sorties, distance, temps, dénivelé, usure, sports par défaut.
- **Affecter en bloc** : un matériel sur toutes les sorties de certains sports entre deux dates (par ex. le
  nouveau vélo depuis le 21/04/2026), avec aperçu en direct des sorties touchées et du matériel remplacé. Une
  sortie porte au plus un matériel de chaque type.
- **Matériel par défaut d'un sport** : posé automatiquement sur les nouvelles sorties synchronisées pendant sa
  période de service.
- Activités : mini-avatar du matériel sous le nom de la sortie et filtre « Matériel » ; fiche d'une sortie :
  choix du matériel par type.

### Corrigé
- Sports : le bouton « Enregistrer et reclasser » ne touche plus le champ État quand il est plus large que sa
  colonne.

## 0.10.0 — 2026-10-01

### Ajouté
- **Suivi du poids** (section Poids de la page Santé) : saisie d'une pesée par jour, historique avec IMC,
  évolution sur la période choisie, courbe avec moyenne des 7 dernières pesées et ligne d'objectif. Le poids
  du profil suit la dernière pesée.
- **Rappel de pesée** : bandeau sur le tableau de bord avec un champ pour saisir le poids, et point sur
  l'onglet Santé, quand la dernière pesée date de N jours ou plus. N et l'objectif de poids se règlent dans
  Paramètres (0 = pas de rappel).

### Modifié
- Activités : le menu des sports devient une palette d'icônes (une ligne par famille, grandes tuiles aux
  couleurs des sports), la proposition A retenue.

## 0.9.4 — 2026-10-01

### Ajouté
- Activités : dernière colonne avec un bouton-icône pour télécharger le GPX (vide pour les sorties sans tracé).
- Santé : choix de la période (30 jours, 3 mois, 12 mois, cette année, l'année dernière, tout l'historique ou
  dates libres), comparée à la période précédente de même durée.

## 0.9.3 — 2026-10-01

### Corrigé
- Fiche d'une activité : après une action (ami, tag, sport, exclusion…), « Retour » renvoyait en boucle sur la
  fiche. Il renvoie maintenant à la page d'où on l'a ouverte (liste filtrée, ami, vérifications…), sinon à la
  dernière liste d'activités consultée, filtres compris.

## 0.9.2 — 2026-10-01

### Modifié
- Liste des activités :
  - changement de sport par un clic sur l'icône du sport : petit menu avec les familles, leurs icônes et
    leurs sports (le sport actuel en surbrillance), puis le choix habituel « cette activité / règle » ;
    cadenas sur l'icône quand le sport a été corrigé à la main ;
  - pastille du jour (Lu, Ma, Me…) devant la date, l'heure en dessous ;
  - plus de type Garmin (cycling, running…) ni de colonne « Classée par » (déverrouillage dans la fiche).
- Durées sans espaces partout : « 1h09min24s », « 3h56 », « 50min ».

## 0.9.1 — 2026-10-01

### Ajouté
- Amis : champ **Pseudo**, nom affiché partout (liste, fiche, « Avec qui », filtre, photos) ; prénom et nom
  restent visibles dans la fiche de l'ami. Dans le profil, « Surnom » devient « Pseudo (nom affiché) ».

## 0.9.0 — 2026-10-01

### Ajouté
- **Amis** (nouvel onglet) : prénom, nom, note et photo ; fiche par ami avec sorties ensemble, distance et
  temps partagés, sports pratiqués ensemble. Dans la fiche d'une activité, section « Avec qui » pour cocher
  une ou plusieurs personnes. Dans Activités : petites photos des amis sur chaque ligne et filtre « Avec ».
- **Profil** (lien avec ta photo et ton surnom dans la navigation) : identité, date de naissance, ville, club,
  taille, poids, FC max et de repos ; âge, IMC, réserve cardiaque et zones cardio (FC max estimée si absente) ;
  bilan depuis la première activité (totaux, semaines actives, plus longue série et série en cours, plus
  longue sortie et meilleure allure par famille).
- Photos recadrées en carré et réduites à 256 px (bibliothèque Pillow), gardées dans `jgarmin.db` :
  jamais dans Git. Sans photo : initiales sur une couleur propre à chaque personne.

## 0.8.0 — 2026-10-01

### Ajouté
- **Icônes des familles et des sports** (police Phosphor de Labs, licence MIT, copiée en local) : sélecteur de
  53 icônes de sport dans la page Sports ; un sport sans icône prend celle de sa famille. Icônes attribuées
  d'office d'après les noms (course, trail, tapis, vélo, VTT, vélo électrique, natation, marche, rando,
  muscu, yoga…), bases existantes comprises. L'icône, à la couleur du sport, remplace la pastille de
  couleur partout : liste et fiche des activités, tableau de bord, carte, vérifications, règles.

## 0.7.2 — 2026-10-01

### Ajouté
- Vérifications : case « tout cocher » dans l'en-tête de chaque section (allure impossible, inhabituelle,
  pointes), à moitié cochée quand une partie seulement de la section l'est.

## 0.7.1 — 2026-10-01

### Ajouté
- Page Sports : ordre des familles et des sports avec des flèches ▲ ▼, et bouton « Trier par utilisation »
  (du plus pratiqué au moins pratiqué, « Autre » en dernier). L'ordre est repris dans toutes les listes.
- « Supprimer la famille » (avec confirmation) : retire une famille, ses sports et leurs règles d'un coup ;
  ses activités sont reclassées par les règles restantes.

### Modifié
- Vérifications : actions sur deux lignes nettes (corriger, puis « ✓ C'est bien moi » / « Exclure des stats »)
  et liste des sports avec le nom complet de la famille.

## 0.7.0 — 2026-10-01

### Ajouté
- **Vérifications** (nouvel onglet, avec le nombre d'alertes dans la navigation) : repère les allures
  impossibles pour le sport, les allures inhabituelles pour toi (nettement plus rapides que ta médiane du même
  sport : montre prêtée…) et les pointes de vitesse aberrantes (sauts de GPS). Pour chaque alerte : exclure,
  changer de sport, ignorer la pointe, ou « c'est bien moi ».
- **Exclure des statistiques** (page Vérifications et en lot dans Activités, avec une raison) : l'activité
  reste dans la liste, grisée avec un badge, mais sort du tableau de bord, de la progression, des records et
  de la carte. Réversible (« Réintégrer »). Filtre « Statistiques : comptées / exclues » dans Activités.
- **Pointe GPS ignorée** : la sortie compte, mais sa vitesse / allure max ne sert plus dans les records ni la
  colonne « Max ». En lot : « Ignorer les pointes cochées ».
- Paramètres : limites par famille (moyenne et pointe les plus rapides) et écart « inhabituel » (25 %).

## 0.6.1 — 2026-10-01

### Corrigé
- Page Sports : les boutons « Enregistrer » / « Supprimer » débordaient du panneau en disposition colonne.
  Les lignes passent à la ligne quand la place manque ; les types Garmin passent sous la liste sur écran moyen.
- Graphiques : lissage des courbes sans dépassement ; durée mensuelle de Progression en segments droits.
- CSS et JavaScript revalidés à chaque chargement : une mise à jour de l'appli s'applique sans vider le cache.

## 0.6.0 — 2026-10-01

### Ajouté
- **Progression : choix de la période analysée** : 3 / 6 / 12 / 24 derniers mois, cette année, l'année
  dernière, tout l'historique, ou dates libres (du … au …). Sorties, distance, durée et dénivelé comparés à la
  période précédente de même durée. Graphique de volume par semaine quand la période fait moins de 3 mois.

## 0.5.0 — 2026-10-01

### Ajouté
- **Historique** (nouvel onglet) : couverture mois par mois de ce qui est en base (activités, tracés, jours de
  santé), choix d'une année ou de mois en un clic, estimation de durée, récupération en arrière-plan des
  périodes plus anciennes. Les jours déjà en base sont sautés : après une erreur 429, relancer reprend où
  ça s'est arrêté. En ligne de commande : `jgarmin history --from 2023-01 [--to 2024-12] [--no-health]`.
- **Carte** : centrée sur ton domicile (déduit des points de départ et d'arrivée les plus fréquents, ou posé
  à la main dans Paramètres) ; menu « Lieu » pour zoomer sur un lieu Garmin (avec le nombre de sorties).

### Modifié
- Durées écrites avec leurs unités : « 3 h 56 », « 50 min », « 1 h 38 min 11 s » dans les fiches. Le « : »
  reste réservé aux allures (4:21 /km).

## 0.4.1 — 2026-10-01

### Modifié
- Disposition en colonne : la navigation est maintenant fixée **à gauche** (comme « Colonne » de Labs) au lieu
  de la droite. Un réglage « colonne à droite » déjà enregistré passe automatiquement à gauche.

## 0.4.0 — 2026-10-01

### Ajouté
- **GPX** : bouton « Télécharger le GPX » dans la fiche et lien « GPX » sur chaque ligne de la liste. Parcours à
  suivre (latitude, longitude), fabriqué depuis le tracé en base : instantané, sans appel à Garmin.
- **Paramètres** (nouvel onglet) :
  - disposition « En-tête » ou en colonne (voir 0.4.1) ;
  - palette : Sarcelle (celle de JBudget) et les 8 palettes de Labs, 8 couleurs en clair et 8 en sombre ;
  - mode clair, sombre ou selon Windows, plus un bouton soleil / lune dans la navigation ;
  - palettes personnalisées : éditeur des 16 couleurs avec aperçu et vérification des contrastes, import du
    JSON des palettes de Labs (copié depuis phpMyAdmin) ;
  - synchro : historique du premier lancement, jours re-synchronisés, synchro au lancement de `jgarmin.bat`.
- **Synchro** : le bouton dit depuis quand il synchronise et ce qu'il va chercher (activités, jours de santé,
  tracés manquants) ; l'indicateur de la barre de navigation lance une synchro depuis n'importe quelle page.
- `jgarmin sync` prend ses valeurs par défaut dans les Paramètres.

## 0.3.0 — 2026-10-01

### Ajouté
- **Tracés GPS** : récupérés à la synchro (une fois par activité en extérieur, après la santé ; une
  interruption reprend au tracé suivant), stockés simplifiés dans la base locale (table `activity_tracks`).
- Fiche d'une activité : carte du parcours (fond OpenStreetMap via Leaflet 1.9.4 copié en local), départ et
  arrivée marqués.
- Liste des activités : mini-carte du parcours sur chaque ligne.
- Nouvelle page **Carte** : tous les parcours superposés aux couleurs des sports, filtres sport et période,
  survol pour voir la sortie, clic pour ouvrir sa fiche.
- Journal de synchro : nombre de tracés ajoutés.

## 0.2.0 — 2026-10-01

### Ajouté
- Fiche d'une activité : vitesse ou allure max, dénivelé −, altitude min–max, durée écoulée (pauses
  comprises), nombre de tours, eau perdue estimée, VO2max après la sortie ; pour la course, cadence moyenne
  et max, longueur de foulée, pas ; temps passé dans chacune des 5 zones cardio ; meilleurs temps mesurés par
  la montre (1 km, 1 mile, 5 km, 40 km) ; mention quand Garmin a enregistré un record personnel.
- Progression : meilleurs temps sur 1 km, 1 mile, 5 km et 40 km, et vitesse / allure max dans les records.
- Activités : colonne « Max » (vitesse ou allure de pointe).
- Les bases existantes sont complétées au démarrage à partir du JSON déjà stocké : rien à re-télécharger.

### Corrigé
- Activités : les listes de sports (changement en ligne et en lot) étaient vides.

## 0.1.1 — 2026-10-01

### Corrigé
- L'interface ne répondait pas : le port 5002 est aussi écouté par l'agent Cisco Secure Client, qui recevait
  les requêtes à la place du serveur. Port par défaut : **5003** (`jgarmin.bat`, `jgarmin serve`).
- `jgarmin serve` refuse de démarrer, avec un message clair, si un autre programme répond déjà sur le port.

## 0.1.0 — 2026-10-01

Première version.

### Ajouté
- Fonctionne derrière un proxy d'entreprise qui inspecte le HTTPS (Cisco Umbrella, Zscaler…) : les
  certificats racine de Windows sont ajoutés à ceux de Python (`%USERPROFILE%\.jgarmin\ca-bundle.pem`).
  Désactivable avec `JGARMIN_SYSTEM_CERTS=0`.
- Page Santé : le score de sommeil n'est affiché que si Garmin en fournit pour la montre.
- **Connexion Garmin** : `jgarmin login` (e-mail, mot de passe et code MFA demandés dans le terminal). Le mot de
  passe n'est jamais enregistré ; seuls les jetons de session le sont, dans `%USERPROFILE%\.jgarmin\tokens`.
  `jgarmin logout` les supprime.
- **Synchronisation** incrémentale (CLI `jgarmin sync` et bouton dans l'interface, avec avancement) :
  activités depuis la dernière connue, santé jour par jour avec re-synchro des 3 derniers jours ; premier
  lancement = 12 mois d'historique. Sans doublon (identifiant Garmin, date). JSON brut gardé en base.
  Une synchro interrompue (erreur 429, coupure) garde ce qui est fait et reprend là où elle s'est arrêtée.
- **Santé** : FC au repos, sommeil (durée, phases, score), Body Battery (min, max, rechargé, dépensé), pas,
  stress moyen et max, VO2max.
- **Sports** : familles Course (Route, Trail, Tapis), Vélo (Route, VTT, Home trainer), Natation (Piscine,
  Eau libre), Marche & rando, Renforcement (Musculation, Yoga), Autre ; une couleur et une unité d'allure par
  sport ; règles sur le type Garmin ou le nom, avec test en direct ; correction manuelle verrouillée, en ligne
  ou en lot, qui peut créer une règle.
- **Écrans** : tableau de bord (semaine en cours vs précédente, volume des 12 dernières semaines par sport,
  mini-courbes santé 30 jours), activités (filtres, changement de sport et tags en lot, fiche détaillée),
  progression par sport (volume mensuel, allure ou vitesse avec tendance, records), santé (30 / 90 / 365 jours,
  moyennes glissantes 7 jours), sports et règles, tags, synchronisation (journal).
- Commandes `activities`, `health`, `week`, `sports`, `reclassify`, `serve` ; `jgarmin.bat` pour Windows.
