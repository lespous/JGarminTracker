"""Familles, sports, couleurs et règles de départ, créés au premier lancement."""

from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .classifier import PRIORITY_SEED
from .models import Sport, SportFamily, SportRule

# Famille -> [(sport, couleur, unité d'allure)]. Couleurs lisibles sur fond clair comme sombre.
FAMILIES: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Course", [("Route", "#E4572E", "min_km"), ("Trail", "#B5452A", "min_km"), ("Tapis", "#F08A5D", "min_km")]),
    ("Vélo", [("Route", "#2E86DE", "kmh"), ("VTT", "#1B5E9E", "kmh"), ("Home trainer", "#6FA8DC", "kmh")]),
    ("Natation", [("Piscine", "#13A89E", "min_100m"), ("Eau libre", "#0B7A72", "min_100m")]),
    ("Marche & rando", [("Marche", "#6AA84F", "min_km"), ("Randonnée", "#3F7D2C", "min_km")]),
    ("Renforcement", [("Musculation", "#8E6CC9", "none"), ("Yoga", "#B79CE0", "none")]),
    ("Autre", [("Autre", "#8A94A0", "none")]),
]
FALLBACK = ("Autre", "Autre")

# (famille, sport) -> motifs. Par défaut, sur le type Garmin (typeKey) :
# « X » = égal à X ; « ~X » = contient X ; « re:X » = expression régulière ; « name:… » = sur le nom de l'activité.
# Les motifs « ~ » et « re: » ont une priorité plus basse que les égalités exactes.
RULES: dict[tuple[str, str], list[str]] = {
    ("Course", "Route"): ["running", "street_running", "track_running", "obstacle_run", "~run"],
    ("Course", "Trail"): ["trail_running", "ultra_run", "name:~trail"],
    ("Course", "Tapis"): ["treadmill_running", "indoor_running", "virtual_run"],
    ("Vélo", "Route"): ["cycling", "road_biking", "gravel_cycling", "cyclocross", "e_bike_fitness",
                        "recumbent_cycling", "track_cycling", "re:cycl|bik"],
    ("Vélo", "VTT"): ["mountain_biking", "enduro_mtb", "downhill_biking", "e_bike_mountain", "bmx"],
    ("Vélo", "Home trainer"): ["indoor_cycling", "virtual_ride", "name:~home trainer", "name:~zwift"],
    ("Natation", "Piscine"): ["lap_swimming", "swimming", "~swim"],
    ("Natation", "Eau libre"): ["open_water_swimming"],
    ("Marche & rando", "Marche"): ["walking", "casual_walking", "speed_walking", "~walk"],
    ("Marche & rando", "Randonnée"): ["hiking", "mountaineering", "rucking", "~hik"],
    ("Renforcement", "Musculation"): ["strength_training", "fitness_equipment", "hiit", "indoor_cardio",
                                      "bouldering", "indoor_climbing"],
    ("Renforcement", "Yoga"): ["yoga", "pilates", "breathwork"],
}


def parse_pattern(raw: str) -> tuple[str, str, str, int]:
    """Motif compact -> (champ, type, motif, priorité)."""
    field, bonus = "type_key", 0
    if raw.startswith("name:"):
        # Un nom explicite (« Trail des collines ») l'emporte sur le type Garmin générique.
        field, raw, bonus = "name", raw.removeprefix("name:"), 30
    if raw.startswith("re:"):
        return field, "regex", raw.removeprefix("re:"), PRIORITY_SEED - 20 + bonus
    if raw.startswith("~"):
        return field, "contains", raw.removeprefix("~"), PRIORITY_SEED - 10 + bonus
    return field, "equals", raw, PRIORITY_SEED + bonus


def local_rules_path() -> Path:
    return Path(os.environ.get("JGARMIN_RULES") or Path.cwd() / "sports.local.json")


def load_local_rules(path: Path | None = None) -> list[dict]:
    """Règles personnelles gardées hors du dépôt Git (noms de parcours, de clubs…).

    Format : liste d'objets {"family": "Course", "sport": "Trail", "pattern": "name:~sentier"}.
    """
    path = path or local_rules_path()
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def seed(session: Session) -> bool:
    """Crée familles, sports et règles si la base n'en a aucun. Renvoie True si quelque chose a été créé."""
    if session.scalar(select(func.count(Sport.id))):
        return False
    sports: dict[tuple[str, str], Sport] = {}
    for fpos, (fname, items) in enumerate(FAMILIES):
        family = SportFamily(name=fname, position=fpos)
        session.add(family)
        for spos, (sname, color, unit) in enumerate(items):
            sport = Sport(family=family, name=sname, color=color, pace_unit=unit, position=spos,
                          fallback=(fname, sname) == FALLBACK)
            session.add(sport)
            sports[(fname, sname)] = sport
    session.flush()

    entries = [(key, raw) for key, patterns in RULES.items() for raw in patterns]
    entries += [((e["family"], e["sport"]), e["pattern"]) for e in load_local_rules()]
    for key, raw in entries:
        if key not in sports:
            raise ValueError(f"sports.local.json : sport « {key[0]} › {key[1]} » inconnu")
        field, match_type, pattern, priority = parse_pattern(raw)
        session.add(SportRule(field=field, match_type=match_type, pattern=pattern, sport_id=sports[key].id,
                              priority=priority, origin="seed"))
    session.flush()
    return True
