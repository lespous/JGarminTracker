"""Objectifs (0.12.0) : progression de la période en cours, avance ou retard sur le rythme, périodes passées.

Les activités exclues des statistiques ne comptent pas, comme partout ailleurs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

from . import units
from .models import Activity, Goal, Sport, SportFamily
from .stats import activities_between, add_months, week_start

# metric -> (libellé, unité courte pour la saisie)
METRICS: dict[str, tuple[str, str]] = {
    "distance": ("Distance", "km"),
    "duration": ("Durée", "h"),
    "count": ("Sorties", "sorties"),
    "elevation": ("Dénivelé +", "m"),
}
PERIODS: dict[str, tuple[str, str]] = {  # period -> (« par semaine », « cette semaine »)
    "week": ("par semaine", "cette semaine"),
    "month": ("par mois", "ce mois-ci"),
    "year": ("par année", "cette année"),
}
HISTORY = {"week": 8, "month": 6, "year": 3}  # périodes passées montrées


def bounds(period: str, day: date) -> tuple[date, date]:
    """Période (semaine ISO, mois civil, année civile) contenant day."""
    if period == "week":
        start = week_start(day)
        return start, start + timedelta(days=6)
    if period == "month":
        start = day.replace(day=1)
        return start, add_months(start, 1) - timedelta(days=1)
    return date(day.year, 1, 1), date(day.year, 12, 31)


def previous(period: str, start: date) -> tuple[date, date]:
    return bounds(period, start - timedelta(days=1))


def measure(acts: list[Activity], metric: str) -> float:
    """Valeur dans l'unité de l'objectif."""
    if metric == "distance":
        return sum(a.distance_m or 0 for a in acts) / 1000
    if metric == "duration":
        return sum(a.duration_s or 0 for a in acts) / 3600
    if metric == "elevation":
        return sum(a.elevation_gain_m or 0 for a in acts)
    return float(len(acts))


def fmt(metric: str, value: float | None) -> str:
    """« 1 234 km », « 12h30 », « 3 sorties », « 2 400 m »."""
    if value is None:
        return units.DASH
    if metric == "distance":
        return f"{units.number(value, 1 if abs(value) < 100 else 0)} km"
    if metric == "duration":
        return units.hmm(value * 3600)
    if metric == "elevation":
        return units.meters(value)
    n = round(value, 1)
    text = units.number(n, 0 if n == int(n) else 1)
    return f"{text} sortie{'s' if abs(n) >= 2 else ''}"


def scope_of(session: Session, scope: str) -> tuple[str, list[int] | None]:
    """« fN » / « sN » / « » -> (libellé, ids des sports ou None pour tout)."""
    if scope[:1] in ("f", "s") and scope[1:].isdigit():
        if scope[0] == "f" and (fam := session.get(SportFamily, int(scope[1:]))):
            return fam.name, [sp.id for sp in fam.sports]
        if scope[0] == "s" and (sp := session.get(Sport, int(scope[1:]))):
            return sp.label, [sp.id]
        return "Sport supprimé", []
    return "Tous les sports", None


@dataclass
class PastPeriod:
    start: date
    end: date
    value: float
    hit: bool


@dataclass
class Progress:
    goal: Goal
    scope_label: str
    start: date
    end: date
    value: float
    expected: float  # où il faudrait en être aujourd'hui au rythme régulier
    days_left: int  # aujourd'hui compris
    history: list[PastPeriod] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        return self.value / self.goal.target if self.goal.target else 0

    @property
    def expected_ratio(self) -> float:
        return self.expected / self.goal.target if self.goal.target else 0

    @property
    def done(self) -> bool:
        return self.value >= self.goal.target

    @property
    def gap(self) -> float:
        """Positif : en avance sur le rythme ; négatif : en retard."""
        return self.value - self.expected

    @property
    def remaining(self) -> float:
        return max(self.goal.target - self.value, 0)

    @property
    def per_week(self) -> float | None:
        """Reste à faire par semaine (objectifs au mois ou à l'année)."""
        if self.goal.period == "week" or self.done or self.days_left <= 0:
            return None
        return self.remaining / max(self.days_left / 7, 1)

    @property
    def hits(self) -> int:
        return sum(p.hit for p in self.history)

    def text(self, value: float | None) -> str:
        return fmt(self.goal.metric, value)


def progress(session: Session, goal: Goal, today: date) -> Progress:
    label, sport_ids = scope_of(session, goal.scope)
    start, end = bounds(goal.period, today)
    acts = activities_between(session, start, today, sport_ids) if sport_ids != [] else []
    value = measure(acts, goal.metric)
    total_days = (end - start).days + 1
    elapsed = (today - start).days + 1
    history = []
    p_start = start
    for _ in range(HISTORY[goal.period]):
        p_start, p_end = previous(goal.period, p_start)
        acts = activities_between(session, p_start, p_end, sport_ids) if sport_ids != [] else []
        v = measure(acts, goal.metric)
        history.append(PastPeriod(p_start, p_end, v, v >= goal.target))
    history.reverse()  # plus ancienne d'abord
    return Progress(goal, label, start, end, value, goal.target * elapsed / total_days, total_days - elapsed + 1,
                    history)


def all_progress(session: Session, today: date) -> list[Progress]:
    from sqlalchemy import select

    goals = session.scalars(select(Goal).order_by(Goal.position, Goal.id)).all()
    return [progress(session, g, today) for g in goals]


def title(goal: Goal, scope_label: str) -> str:
    """« 1 500 km de Vélo par année »."""
    what = fmt(goal.metric, goal.target)
    where = "" if scope_label == "Tous les sports" else f" · {scope_label}"
    return f"{what} {PERIODS[goal.period][0]}{where}"
