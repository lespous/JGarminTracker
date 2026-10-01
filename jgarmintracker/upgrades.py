"""Mises à jour des données d'une base existante (nouveaux sports, nouvelles règles…).

Chaque mise à jour est idempotente et n'est appliquée qu'une fois par base : si tu supprimes ensuite
un sport qu'elle a créé, il ne revient pas. Ajoute ici des couples (nom, fonction(session)).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AppliedUpgrade

UPGRADES: list = []


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
