"""Suivi du poids : pesées, IMC, moyenne glissante, rappel de pesée."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import settings
from .models import Profile, WeightEntry

MIN_KG, MAX_KG = 25, 300
ROLLING = 7  # moyenne sur les 7 dernières pesées (pas 7 jours : on ne se pèse pas tous les jours)


def bmi(weight_kg: float | None, height_cm: float | None) -> float | None:
    if not weight_kg or not height_cm:
        return None
    return round(weight_kg / (height_cm / 100) ** 2, 1)


def add(session: Session, day: date, kg: float) -> WeightEntry:
    """Enregistre la pesée du jour (remplace celle déjà saisie ce jour-là) et met à jour le poids du profil."""
    if not MIN_KG <= kg <= MAX_KG:
        raise ValueError(f"Poids attendu entre {MIN_KG} et {MAX_KG} kg.")
    entry = session.get(WeightEntry, day)
    if entry is None:
        entry = WeightEntry(day=day, weight_kg=round(kg, 1))
        session.add(entry)
    else:
        entry.weight_kg = round(kg, 1)
    session.flush()
    sync_profile(session)
    return entry


def sync_profile(session: Session) -> None:
    """Le poids du profil suit la dernière pesée (sert à l'IMC et aux repères)."""
    last = latest(session)
    prof = session.get(Profile, 1)
    if last and prof is not None:
        prof.weight_kg = last.weight_kg
    elif last:
        session.add(Profile(id=1, weight_kg=last.weight_kg))


def latest(session: Session) -> WeightEntry | None:
    return session.scalar(select(WeightEntry).order_by(WeightEntry.day.desc()).limit(1))


@dataclass
class Reminder:
    due: bool
    days_since: int | None  # None : jamais pesé
    every: int


def reminder(session: Session, today: date) -> Reminder:
    every = int(settings.get(session, "weight_reminder_days") or 0)
    last = latest(session)
    days_since = (today - last.day).days if last else None
    due = every > 0 and (days_since is None or days_since >= every)
    return Reminder(due, days_since, every)


def series(session: Session, start: date, end: date, height_cm: float | None) -> dict:
    """Pesées de la période, moyenne sur les ROLLING dernières pesées (y compris celles d'avant la période), IMC."""
    rows = session.scalars(select(WeightEntry).where(WeightEntry.day <= end).order_by(WeightEntry.day)).all()
    out = {"labels": [], "weight": [], "avg": [], "bmi": []}
    for i, r in enumerate(rows):
        if r.day < start:
            continue
        window = [x.weight_kg for x in rows[max(0, i - ROLLING + 1): i + 1]]
        out["labels"].append(r.day.strftime("%d/%m/%y"))
        out["weight"].append(r.weight_kg)
        out["avg"].append(round(sum(window) / len(window), 2) if len(window) >= 3 else None)
        out["bmi"].append(bmi(r.weight_kg, height_cm))
    return out


@dataclass
class Summary:
    last: WeightEntry | None
    first_in_period: WeightEntry | None
    change: float | None  # kg sur la période (dernière − première pesée de la période)
    bmi: float | None
    goal: float | None
    to_goal: float | None  # kg restants (négatif = à perdre)
    count: int


def summary(session: Session, start: date, end: date, height_cm: float | None) -> Summary:
    rows = session.scalars(select(WeightEntry).where(WeightEntry.day >= start, WeightEntry.day <= end)
                           .order_by(WeightEntry.day)).all()
    last = latest(session)
    goal = settings.get(session, "weight_goal")
    change = round(rows[-1].weight_kg - rows[0].weight_kg, 1) if len(rows) >= 2 else None
    return Summary(last, rows[0] if rows else None, change, bmi(last.weight_kg, height_cm) if last else None,
                   goal, round(goal - last.weight_kg, 1) if goal and last else None, len(rows))


def bmi_label(value: float | None) -> str:
    """Catégories de l'OMS, pour un repère rapide."""
    if value is None:
        return ""
    if value < 18.5:
        return "maigreur"
    if value < 25:
        return "corpulence normale"
    if value < 30:
        return "surpoids"
    return "obésité"
