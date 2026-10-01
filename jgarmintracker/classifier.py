"""Attribution du sport : règles par priorité, sinon le sport « Autre ». Une correction manuelle est verrouillée."""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Activity, Sport, SportRule

FIELDS = {
    "type_key": "Type Garmin",
    "name": "Nom de l'activité",
}
MATCH_TYPES = {
    "equals": "est égal à",
    "contains": "contient",
    "regex": "expression régulière",
}

# Une règle apprise d'une correction passe avant les règles de départ ; une règle manuelle avant les deux.
PRIORITY_SEED = 100
PRIORITY_LEARNED = 200
PRIORITY_MANUAL = 300


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def fold(text: str | None) -> str:
    """Minuscules, sans accents, espaces simplifiés : base de toutes les comparaisons."""
    return " ".join(strip_accents(text or "").lower().split())


def field_text(activity, field: str) -> str:
    if field == "type_key":
        return fold(activity.type_key)
    if field == "name":
        return fold(activity.name)
    raise ValueError(f"champ inconnu : {field}")


def validate_rule(field: str, match_type: str, pattern: str) -> str | None:
    """Renvoie un message d'erreur, ou None si la règle est valide."""
    if field not in FIELDS:
        return "Champ inconnu."
    if match_type not in MATCH_TYPES:
        return "Type de correspondance inconnu."
    if not (pattern or "").strip():
        return "Le motif est vide."
    if match_type == "regex":
        try:
            re.compile(strip_accents(pattern), re.IGNORECASE)
        except re.error as e:
            return f"Expression régulière invalide : {e}"
    return None


class CompiledRule:
    """Accepte une SportRule ou tout objet ayant les mêmes attributs (test d'une règle non enregistrée)."""

    def __init__(self, rule):
        self.rule = rule
        self.rx = None
        self.pattern = fold(rule.pattern)
        if rule.match_type == "regex":
            try:
                self.rx = re.compile(strip_accents(rule.pattern), re.IGNORECASE)
            except re.error:
                self.pattern = None

    def matches(self, activity) -> bool:
        if not self.pattern:
            return False
        text = field_text(activity, self.rule.field)
        match self.rule.match_type:
            case "equals":
                return text == self.pattern
            case "contains":
                return self.pattern in text
            case "regex":
                return bool(self.rx.search(text))
        return False


def compile_rules(rules) -> list[CompiledRule]:
    """Priorité la plus haute d'abord ; à égalité, le motif le plus long."""
    return sorted((CompiledRule(r) for r in rules),
                  key=lambda c: (-c.rule.priority, -len(c.rule.pattern), c.rule.id or 0))


def fallback_sport(session: Session) -> Sport:
    sport = session.scalar(select(Sport).where(Sport.fallback).order_by(Sport.id))
    if sport is None:
        raise RuntimeError("sport par défaut « Autre » manquant")
    return sport


class Classifier:
    def __init__(self, session: Session):
        self.rules = compile_rules(session.scalars(select(SportRule).where(SportRule.enabled)).all())
        self.fallback_id = fallback_sport(session).id

    def classify(self, activity) -> tuple[int, str, int | None]:
        for c in self.rules:
            if c.matches(activity):
                return c.rule.sport_id, "rule", c.rule.id
        return self.fallback_id, "fallback", None

    def apply(self, activity: Activity) -> bool:
        """Attribue le sport (sauf verrou). Renvoie True si le sport change."""
        if activity.sport_locked:
            return False
        sport_id, source, rule_id = self.classify(activity)
        changed = activity.sport_id != sport_id
        activity.sport_id, activity.sport_source, activity.rule_id = sport_id, source, rule_id
        return changed


def reclassify(session: Session) -> int:
    """Réapplique les règles à toutes les activités non verrouillées. Renvoie le nombre de changements."""
    session.flush()
    clf = Classifier(session)
    return sum(clf.apply(a) for a in session.scalars(select(Activity)))


def learn_rule(session: Session, field: str, value: str, sport: Sport) -> SportRule:
    """Règle apprise « champ = valeur » vers sport ; met à jour celle qui existe déjà."""
    rule = session.scalar(select(SportRule).where(
        SportRule.field == field, SportRule.match_type == "equals", SportRule.pattern == value,
        SportRule.origin == "learned",
    ))
    if rule:
        rule.sport_id, rule.enabled = sport.id, True
    else:
        rule = SportRule(field=field, match_type="equals", pattern=value, sport_id=sport.id,
                         priority=PRIORITY_LEARNED, origin="learned")
        session.add(rule)
    session.flush()
    return rule
