from types import SimpleNamespace

from sqlalchemy import select

from jgarmintracker.classifier import Classifier, CompiledRule, learn_rule, reclassify, validate_rule
from jgarmintracker.models import Activity, Sport, SportFamily, SportRule


def sport(session, family, name):
    return session.scalar(select(Sport).join(Sport.family).where(SportFamily.name == family, Sport.name == name))


def fake(type_key="", name=""):
    return SimpleNamespace(type_key=type_key, name=name, sport_locked=False, sport_id=None)


def test_seed_creates_families_and_one_fallback(session):
    families = [f.name for f in session.scalars(select(SportFamily).order_by(SportFamily.position))]
    assert families == ["Course", "Vélo", "Natation", "Marche & rando", "Renforcement", "Autre"]
    assert [s.label for s in session.scalars(select(Sport).where(Sport.fallback))] == ["Autre"]
    assert sport(session, "Vélo", "Route").pace_unit == "kmh"
    assert sport(session, "Natation", "Piscine").pace_unit == "min_100m"


def test_type_key_rules(session):
    clf = Classifier(session)
    cases = {
        "running": ("Course", "Route"), "trail_running": ("Course", "Trail"),
        "treadmill_running": ("Course", "Tapis"), "road_biking": ("Vélo", "Route"),
        "mountain_biking": ("Vélo", "VTT"), "indoor_cycling": ("Vélo", "Home trainer"),
        "lap_swimming": ("Natation", "Piscine"), "open_water_swimming": ("Natation", "Eau libre"),
        "walking": ("Marche & rando", "Marche"), "hiking": ("Marche & rando", "Randonnée"),
        "strength_training": ("Renforcement", "Musculation"), "yoga": ("Renforcement", "Yoga"),
        # Types inconnus : motifs « contient » / regex, sinon Autre.
        "virtual_running_x": ("Course", "Route"), "gravel_biking_new": ("Vélo", "Route"),
        "paddleboarding": ("Autre", "Autre"),
    }
    for type_key, (family, name) in cases.items():
        assert clf.classify(fake(type_key))[0] == sport(session, family, name).id, type_key


def test_name_rule_beats_generic_type(session):
    clf = Classifier(session)
    sport_id, source, _ = clf.classify(fake("running", "Trail des Crêtes"))
    assert sport_id == sport(session, "Course", "Trail").id and source == "rule"


def test_manual_lock_survives_reclassify(session):
    yoga = sport(session, "Renforcement", "Yoga")
    a = Activity(garmin_id=1, start=__import__("datetime").datetime(2025, 1, 1, 8), type_key="running", name="x",
                 sport_id=yoga.id, sport_locked=True, sport_source="manual")
    session.add(a)
    reclassify(session)
    assert a.sport_id == yoga.id
    a.sport_locked = False
    reclassify(session)
    assert a.sport_id == sport(session, "Course", "Route").id


def test_learned_rule_wins_over_seed(session):
    yoga = sport(session, "Renforcement", "Yoga")
    learn_rule(session, "type_key", "hiit", yoga)
    assert Classifier(session).classify(fake("hiit"))[0] == yoga.id
    # Une deuxième correction du même type met la règle à jour au lieu d'en créer une autre.
    learn_rule(session, "type_key", "hiit", sport(session, "Autre", "Autre"))
    assert len(session.scalars(select(SportRule).where(SportRule.pattern == "hiit",
                                                        SportRule.origin == "learned")).all()) == 1


def test_validate_and_accents():
    assert validate_rule("name", "regex", "(") .startswith("Expression régulière invalide")
    assert validate_rule("name", "contains", " ") == "Le motif est vide."
    assert validate_rule("type_key", "equals", "running") is None
    rule = SimpleNamespace(field="name", match_type="contains", pattern="Crêtes", id=1, priority=1)
    assert CompiledRule(rule).matches(fake(name="trail des CRETES"))
