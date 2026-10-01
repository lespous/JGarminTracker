"""Mises à jour des données d'une base existante (nouveaux sports, nouvelles règles, nouveaux champs…).

Chaque mise à jour est idempotente et n'est appliquée qu'une fois par base : si tu supprimes ensuite
un sport qu'elle a créé, il ne revient pas. Ajoute ici des couples (nom, fonction(session)).
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Activity, AppliedUpgrade


def upgrade_activity_extras(session: Session) -> None:
    """0.2.0 : remplit vitesse max, D−, zones cardio, cadence, meilleurs temps… depuis le JSON déjà en base."""
    from .sync import parse_activity_extras

    for act in session.scalars(select(Activity)):
        try:
            raw = json.loads(act.raw_json or "{}")
        except ValueError:
            continue
        for key, value in parse_activity_extras(raw).items():
            setattr(act, key, value)
    session.flush()


UPGRADES: list = [
    ("2026-10-activity-extras", upgrade_activity_extras),
]


def run_upgrades(session: Session) -> list[str]:
    """Applique les mises à jour pas encore faites sur cette base. Renvoie leurs noms."""
    done = set(session.scalars(select(AppliedUpgrade.name)))
    applied = []
    for name, upgrade in UPGRADES:
        if name not in done:
            upgrade(session)
            session.add(AppliedUpgrade(name=name))
            applied.append(name)
    return applied
