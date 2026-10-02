"""Entretien du matériel (0.12.0) : tâches récurrentes (tous les N km et/ou N mois), journal, rappels.

Point de départ d'une tâche : son dernier entretien fait, sinon la mise en service du matériel, sinon la création
de la tâche. Les km comptés sont ceux des sorties faites avec le matériel après ce jour (sorties exclues écartées).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import units
from .models import Activity, Gear, GearService, GearTask, activity_gear

SOON = 0.9  # à 90 % de l'intervalle : « bientôt »
DAYS_PER_MONTH = 30.44

# Suggestions de tâches par type de matériel (saisie libre quand même).
SUGGESTIONS: dict[str, list[tuple[str, float | None, int | None]]] = {
    "bike": [("Chaîne", 3000, None), ("Pneus", 4000, None), ("Plaquettes de frein", 2500, None),
             ("Cassette", 9000, None), ("Révision complète", None, 12), ("Graissage chaîne", 300, None)],
    "shoes": [("Remplacement", 800, None)],
    "other": [("Révision", None, 12)],
}


def km_after(session: Session, gear_id: int, after: date | None, until: date | None = None) -> float:
    """Km des sorties faites avec ce matériel après le jour `after` (exclu), jusqu'à `until` inclus."""
    stmt = (select(func.coalesce(func.sum(Activity.distance_m), 0.0))
            .join(activity_gear, activity_gear.c.activity_id == Activity.id)
            .where(activity_gear.c.gear_id == gear_id, Activity.excluded.is_(False)))
    if after:
        stmt = stmt.where(Activity.start >= datetime.combine(after + timedelta(days=1), datetime.min.time()))
    if until:
        stmt = stmt.where(Activity.start < datetime.combine(until + timedelta(days=1), datetime.min.time()))
    return (session.scalar(stmt) or 0) / 1000


@dataclass
class TaskStatus:
    task: GearTask
    last: GearService | None
    since: date  # point de départ
    km: float  # km depuis
    months: float  # mois depuis
    ratio: float | None  # le plus avancé des deux intervalles ; None sans intervalle

    @property
    def due(self) -> bool:
        return self.ratio is not None and self.ratio >= 1

    @property
    def soon(self) -> bool:
        return self.ratio is not None and SOON <= self.ratio < 1

    @property
    def text(self) -> str:
        """« dans 340 km », « dans 2 mois », « en retard de 120 km », « en retard de 3 semaines »."""
        t = self.task
        parts = []
        if t.every_km:
            left = t.every_km - self.km
            parts.append((left / t.every_km, f"{units.number(abs(left))} km"))
        if t.every_months:
            left_days = t.every_months * DAYS_PER_MONTH - self.months * DAYS_PER_MONTH
            parts.append((left_days / (t.every_months * DAYS_PER_MONTH), duration_text(abs(left_days))))
        if not parts:
            return "pas d'intervalle"
        ratio_left, text = min(parts)  # l'intervalle le plus proche décide
        return f"en retard de {text}" if ratio_left <= 0 else f"dans {text}"


def duration_text(days: float) -> str:
    days = round(days)
    if days < 14:
        return f"{days} jour{'s' if days > 1 else ''}"
    if days < 60:
        return f"{round(days / 7)} semaines"
    return f"{round(days / DAYS_PER_MONTH)} mois"


def status(session: Session, task: GearTask, today: date) -> TaskStatus:
    last = session.scalar(select(GearService).where(GearService.task_id == task.id)
                          .order_by(GearService.day.desc(), GearService.id.desc()).limit(1))
    since = last.day if last else (task.gear.since or task.created_at.date())
    km = km_after(session, task.gear_id, since, today)
    months = max((today - since).days, 0) / DAYS_PER_MONTH
    ratios = [r for r in (km / task.every_km if task.every_km else None,
                          months / task.every_months if task.every_months else None) if r is not None]
    return TaskStatus(task, last, since, km, months, max(ratios) if ratios else None)


def gear_status(session: Session, g: Gear, today: date) -> list[TaskStatus]:
    return [status(session, t, today) for t in g.tasks]


def due(session: Session, today: date) -> list[TaskStatus]:
    """Entretiens dus du matériel en service, les plus en retard d'abord."""
    tasks = session.scalars(select(GearTask).join(Gear).where(Gear.retired.is_(None))).all()
    out = [st for st in (status(session, t, today) for t in tasks) if st.due]
    return sorted(out, key=lambda st: -(st.ratio or 0))


def mark_done(session: Session, task: GearTask, day: date, cost: float | None = None, note: str = "") -> GearService:
    total = km_after(session, task.gear_id, None, day)
    svc = GearService(gear_id=task.gear_id, task_id=task.id, name=task.name, day=day, km=round(total, 1),
                      cost=cost, note=note)
    session.add(svc)
    return svc


def delete_task(session: Session, task: GearTask) -> None:
    """Le journal garde les entretiens faits : SQLAlchemy vide leur task_id (pas de cascade sur services)."""
    task.gear.tasks.remove(task)
    session.delete(task)
