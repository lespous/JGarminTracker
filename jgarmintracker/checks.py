"""Vérifications : repère les activités suspectes (montre prêtée, sport mal classé, saut de GPS).

Trois contrôles, sur les activités non exclues et non marquées « c'est bien moi » :
  - allure impossible : moyenne plus rapide que la limite de la famille de sports ;
  - allure inhabituelle : nettement plus rapide que ta médiane pour le même sport ;
  - pointe aberrante : vitesse max impossible pour la famille (saut de GPS).
Les limites sont réglables par famille dans Paramètres (vitesses en m/s en base).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from . import settings, units
from .models import Activity, Sport, SportFamily

# Limites par défaut, selon le nom de la famille (familles de départ) : (moyenne max, pointe max), en m/s.
DEFAULT_LIMITS = {
    "Course": (1000 / 150, 1000 / 100),  # 2:30 /km de moyenne, 1:40 /km en pointe
    "Marche & rando": (1000 / 300, 1000 / 180),  # 5:00 /km, 3:00 /km
    "Vélo": (60 / 3.6, 100 / 3.6),  # 60 km/h, 100 km/h
    "Natation": (100 / 60, None),  # 1:00 /100 m ; pas de pointe fiable en natation
}
UNUSUAL_PCT = 25  # % plus rapide que la médiane du sport
MIN_HISTORY = 5  # sorties nécessaires pour calculer une médiane fiable


def limits(session: Session) -> dict[int, dict]:
    """{family_id: {"avg": m/s ou None, "max": m/s ou None}} : réglages de Paramètres, sinon défauts par nom."""
    saved = settings.get(session, "check_limits") or {}
    out = {}
    for fam in session.scalars(select(SportFamily)):
        avg, mx = DEFAULT_LIMITS.get(fam.name, (None, None))
        custom = saved.get(str(fam.id)) or {}
        out[fam.id] = {"avg": custom.get("avg", avg), "max": custom.get("max", mx)}
    return out


def family_unit(family: SportFamily) -> str:
    """Unité d'affichage des limites d'une famille : celle de la majorité de ses sports."""
    units_ = [s.pace_unit for s in family.sports if s.pace_unit != "none"]
    return max(set(units_), key=units_.count) if units_ else "none"


def to_display(speed: float | None, unit: str) -> str:
    """m/s -> texte saisissable dans le formulaire (« 2:30 », « 60 »)."""
    if not speed:
        return ""
    if unit == "kmh":
        return units.number(speed * 3.6, 0)
    per = 100 if unit == "min_100m" else 1000
    return units.mmss(per / speed)


def from_display(text: str | None, unit: str) -> float | None:
    """« 2:30 » (allure) ou « 60 » (km/h) -> m/s. Vide -> None (pas de limite). ValueError si illisible."""
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    if unit == "kmh":
        return float(text) / 3.6
    if ":" in text:
        m, s = text.split(":", 1)
        seconds = int(m) * 60 + float(s)
    else:
        seconds = float(text) * 60  # minutes décimales
    if seconds <= 0:
        raise ValueError(text)
    return (100 if unit == "min_100m" else 1000) / seconds


@dataclass
class Finding:
    kind: str  # impossible | unusual | spike
    activity: Activity
    detail: str


def find_issues(session: Session) -> dict[str, list[Finding]]:
    acts = session.scalars(
        select(Activity).options(joinedload(Activity.sport).joinedload(Sport.family))
        .where(Activity.excluded.is_(False)).order_by(Activity.start.desc())
    ).unique().all()
    lim = limits(session)
    pct = settings.get(session, "unusual_pct") or UNUSUAL_PCT

    # Médiane par sport, sur les sorties d'au moins 1 km non exclues (alertes comprises : robuste par nature).
    speeds: dict[int, list[float]] = {}
    for a in acts:
        if a.sport_id and a.avg_speed and (a.distance_m or 0) >= 1000:
            speeds.setdefault(a.sport_id, []).append(a.avg_speed)
    medians = {sid: statistics.median(v) for sid, v in speeds.items() if len(v) >= MIN_HISTORY}

    found: dict[str, list[Finding]] = {"impossible": [], "unusual": [], "spike": []}
    for a in acts:
        if a.review_ok or not a.sport or a.sport.pace_unit == "none":
            continue
        unit = a.sport.pace_unit
        fam_lim = lim.get(a.sport.family_id, {})
        avg_limit, max_limit = fam_lim.get("avg"), fam_lim.get("max")
        if a.avg_speed and avg_limit and a.avg_speed > avg_limit:
            found["impossible"].append(Finding("impossible", a,
                f"{units.pace(a.avg_speed, unit)} de moyenne, limite {units.pace(avg_limit, unit)}"))
        elif a.avg_speed and a.sport_id in medians and (a.distance_m or 0) >= 1000 \
                and a.avg_speed > medians[a.sport_id] * (1 + pct / 100):
            med = medians[a.sport_id]
            found["unusual"].append(Finding("unusual", a,
                f"{units.pace(a.avg_speed, unit)} contre {units.pace(med, unit)} d'habitude "
                f"({round((a.avg_speed / med - 1) * 100)} % plus rapide)"))
        # Pointe : seulement au-delà de la limite absolue de la famille. Un rapport pointe / moyenne élevé est
        # courant sur de vraies sorties (arrêts, fractionné) : testé sur un vrai compte, il donnait trop de fausses alertes.
        if a.max_speed and not a.ignore_max_speed and max_limit and a.max_speed > max_limit:
            found["spike"].append(Finding("spike", a,
                f"pointe à {units.pace(a.max_speed, unit)} pour une moyenne de {units.pace(a.avg_speed, unit)}"))
    return found


def count_issues(session: Session) -> int:
    return len({f.activity.id for items in find_issues(session).values() for f in items})
