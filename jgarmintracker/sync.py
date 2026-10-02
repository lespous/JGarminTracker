"""Synchronisation : transforme le JSON Garmin en lignes, sans doublon.

Reçoit une « source » (GarminSource en vrai, FakeSource dans les tests) qui expose :
  activities_between(start, end) -> list[dict]
  daily_summary(day) -> dict | None      (FC au repos, Body Battery, pas, stress)
  sleep(day) -> dict | None              (nuit terminée le matin de `day`)
  vo2max(start, end) -> list | dict | None
  track(garmin_id) -> dict | None       (détails de l'activité, dont le tracé GPS)
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

from . import gear, routes, segments, tracks, weather
from .classifier import Classifier
from .garmin import GarminError, SyncError
from .models import Activity, ActivityTrack, DailyHealth, Segment, SyncRun

DEFAULT_HISTORY_DAYS = 365
RESYNC_DAYS = 3  # Garmin complète les nuits et les résumés après coup

EXTRA_FIELDS = ("max_speed", "elevation_loss_m", "min_elevation_m", "max_elevation_m", "elapsed_s", "lap_count",
                "hr_zone_1", "hr_zone_2", "hr_zone_3", "hr_zone_4", "hr_zone_5", "cadence_avg", "cadence_max",
                "stride_cm", "steps", "fastest_1k_s", "fastest_mile_s", "fastest_5k_s", "fastest_40k_s", "water_ml",
                "vo2max", "is_pr")
ACTIVITY_FIELDS = ("start", "type_key", "name", "duration_s", "moving_s", "distance_m", "elevation_gain_m",
                   "avg_hr", "max_hr", "avg_speed", "calories", "aerobic_te", "anaerobic_te", "avg_power") + EXTRA_FIELDS
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
        **parse_activity_extras(raw),
    }


def parse_activity_extras(raw: dict) -> dict:
    """Détails ajoutés en 0.2.0. Unités vérifiées sur de vraies sorties : m/s, m, s, cm (foulée), ml (eau)."""
    cadence = _num(raw.get("averageRunningCadenceInStepsPerMinute"))
    return {
        "max_speed": _num(raw.get("maxSpeed")) or None,
        "elevation_loss_m": _num(raw.get("elevationLoss")),
        "min_elevation_m": _num(raw.get("minElevation")),
        "max_elevation_m": _num(raw.get("maxElevation")),
        "elapsed_s": _num(raw.get("elapsedDuration")),
        "lap_count": _int(raw.get("lapCount")),
        **{f"hr_zone_{i}": _num(raw.get(f"hrTimeInZone_{i}")) for i in range(1, 6)},
        "cadence_avg": cadence or None,
        "cadence_max": (_num(raw.get("maxRunningCadenceInStepsPerMinute")) or None) if cadence else None,
        "stride_cm": _num(raw.get("avgStrideLength")) or None,
        "steps": _int(raw.get("steps")) or None,
        "fastest_1k_s": _num(raw.get("fastestSplit_1000")) or None,
        "fastest_mile_s": _num(raw.get("fastestSplit_1609")) or None,
        "fastest_5k_s": _num(raw.get("fastestSplit_5000")) or None,
        "fastest_40k_s": _num(raw.get("fastestSplit_40000")) or None,
        "water_ml": _num(raw.get("waterEstimated")) or None,
        "vo2max": _num(raw.get("vO2MaxValue")) or None,
        "is_pr": bool(raw.get("pr") or raw.get("isPR")),
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
        gear.apply_defaults(session, act)
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


def missing_tracks(session: Session) -> list[Activity]:
    """Activités avec un tracé chez Garmin mais pas encore demandé, plus récentes d'abord."""
    stmt = (select(Activity).outerjoin(ActivityTrack, ActivityTrack.activity_id == Activity.id)
            .where(ActivityTrack.activity_id.is_(None)).order_by(Activity.start.desc()))
    return [a for a in session.scalars(stmt) if tracks.has_track(json.loads(a.raw_json or "{}"))]


def save_track(session: Session, act: Activity, details: dict | None) -> bool:
    """Enregistre le tracé (ou son absence, pour ne pas le redemander). Renvoie True s'il y a des points."""
    points = tracks.parse_track(details)
    session.add(ActivityTrack(activity_id=act.id, points_json=tracks.dumps(points), n_points=len(points),
                              preview_path=tracks.preview_path(points)))
    return bool(points)


def fetch_weather(session: Session, source, todo: list[Activity], notify, pause: float = 0) -> int:
    """Météo de chaque sortie de la liste (une demande par sortie, validée une à une). Renvoie le nombre reçu."""
    if not hasattr(source, "weather"):
        return 0
    got = 0
    for i, act in enumerate(todo, 1):
        notify(Progress("weather", i - 1, len(todo), act.day))
        try:
            raw = source.weather(act.garmin_id)
        except SyncError:
            break  # facultatif : la suite viendra à la prochaine synchro, sans mettre la synchro en erreur
        got += weather.save(session, act, raw)
        session.commit()
        if pause and i < len(todo):
            time.sleep(pause)
    return got


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

        # Tracés GPS en dernier : un blocage ici ne retarde pas la santé. Une interruption reprend au suivant.
        todo = missing_tracks(session) if hasattr(source, "track") else []
        for i, act in enumerate(todo, 1):
            notify(Progress("tracks", i - 1, len(todo), act.day))
            run.tracks_added += save_track(session, act, source.track(act.garmin_id))
            session.commit()
            if pause and i < len(todo):
                time.sleep(pause)
        if run.tracks_added:
            routes.rebuild(session)  # nouveaux tracés : parcours répétés à recalculer
            session.commit()

        # Météo au départ, en dernier : l'historique se complète petit à petit, plus récentes d'abord.
        fetch_weather(session, source, weather.missing(session), notify, pause)

        # Segments : nouvelles sorties qui les empruntent (et téléchargements restés en attente).
        if session.scalar(select(func.count(Segment.id))):
            segments.refresh(session, source, notify=notify)
            session.commit()
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


def sync_history(session: Session, source, start: date, end: date, *, activities: bool = True, health: bool = True,
                 skip_existing: bool = True, progress: ProgressFn | None = None) -> SyncRun:
    """Récupère une période passée (page Historique). Les jours déjà en base sont sautés : une récupération
    interrompue (erreur 429) se relance telle quelle et reprend où elle s'était arrêtée."""
    notify = progress or (lambda p: None)
    what = " + ".join(w for w, on in (("activités et tracés", activities), ("santé", health)) if on)
    run = SyncRun(mode="history", message=f"Historique du {start:%d/%m/%Y} au {end:%d/%m/%Y} : {what}.")
    session.add(run)
    session.commit()
    pause = getattr(source, "pause", 0)
    try:
        if activities:
            notify(Progress("activities"))
            clf = Classifier(session)
            raws = source.activities_between(start, end)
            for i, raw in enumerate(raws, 1):
                status = _upsert_activity(session, raw, clf)
                run.activities_added += status == "added"
                run.activities_updated += status == "updated"
                notify(Progress("activities", i, len(raws)))
            session.commit()

        if health:
            known = set(session.scalars(select(DailyHealth.day).where(DailyHealth.day >= start, DailyHealth.day <= end)))
            span = [start + timedelta(days=i) for i in range((end - start).days + 1)]
            if skip_existing:
                span = [d for d in span if d not in known]
            vo2 = _vo2max_map(source, start, end) if span else {}
            for i, d in enumerate(span, 1):
                notify(Progress("health", i - 1, len(span), d))
                status = _upsert_day(session, d, source.daily_summary(d), source.sleep(d), vo2.get(d))
                run.days_added += status == "added"
                run.days_updated += status == "updated"
                session.commit()
                if pause and i < len(span):
                    time.sleep(pause)

        if activities and hasattr(source, "track"):
            lo, hi = datetime.combine(start, datetime.min.time()), datetime.combine(end + timedelta(days=1), datetime.min.time())
            todo = [a for a in missing_tracks(session) if lo <= a.start < hi]
            for i, act in enumerate(todo, 1):
                notify(Progress("tracks", i - 1, len(todo), act.day))
                run.tracks_added += save_track(session, act, source.track(act.garmin_id))
                session.commit()
                if pause and i < len(todo):
                    time.sleep(pause)
            if run.tracks_added:
                routes.rebuild(session)
                session.commit()
            fetch_weather(session, source, [a for a in weather.missing(session) if lo <= a.start < hi], notify, pause)
        run.status = "ok"
        notify(Progress("done"))
    except SyncError as e:
        session.rollback()
        run.status, run.message = "error", f"{run.message} {e}"
    run.finished_at = datetime.now()
    session.merge(run)
    session.commit()
    return run


def estimate_seconds(days: int, activities: int = 0) -> int:
    """Durée probable d'une récupération : ~0,9 s par jour de santé, ~0,7 s par tracé (mesuré sur un vrai compte)."""
    return round(days * 0.9 + activities * 0.7 + 5)


def last_run(session: Session) -> SyncRun | None:
    """Dernière synchro (les analyses de segments, lancées à part, ne comptent pas)."""
    return session.scalar(select(SyncRun).where(SyncRun.mode != "segments").order_by(SyncRun.id.desc()).limit(1))
