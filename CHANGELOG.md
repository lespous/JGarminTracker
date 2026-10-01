# Journal des versions

Numérotation `MAJEUR.MINEUR.CORRECTIF` : une nouvelle fonctionnalité augmente le chiffre du milieu,
une simple correction le dernier. Le numéro vit dans `jgarmintracker/__init__.py` ; chaque version a son tag Git (`v0.1.0`).

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
