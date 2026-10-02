"""Menu (0.17.0) : catégories, pages, icônes et onglets des pages regroupées.

Une page regroupée garde son adresse ; elle n'a plus d'entrée dans le menu mais un onglet en haut de la page
principale de son groupe (par ex. Historique est un onglet de Synchronisation).
"""

from __future__ import annotations

# (titre de la catégorie, icône, [(endpoint, libellé, icône)])
NAV: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    ("Accueil", "house", [("dashboard", "Tableau de bord", "house")]),
    ("Sorties", "list-bullets", [("activities", "Activités", "list-bullets"), ("map_page", "Carte", "map-trifold"),
                                 ("gear_page", "Matériel", "bicycle"), ("friends_page", "Amis", "users-three")]),
    ("Analyse", "chart-line-up", [("progress", "Progression", "chart-line-up"), ("form_page", "Forme", "gauge")]),
    ("Santé", "heartbeat", [("health", "Santé", "heartbeat")]),
    ("Données", "arrows-clockwise", [("sync_page", "Synchronisation", "arrows-clockwise"),
                                     ("checks_page", "Vérifications", "list-checks")]),
    ("Réglages", "gear-six", [("sports", "Sports", "person-simple-run"), ("settings_page", "Paramètres", "gear-six")]),
]

# Onglets des pages regroupées : la première est celle du menu.
TABS: list[list[tuple[str, str, str]]] = [
    [("map_page", "Carte", "map-trifold"), ("routes_page", "Parcours et segments", "path")],
    [("progress", "Progression", "chart-line-up"), ("review_page", "Bilan de l'année", "trophy")],
    [("sync_page", "Synchroniser", "arrows-clockwise"), ("history_page", "Récupérer l'historique", "clock-counter-clockwise")],
    [("sports", "Sports et règles", "person-simple-run"), ("tags_page", "Tags", "tag")],
]

# Pages de détail -> page de leur liste (pour l'onglet et l'entrée du menu en surbrillance).
DETAILS = {"activity_detail": "activities", "palette_form": "settings_page", "friend_detail": "friends_page",
           "gear_detail": "gear_page", "route_detail": "routes_page", "segment_detail": "routes_page"}


def owner(endpoint: str | None) -> str | None:
    """Entrée du menu à mettre en surbrillance pour cette page."""
    ep = DETAILS.get(endpoint or "", endpoint)
    for tabs in TABS:
        if any(t[0] == ep for t in tabs):
            return tabs[0][0]
    return ep


def tabs_for(endpoint: str | None) -> tuple[list[tuple[str, str, str]], str] | None:
    """(onglets, onglet actif) si la page fait partie d'un groupe, sinon None."""
    ep = DETAILS.get(endpoint or "", endpoint)
    for tabs in TABS:
        if any(t[0] == ep for t in tabs):
            return tabs, ep
    return None
