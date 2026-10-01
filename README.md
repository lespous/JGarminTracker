# JGarminTracker

Récupère les données de ta montre Garmin (activités, sommeil, FC au repos, Body Battery, pas, stress, VO2max),
les garde dans une base SQLite **locale** et montre leur évolution : volume par semaine et par sport,
progression de l'allure, tendances santé.

Les données ne quittent jamais le PC. Le mot de passe Garmin n'est jamais enregistré.

> S'appuie sur [`garminconnect`](https://github.com/cyberjunky/python-garminconnect), une bibliothèque
> **non officielle** (version épinglée : 0.3.17). Si Garmin change son API, seul `jgarmintracker/garmin.py`
> est à adapter.

## Installation (Windows, PowerShell)

```powershell
cd D:\AG\JGarminTracker
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
$env:PYTHONIOENCODING = "utf-8"   # accents corrects dans la console
.venv\Scripts\jgarmin --version
```

## Premier lancement

```powershell
.venv\Scripts\jgarmin login       # e-mail, mot de passe, code MFA si le compte l'exige
.venv\Scripts\jgarmin sync        # 1re fois : 12 mois d'historique, quelques minutes
.\jgarmin.bat                     # ouvre http://127.0.0.1:5003
```

Ensuite, pour synchroniser : double-clic sur `jgarmin-sync.bat` (lance `jgarmin login` d'abord s'il n'y a pas
encore de session ; `jgarmin-sync.bat --full` relit les 12 derniers mois).

Les jetons de session sont rangés dans `%USERPROFILE%\.jgarmin\tokens` (ou `$JGARMIN_TOKENS`). S'ils
expirent, la synchro le dit : relance `jgarmin login`. Le bouton « Synchroniser » de l'interface ne demande
jamais de mot de passe.

## Commandes

```
jgarmin --version
jgarmin login | logout
jgarmin sync [--days 3] [--full] [--months 12]   # incrémental par défaut
jgarmin history --from 2023-01 [--to 2024-12] [--no-health] [--no-activities]   # périodes anciennes
jgarmin activities [--sport Course] [--since 2026-01-01] [-q texte]
jgarmin health [--days 14]
jgarmin week [--sport Course]
jgarmin sports
jgarmin reclassify
jgarmin serve [--port 5003]
```

Base : `jgarmin.db` dans le dossier courant, ou `--db chemin`, ou `$JGARMIN_DB`.

## Sports et règles

Chaque activité reçoit un sport par des règles sur le **type Garmin** (`running`, `trail_running`,
`road_biking`, `lap_swimming`…) ou sur le **nom** de l'activité. La règle de plus haute priorité gagne ;
sans règle, l'activité va dans « Autre ». Une correction à la main est verrouillée et peut créer une règle
(par type ou par nom). Page **Sports** : couleurs, unités d'allure, règles avec test en direct.

Règles personnelles hors du dépôt (noms de parcours, de clubs) : `sports.local.json`, lu à la création de la base.

```json
[{"family": "Course", "sport": "Trail", "pattern": "name:~sentier"}]
```

Motifs : `X` = type égal à X, `~X` = contient X, `re:X` = expression régulière, préfixe `name:` = sur le nom.

## Cartes

La synchro récupère aussi le tracé GPS simplifié de chaque sortie en extérieur (un appel par activité, une
seule fois). Il s'affiche dans la fiche de l'activité, en mini-carte dans la liste, et sur la page **Carte**
qui superpose tous les parcours (filtres sport et période).

Le fond de carte vient d'OpenStreetMap (tuiles chargées depuis internet : le serveur voit la zone affichée,
jamais tes tracés). Leaflet 1.9.4 est copié dans `static/`, comme la police d'icônes Phosphor (licence MIT, reprise de Labs). Les tracés restent dans `jgarmin.db`.

Bouton « Télécharger le GPX » (fiche et liste) : le parcours à suivre dans une appli de navigation, fabriqué
depuis le tracé en base (latitude et longitude seulement).

## Paramètres

Onglet **Paramètres** : disposition (en-tête ou colonne à gauche), palette (Sarcelle et les 8 palettes de
Labs), mode clair / sombre / selon Windows, palettes personnalisées et réglages de synchro, enregistrés dans
`jgarmin.db`.

Importer les palettes personnalisées de Labs : dans phpMyAdmin,
`SELECT value FROM settings WHERE name = 'palettes';` (avec le préfixe des tables s'il y en a un), puis coller
le JSON dans « Importer des palettes de Labs ».

## Amis et profil

Onglet **Amis** : les personnes avec qui tu fais certaines sorties (photo facultative), à cocher dans la fiche
d'une activité (« Avec qui »). Page **Profil** (lien en haut de la navigation) : identité, mesures, zones cardio et
bilan de carrière. Les photos sont réduites à 256 px et gardées dans `jgarmin.db` : jamais dans Git.

## Données

Tout est stocké en unités SI (secondes, mètres, m/s) ; la conversion (km, min/km, km/h, min/100 m, durées « 3 h 56 »)
se fait à l'affichage. Le JSON brut de Garmin est gardé (activités, résumé du jour, sommeil, VO2max) pour
recalculer sans tout re-télécharger. La nuit de sommeil est rattachée au jour du réveil.

## Tests

```powershell
.venv\Scripts\python -m pytest
```

Aucun appel réseau : la synchro est testée avec `FakeSource` et des données **inventées** (`tests/fixtures`).
