# Journal des versions

Numérotation `MAJEUR.MINEUR.CORRECTIF` : une nouvelle fonctionnalité augmente le chiffre du milieu,
une simple correction le dernier. Le numéro vit dans `jgarmintracker/__init__.py` ; chaque version a son tag Git (`v0.1.0`).

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
