"""Matériel (0.11.0) : affectation aux sorties, matériel par défaut d'un sport, usure.

Règle : une sortie porte au plus un matériel de chaque type (un vélo, une paire de chaussures, un « autre »).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Activity, Gear

# type -> (libellé, icône par défaut, couleur par défaut)
KINDS: dict[str, tuple[str, str, str]] = {
    "bike": ("Vélo", "bicycle", "#2E86DE"),
    "shoes": ("Chaussures", "sneaker-move", "#E4572E"),
    "other": ("Autre", "backpack", "#8E6CC9"),
}
# Icônes proposées pour un matériel (toutes déclarées dans icons.css).
ICONS = ["bicycle", "mountains", "scooter", "timer", "sneaker-move", "sneaker", "boot", "backpack", "watch",
         "person-simple-ski", "racquet", "sailboat", "wrench", "package"]
WEAR_WARN = 0.9  # à 90 % du kilométrage maximal, la carte passe en alerte


def kind_label(kind: str) -> str:
    return KINDS.get(kind, KINDS["other"])[0]


def icon_of(g: Gear) -> str:
    return g.icon or KINDS.get(g.kind, KINDS["other"])[1]


@dataclass
class Wear:
    km: float
    max_km: float | None
    ratio: float | None  # 0..1+ ; None sans maximum

    @property
    def warn(self) -> bool:
        return self.ratio is not None and self.ratio >= WEAR_WARN

    @property
    def worn(self) -> bool:
        return self.ratio is not None and self.ratio >= 1


def wear(g: Gear, distance_m: float) -> Wear:
    km = distance_m / 1000
    return Wear(km, g.max_km, km / g.max_km if g.max_km else None)


def cost_per_km(g: Gear, distance_m: float) -> float | None:
    return g.price / (distance_m / 1000) if g.price and distance_m >= 1000 else None


@dataclass
class AssignResult:
    added: int = 0  # sorties qui n'avaient pas de matériel de ce type
    replaced: int = 0  # un autre matériel du même type a été remplacé
    kept: int = 0  # un autre matériel du même type a été gardé (remplacement refusé)
    already: int = 0  # avaient déjà ce matériel

    @property
    def changed(self) -> int:
        return self.added + self.replaced


def same_kind(act: Activity, g: Gear) -> list[Gear]:
    return [x for x in act.gear if x.kind == g.kind and x.id != g.id]


def plan_assign(acts: list[Activity], g: Gear, replace: bool) -> AssignResult:
    """Ce que ferait assign, sans rien changer (aperçu)."""
    r = AssignResult()
    for act in acts:
        if g in act.gear:
            r.already += 1
        elif same_kind(act, g):
            if replace:
                r.replaced += 1
            else:
                r.kept += 1
        else:
            r.added += 1
    return r


def assign(acts: list[Activity], g: Gear, replace: bool = True) -> AssignResult:
    r = plan_assign(acts, g, replace)
    for act in acts:
        if g in act.gear:
            continue
        others = same_kind(act, g)
        if others and not replace:
            continue
        for x in others:
            act.gear.remove(x)
        act.gear.append(g)
    return r


def set_kind(act: Activity, kind: str, g: Gear | None) -> None:
    """Fiche d'une sortie : le matériel de ce type devient g (ou aucun)."""
    for x in [x for x in act.gear if x.kind == kind]:
        act.gear.remove(x)
    if g is not None:
        act.gear.append(g)


def candidates(session: Session, sport_ids: list[int], start: date | None, end: date | None) -> list[Activity]:
    """Sorties des sports donnés entre deux dates (incluses), les plus récentes d'abord."""
    if not sport_ids:
        return []
    stmt = select(Activity).where(Activity.sport_id.in_(sport_ids))
    if start:
        stmt = stmt.where(Activity.start >= datetime.combine(start, datetime.min.time()))
    if end:
        stmt = stmt.where(Activity.start < datetime.combine(end + timedelta(days=1), datetime.min.time()))
    return list(session.scalars(stmt.order_by(Activity.start.desc())))


def make_default(session: Session, g: Gear, sport_ids: list[int]) -> None:
    """g devient le matériel par défaut de ces sports ; un autre matériel du même type perd ces sports."""
    from .models import Sport

    sports = list(session.scalars(select(Sport).where(Sport.id.in_(sport_ids)))) if sport_ids else []
    for other in session.scalars(select(Gear).where(Gear.kind == g.kind, Gear.id != g.id)):
        other.default_sports = [sp for sp in other.default_sports if sp.id not in sport_ids]
    g.default_sports = list({sp.id: sp for sp in [*g.default_sports, *sports]}.values())


def default_for(session: Session, act: Activity) -> list[Gear]:
    """Matériel par défaut du sport de la sortie, en service ce jour-là : un par type, le plus récent d'abord."""
    if act.sport_id is None:
        return []
    out: dict[str, Gear] = {}
    rows = session.scalars(select(Gear).where(Gear.default_sports.any(id=act.sport_id)))
    for g in sorted(rows, key=lambda x: x.since or date.min, reverse=True):
        if g.kind not in out and g.in_service(act.day):
            out[g.kind] = g
    return list(out.values())


def apply_defaults(session: Session, act: Activity) -> int:
    """Nouvelle sortie synchronisée : reçoit le matériel par défaut de son sport (sans écraser un type déjà posé)."""
    n = 0
    for g in default_for(session, act):
        if not any(x.kind == g.kind for x in act.gear):
            act.gear.append(g)
            n += 1
    return n
