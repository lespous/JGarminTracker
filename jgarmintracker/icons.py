"""Icônes des familles et des sports : noms Phosphor (voir web/static/icons.css), libellés et choix automatique."""

from __future__ import annotations

from .classifier import fold

# Nom Phosphor -> libellé (bulle d'aide du sélecteur). Même liste que icons.css.
ICONS: dict[str, str] = {
    "person-simple-run": "Course", "sneaker-move": "Chaussure en mouvement", "sneaker": "Chaussure",
    "mountains": "Montagne", "path": "Chemin", "person-simple-bike": "Cycliste", "bicycle": "Vélo",
    "scooter": "Trottinette", "motorcycle": "Moto", "person-simple-swim": "Nageur", "swimming-pool": "Piscine",
    "waves": "Vagues", "lifebuoy": "Bouée", "sailboat": "Voilier", "boat": "Bateau", "anchor": "Ancre",
    "person-simple-walk": "Marche", "person-simple-hike": "Randonnée", "boot": "Chaussure de marche",
    "tree-evergreen": "Forêt", "compass": "Boussole", "stairs": "Escaliers", "barbell": "Haltère",
    "person-simple-tai-chi": "Yoga, tai-chi", "hand-fist": "Combat", "person-arms-spread": "Étirements",
    "person-simple-ski": "Ski", "person-simple-snowboard": "Snowboard", "snowflake": "Neige",
    "soccer-ball": "Football", "basketball": "Basket", "tennis-ball": "Tennis", "racquet": "Raquette",
    "ping-pong": "Ping-pong", "volleyball": "Volley", "football": "Rugby, football américain", "golf": "Golf",
    "baseball": "Baseball", "hockey": "Hockey", "bowling-ball": "Bowling", "horse": "Équitation",
    "person-simple-throw": "Lancer", "target": "Cible", "heartbeat": "Cardio", "pulse": "Activité",
    "timer": "Chrono", "lightning": "Intensité", "flame": "Effort", "trophy": "Trophée", "medal": "Médaille",
    "sun": "Plein air", "wind": "Vent", "person": "Personne",
}
DEFAULT_ICON = "pulse"

# Mots du nom (sans accents, minuscules) -> icône. Le premier qui correspond l'emporte : du plus précis au plus large.
KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("trail",), "mountains"),
    (("tapis", "treadmill"), "sneaker-move"),
    (("vtt", "mountain bike", "gravel"), "mountains"),
    (("home trainer", "zwift", "indoor"), "timer"),
    (("electrique", "e-bike", "ebike"), "scooter"),
    (("velo", "cycl", "bike", "route velo"), "bicycle"),
    (("piscine", "pool"), "swimming-pool"),
    (("eau libre", "open water", "mer", "lac"), "waves"),
    (("natation", "nage", "swim"), "person-simple-swim"),
    (("rando", "hik", "trek"), "person-simple-hike"),
    (("marche", "walk", "promenade"), "person-simple-walk"),
    (("course", "run", "jogging", "footing"), "person-simple-run"),
    (("yoga", "pilates", "tai chi", "stretch", "etirement"), "person-simple-tai-chi"),
    (("muscu", "renfo", "strength", "fitness", "crossfit", "hiit"), "barbell"),
    (("ski",), "person-simple-ski"),
    (("snowboard",), "person-simple-snowboard"),
    (("foot", "soccer"), "soccer-ball"),
    (("tennis", "padel", "badminton", "squash"), "racquet"),
    (("basket",), "basketball"),
    (("golf",), "golf"),
    (("equitation", "cheval"), "horse"),
    (("voile", "kayak", "aviron", "paddle", "canoe"), "sailboat"),
    (("escalade", "climb", "bloc"), "mountains"),
]


def guess_icon(*names: str | None) -> str | None:
    """Icône d'après un ou plusieurs noms (sport, puis famille). None si rien ne correspond."""
    for name in names:
        text = fold(name)
        if not text:
            continue
        for words, icon in KEYWORDS:
            if any(w in text for w in words):
                return icon
    return None


def valid(icon: str | None) -> str | None:
    """Icône connue, ou None (« comme la famille »)."""
    return icon if icon in ICONS else None
