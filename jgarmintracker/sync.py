"""Synchronisation : transforme le JSON Garmin en lignes, sans doublon.

Reçoit une « source » (GarminSource en vrai, FakeSource dans les tests) qui expose :
  activities_between(start, end) -> list[dict]
  daily_summary(day) -> dict | None      (FC au repos, Body Battery, pas, stress)
  sleep(day) -> dict | None              (nuit terminée le matin de `day`)
  vo2max(start, end) -> list | dict | None
Clés : identifiant Garmin pour les activités, date pour les jours.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .classifier import Classifier
from .garmin import GarminError, SyncError
from .models import Activity, DailyHealth, SyncRun

DEFAULT_HISTORY_DAYS = 365
RESYNC_DAYS = 3  # Garmin complète les nuits et les résumés après coup

ACTIVITY_FIELDS = ("start", "type_key", "name", "duration_s", "moving_s", "distance_m", "elevation_gain_m",
                   "avg_hr", "max_hr", "avg_speed", "calories", "aerobic_te", "anaerobic_te", "avg_power")
HEALTH_FIELDS = ("resting_hr", "sleep_s", "deep_s", "light_s", "rem_s", "awake_s", "sleep_score", "bb_max",
                 "bb_min", "bb_charged", "bb_drained", "steps", "stress_avg", "stress_max", "vo2max")


# ---------------------------------------------------------------- lecture du JSON Garmin
def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _int(value, allow_negative: bool = False) -> int | None:
    """Garmin met -1 / -2 pour « pas de mesure » (stress) : traités comme absents."""
    v = _num(value)
    if v is None or (v < 0 and not allow_negative):
        return None
    return round(v)


def _local_datetime(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace(" ", "T")).replace(tzinfo=None, microsecond=0)


def parse_activity(raw: dict) -> dict:
    return {
        "garmin_id": int(raw["activityId"]),
        "start": _local_datetime(raw["startTimeLocal"]),
        "type_key": (raw.get("activityType") or {}).get("typeKey") or "",
        "name": raw.get("activityName") or "",
        "duration_s": _num(raw.get("duration")),
        "moving_s": _num(raw.get("movingDuration")),
        "distance_m": _num(raw.get("distance")) or None,
        "elevation_gain_m": _num(raw.get("elevationGain")),
        "avg_hr": _num(raw.get("averageHR")),
        "max_hr": _num(raw.get("maxHR")),
        "avg_speed": _num(raw.get("averageSpeed")) or None,
        "calories": _num(raw.get("calories")),
        "aerobic_te": _num(raw.get("aerobicTrainingEffect")),
        "anaerobic_te": _num(raw.get("anaerobicTrainingEffect")),
        "avg_power": _num(raw.get("avgPower")),
    }


def parse_summary(raw: dict | None) -> dict:
    raw = raw or {}
    return {
        "resting_hr": _int(raw.get("restingHeartRate")) or None,
        "bb_max": _int(raw.get("bodyBatteryHighestValue")),
        "bb_min": _int(raw.get("bodyBatteryLowestValue")),
        "bb_charged": _int(raw.get("bodyBatteryChargedValue")),
        "bb_drained": _int(raw.get("bodyBatteryDrainedValue")),
        "steps": _int(raw.get("totalSteps")),
        "stress_avg": _int(raw.get("averageStressLevel")),
        "stress_max": _int(raw.get("maxStressLevel")),
    }


def parse_sleep(raw: dict | None) -> dict:
    dto = (raw or {}).get("dailySleepDTO") or {}
    total = _int(dto.get("sleepTimeSeconds"))
    if not total:
        return {k: None for k in ("sleep_s", "deep_s", "light_s", "rem_s", "awake_s", "sleep_score")}
    score = (((dto.get("sleepScores") or {}).get("overall") or {}).get("value"))
    return {
        "sleep_s": total,
        "deep_s": _int(dto.get("deepSleepSeconds")),
        "light_s": _int(dto.get("lightSleepSeconds")),
        "rem_s": _int(dto.get("remSleepSeconds")),
        "awake_s": _int(dto.get("awakeSleepSeconds")),
        "sleep_score": _int(score),
    }


def parse_vo2max(raw) -> dict[date, tuple[float, dict]]:
    """Réponse « max metrics » -> {jour: (VO2max, élément brut)}. Valeur course (generic), sinon vélo."""
    items = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    out: dict[date, tuple[float, dict]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("generic", "cycling"):
            block = item.get(key) or {}
            value = _num(block.get("vo2MaxPreciseValue")) or _num(block.get("vo2MaxValue"))
            day = block.get("calendarDate") or item.get("calendarDate")
            if value and day:
                out.setdefault(date.fromisoformat(day[:10]), (round(value, 1), item))
                break
    return out


# ---------------------------------------------------------------- synchronisation
@dataclass
class Progress:
    step: str  # activities | health | done
    done: int = 0
    total: int = 0
    day: date | None = None


ProgressFn = Callable[[Progress], None]


def _upsert_activity(session: Session, raw: dict, clf: Classifier) -> str:
    """Renvoie « added », « updated » ou « same »."""
    data = parse_activity(raw)
    raw_text = json.dumps(raw, ensure_ascii=False, sort_keys=True)
    act = session.scalar(select(Activity).where(Activity.garmin_id == data["garmin_id"]))
    if act is None:
        act = Activity(garmin_id=data["garmin_id"], raw_json=raw_text)
        for k in ACTIVITY_FIELDS:
            setattr(act, k, data[k])
        session.add(act)
        clf.apply(act)
        return "added"
    changed = act.raw_json != raw_text
    if changed:
        for k in ACTIVITY_FIELDS:
            setattr(act, k, data[k])
        act.raw_json, act.synced_at = raw_text, datetime.now()
        clf.apply(act)
    return "updated" if changed else "same"


def _dump(raw) -> str | None:
    return json.dumps(raw, ensure_ascii=False, sort_keys=True) if raw else None


def _upsert_day(session: Session, day: date, summary: dict | None, sleep: dict | None,
                vo2: tuple[float, dict] | None) -> str:
    values = {**parse_summary(summary), **parse_sleep(sleep), "vo2max": vo2[0] if vo2 else None}
    row = session.get(DailyHealth, day)
    if row is None:
        if all(v is None for v in values.values()):
            return "empty"  # jour sans montre : pas de ligne
        row = DailyHealth(day=day)
        session.add(row)
        status = "added"
    else:
        status = "updated"
        if vo2 is None:  # la VO2max n'est demandée que sur la période synchronisée : on garde l'ancienne
            values["vo2max"] = row.vo2max
    for k, v in values.items():
        setattr(row, k, v)
    row.raw_summary, row.raw_sleep = _dump(summary), _dump(sleep)
    if vo2:
        row.raw_vo2max = _dump(vo2[1])
    row.synced_at = datetime.now()
    return status


def _vo2max_map(source, start: date, end: date) -> dict[date, tuple[float, dict]]:
    """Par tranches de 90 jours. Facultatif : une erreur ici ne bloque pas la synchro."""
    out: dict[date, tuple[float, dict]] = {}
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=89), end)
        try:
            out.update(parse_vo2max(source.vo2max(cur, chunk_end)))
        except GarminError:
            pass
        cur = chunk_end + timedelta(days=1)
    return out


def plan(session: Session, today: date, full: bool, days: int, history_days: int) -> tuple[date, date]:
    """Dates de départ (activités, santé). Premier lancement ou --full : tout l'historique demandé."""
    first = today - timedelta(days=history_days - 1)
    resync = today - timedelta(days=max(days, 1) - 1)
    last_act = session.scalar(select(func.max(Activity.start)))
    last_day = session.scalar(select(func.max(DailyHealth.day)))
    act_start = first if full or last_act is None else min(last_act.date() - timedelta(days=1), resync)
    # Santé : reprend après le dernier jour connu (une synchro interrompue repart de là), plus les derniers jours.
    health_start = first if full or last_day is None else min(last_day + timedelta(days=1), resync)
    return max(act_start, first), max(health_start, first)


def sync(session: Session, source, *, today: date | None = None, full: bool = False, days: int = RESYNC_DAYS,
         history_days: int = DEFAULT_HISTORY_DAYS, progress: ProgressFn | None = None) -> SyncRun:
    """Synchronise activités puis santé. Valide jour par jour : une interruption ne perd rien."""
    today = today or date.today()
    notify = progress or (lambda p: None)
    run = SyncRun(mode="full" if full else "incremental")
    session.add(run)
    session.commit()
    try:
        act_start, health_start = plan(session, today, full, days, history_days)

        notify(Progress("activities"))
        clf = Classifier(session)
        raws = source.activities_between(act_start, today)
        for i, raw in enumerate(raws, 1):
            status = _upsert_activity(session, raw, clf)
            run.activities_added += status == "added"
            run.activities_updated += status == "updated"
            notify(Progress("activities", i, len(raws)))
        session.commit()

        span = [health_start + timedelta(days=i) for i in range((today - health_start).days + 1)]
        vo2 = _vo2max_map(source, health_start, today) if span else {}
        pause = getattr(source, "pause", 0)
        for i, d in enumerate(span, 1):
            notify(Progress("health", i - 1, len(span), d))
            status = _upsert_day(session, d, source.daily_summary(d), source.sleep(d), vo2.get(d))
            run.days_added += status == "added"
            run.days_updated += status == "updated"
            session.commit()
            if pause and i < len(span):
                time.sleep(pause)
        run.status = "ok"
        notify(Progress("done", len(span), len(span)))
    except SyncError as e:
        session.rollback()
        run.status, run.message = "error", str(e)
    except Exception as e:
        session.rollback()
        run.status, run.message = "error", f"Erreur inattendue : {e!r}"
        run.finished_at = datetime.now()
        session.merge(run)
        session.commit()
        raise
    run.finished_at = datetime.now()
    session.merge(run)
    session.commit()
    return run


def last_run(session: Session) -> SyncRun | None:
    return session.scalar(select(SyncRun).order_by(SyncRun.id.desc()).limit(1))
