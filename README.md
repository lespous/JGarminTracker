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
jamais tes tracés). Leaflet 1.9.4 est copié dans `static/`. Les tracés restent dans `jgarmin.db`.

## Données

Tout est stocké en unités SI (secondes, mètres, m/s) ; la conversion (km, min/km, km/h, min/100 m, h:mm)
se fait à l'affichage. Le JSON brut de Garmin est gardé (activités, résumé du jour, sommeil, VO2max) pour
recalculer sans tout re-télécharger. La nuit de sommeil est rattachée au jour du réveil.

## Tests

```powershell
.venv\Scripts\python -m pytest
```

Aucun appel réseau : la synchro est testée avec `FakeSource` et des données **inventées** (`tests/fixtures`).
