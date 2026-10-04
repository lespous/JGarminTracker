---
title: JGarminTracker
slug: jgarmintracker
summary: Un outil personnel qui récupère les données de ma montre Garmin (activités, sommeil, santé), les garde en local et montre ma progression semaine après semaine.
year: 2026
status: active
version: 0.19.2
featured: true
published: true
sortOrder: 1
tags: [Python, Données, Sport, Santé]
stack: [Python, Typer, Rich, SQLite, SQLAlchemy, Flask, HTMX, Chart.js, Leaflet, MapLibre GL, garminconnect, Pillow, pytest]
cover: jgarmintracker-cover.png
repoUrl: https://github.com/lespous/JGarminTracker
---
JGarminTracker récupère les données de ma montre Garmin, les garde dans une base sur mon PC et me montre leur évolution : combien j'ai couru ou roulé cette semaine par rapport aux précédentes, si mon allure progresse, si ma FC au repos et mon sommeil vont dans le bon sens.

Les données de santé ne quittent jamais le PC : seuls les jetons de session Garmin sont enregistrés, jamais le mot de passe.

## Ce que fait l'outil

- **Synchronisation incrémentale** : nouvelles activités, santé jour par jour (FC au repos, sommeil, Body Battery, pas, stress, VO2max) et tracés GPS, sans doublon. Une synchro interrompue reprend là où elle s'est arrêtée, et une page Historique récupère les années plus anciennes.
- **Sports classés par des règles** : chaque activité reçoit un sport d'après son type Garmin ou son nom (« Trail des crêtes » va dans Trail). Corriger un sport peut créer une règle, appliquée aux synchros suivantes. Familles, couleurs et icônes réglables.
- **Progression** : volume par semaine et par sport, allure ou vitesse de chaque sortie avec sa tendance, records (plus longue sortie, meilleurs 1 km, 5 km et 40 km mesurés par la montre), sur la période de mon choix et comparés à la période précédente.
- **Santé** : FC au repos avec moyenne glissante, sommeil par phase, plage de Body Battery, stress, pas, VO2max, et suivi du poids avec rappel de pesée, IMC et objectif.
- **Cartes** : parcours de chaque sortie sur fond OpenStreetMap, carte de tous mes parcours centrée sur la maison (et en carte de chaleur), export GPX pour refaire un parcours, et lecture de chaque sortie sur sa carte (le point avance au vrai rythme, de ×2 à ×1000, avec altitude, pente, allure et FC à chaque instant, et survol 3D en relief).
- **Vérifications** : repère les sorties suspectes (allure impossible, pointe de GPS, montre prêtée à quelqu'un de plus rapide) pour les exclure des statistiques sans les supprimer.
- **Matériel** : vélos et chaussures avec photo, usure et coût au km, affectés en bloc aux sorties d'une période ou posés par défaut selon le sport, avec rappels d'entretien (chaîne, pneus, révision).
- **Parcours répétés et météo** : les sorties faites sur le même tracé sont reconnues et classées au temps, et chaque sortie garde la météo du départ (allure selon la température et le vent).
- **Segments** : une portion de parcours choisie sur la carte (une montée, une ligne droite) est chronométrée sur toutes les sorties qui l'empruntent, avec classement, record et profil d'altitude.
- **Forme** : charge d'entraînement calculée d'après la FC (condition, fatigue, fraîcheur, ratio aigu / chronique), récupération, et ce qui joue sur ma vitesse (sommeil de la veille, poids).
- **Bilan de l'année** : l'année en chiffres et en calendrier, records, matériel, amis, santé et météo, avec une image à partager.
- **Objectifs** : km, heures, sorties ou dénivelé par semaine, mois ou année, avec avance ou retard sur le rythme.
- **Amis et profil** : avec qui j'ai fait chaque sortie, et un bilan de carrière (totaux, séries de semaines actives, zones cardio).

Tout tourne en local, avec une interface web pour consulter et corriger (thèmes et palettes partagés avec ce site), et une ligne de commande pour synchroniser et résumer.
