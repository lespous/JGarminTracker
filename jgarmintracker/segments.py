"""Segments (0.14.0) : portions de parcours chronométrées sur toutes les sorties qui les empruntent.

1. Repérage, sans appel Garmin : les tracés déjà en base disent quelles sorties passent par le segment, dans le
   même sens (départ puis arrivée du segment, et tout le chemin du segment longé à moins de 50 m).
2. Chronométrage : pour ces sorties seulement, les données point par point (temps, position, distance, FC,
   altitude) sont téléchargées une fois (ActivityStream), puis le passage est mesuré entre les points les plus
   proches du départ et de l'arrivée du segment.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from . import tracks
from .models import Activity, ActivityStream, ActivityTrack, Segment, SegmentEffort, Sport

NEAR_END_M = 60  # départ / arrivée du segment : point de la sortie à moins de 60 m
NEAR_PATH_M = 50  # chaque point du segment doit être longé à moins de 50 m
LENGTH_GAP = 0.2  # longueur parcourue entre départ et arrivée : ±20 % de celle du segment (pas de détour)
SEG_SAMPLES = 30
MIN_SEGMENT_M = 100


# ---------------------------------------------------------------- géométrie
class Projector:
    """Projection locale en mètres (équirectangulaire), précise à l'échelle d'une sortie."""

    def __init__(self, lat0: float):
        self.kx = math.cos(math.radians(lat0)) * 111_320
        self.ky = 110_540

    def xy(self, p) -> tuple[float, float]:
        return p[1] * self.kx, p[0] * self.ky


def _d(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def length(xy: list[tuple[float, float]]) -> float:
    return sum(_d(a, b) for a, b in zip(xy, xy[1:]))


def _resample(xy, n):
    from .routes import resample

    return resample(xy, n)


@dataclass
class Shape:
    """Segment prêt pour la recherche."""
    proj: Projector
    xy: list[tuple[float, float]]
    samples: list[tuple[float, float]]
    distance: float
    bbox: tuple[float, float, float, float]  # en mètres, élargie de NEAR_END_M

    @classmethod
    def of(cls, points: list[tracks.Point]) -> Shape:
        proj = Projector(points[0][0])
        xy = [proj.xy(p) for p in points]
        xs, ys = [p[0] for p in xy], [p[1] for p in xy]
        m = NEAR_END_M
        return cls(proj, xy, _resample(xy, SEG_SAMPLES), length(xy), (min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m))


def _proj(a, b, p) -> tuple[float, float]:
    """Distance de p au segment [a, b] et position (0..1) de sa projection sur ce segment."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n2 = dx * dx + dy * dy
    f = 0.0 if n2 == 0 else min(max(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n2, 0.0), 1.0)
    return math.hypot(p[0] - (a[0] + f * dx), p[1] - (a[1] + f * dy)), f


def at(values: list[float], x: float) -> float:
    """Valeur interpolée à la position fractionnaire x (indice 3,4 = 40 % entre les points 3 et 4)."""
    k = min(int(x), len(values) - 1)
    if k >= len(values) - 1:
        return values[-1]
    return values[k] + (values[k + 1] - values[k]) * (x - k)


def windows(path: list[tuple[float, float]], shape: Shape) -> list[tuple[float, float]]:
    """Passages d'un chemin déjà projeté sur le segment, dans le même sens : (position de départ, position d'arrivée),
    positions fractionnaires le long du chemin. La distance est mesurée au chemin lui-même (entre ses points), pas
    seulement à ses points : un tracé simplifié peut avoir des points espacés de plusieurs centaines de mètres."""
    if len(path) < 2:
        return []
    cum = [0.0]
    for a, b in zip(path, path[1:]):
        cum.append(cum[-1] + _d(a, b))

    def runs(target):
        res, best = [], None  # best : (position, distance) du passage en cours
        for k in range(len(path) - 1):
            dist, f = _proj(path[k], path[k + 1], target)
            if dist <= NEAR_END_M:
                if best is None or dist < best[1]:
                    best = (k + f, dist)
            elif best is not None:
                res.append(best[0])
                best = None
        if best is not None:
            res.append(best[0])
        return res

    out = []
    ends = runs(shape.xy[-1])
    for i in runs(shape.xy[0]):
        j = next((e for e in ends if e > i), None)
        if j is None:
            continue
        travelled = at(cum, j) - at(cum, i)
        if abs(travelled - shape.distance) > LENGTH_GAP * shape.distance + 2 * NEAR_END_M:
            continue
        lo, hi = int(i), min(math.ceil(j), len(path) - 1)
        if all(min(_proj(path[k], path[k + 1], q)[0] for k in range(lo, max(hi, lo + 1))) <= NEAR_PATH_M
               for q in shape.samples):
            out.append((i, j))
    return out


# ---------------------------------------------------------------- données point par point
def parse_stream(details: dict | None) -> list[list]:
    """Réponse « activity details » (activityDetailMetrics) -> [[t, lat, lon, dist, fc, alt], …], points sans position
    écartés, temps en secondes depuis le premier point."""
    details = details or {}
    keys = {m.get("key"): m.get("metricsIndex") for m in details.get("metricDescriptors") or []}
    need = ("directTimestamp", "directLatitude", "directLongitude", "sumDistance")
    if not all(k in keys for k in need):
        return []
    out, t0 = [], None
    for row in details.get("activityDetailMetrics") or []:
        m = row.get("metrics") or []

        def get(key):
            idx = keys.get(key)
            return m[idx] if idx is not None and idx < len(m) else None

        ts, lat, lon, dist = (get(k) for k in need)
        if not all(isinstance(v, (int, float)) for v in (ts, lat, lon, dist)) or not (lat or lon):
            continue
        t0 = ts if t0 is None else t0
        hr, ele = get("directHeartRate"), get("directElevation")
        out.append([round((ts - t0) / 1000, 1), round(lat, 6), round(lon, 6), round(dist, 1),
                    round(hr) if isinstance(hr, (int, float)) else None,
                    round(ele, 1) if isinstance(ele, (int, float)) else None])
    return out


def save_stream(session: Session, act: Activity, details: dict | None) -> list[list]:
    samples = parse_stream(details)
    session.merge(ActivityStream(activity_id=act.id, samples_json=json.dumps(samples, separators=(",", ":")),
                                 n=len(samples)))
    return samples


def load_stream(session: Session, activity_id: int) -> list[list] | None:
    row = session.get(ActivityStream, activity_id)
    return json.loads(row.samples_json) if row else None


# ---------------------------------------------------------------- recherche et chronométrage
def candidates(session: Session, seg: Segment, cache: dict | None = None) -> list[Activity]:
    """Sorties de la même famille dont le tracé emprunte le segment dans le même sens (sans appel Garmin)."""
    shape = Shape.of(tracks.loads(seg.points_json))
    stmt = (select(Activity, ActivityTrack.points_json).join(ActivityTrack, ActivityTrack.activity_id == Activity.id)
            .options(joinedload(Activity.sport).joinedload(Sport.family))
            .where(ActivityTrack.n_points >= 2, Activity.excluded.is_(False)))
    out = []
    for act, pts_json in session.execute(stmt):
        if seg.family_id and (not act.sport or act.sport.family_id != seg.family_id):
            continue
        pts = cache.get(act.id) if cache is not None else None
        if pts is None:
            pts = tracks.loads(pts_json)
            if cache is not None:
                cache[act.id] = pts
        path = [shape.proj.xy(p) for p in pts]
        x0, y0, x1, y1 = shape.bbox
        xs, ys = [x for x, _y in path], [y for _x, y in path]
        if max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1:  # emprise sans recouvrement
            continue
        if windows(path, shape):
            out.append(act)
    return out


@dataclass
class Timing:
    elapsed_s: float
    distance_m: float
    start_offset_s: float
    avg_hr: float | None


def time_on(samples: list[list], shape: Shape) -> Timing | None:
    """Meilleur passage d'une sortie sur le segment, d'après ses données point par point."""
    if len(samples) < 2:
        return None
    path = [shape.proj.xy((s[1], s[2])) for s in samples]
    times, dists = [s[0] for s in samples], [s[3] for s in samples]
    best = None
    for i, j in windows(path, shape):
        elapsed = at(times, j) - at(times, i)
        if elapsed <= 0:
            continue
        hrs = [s[4] for s in samples[int(i):math.ceil(j) + 1] if s[4]]
        t = Timing(elapsed, at(dists, j) - at(dists, i), at(times, i), sum(hrs) / len(hrs) if hrs else None)
        if best is None or t.elapsed_s < best.elapsed_s:
            best = t
    return best


def refresh(session: Session, source=None, segment_ids: list[int] | None = None, notify=None) -> dict:
    """Repère les sorties de chaque segment, télécharge leurs données point par point si besoin (source Garmin ;
    None = sans réseau), et met les passages à jour. Renvoie {fetched, efforts, records}."""
    from .sync import Progress

    notify = notify or (lambda p: None)
    stmt = select(Segment).order_by(Segment.id)
    if segment_ids is not None:
        stmt = stmt.where(Segment.id.in_(segment_ids))
    segs = list(session.scalars(stmt))
    cache: dict = {}
    todo: dict[int, list[Activity]] = {seg.id: candidates(session, seg, cache) for seg in segs}
    need = {a.id: a for acts in todo.values() for a in acts if session.get(ActivityStream, a.id) is None}
    fetched = 0
    if source is not None and hasattr(source, "details"):
        from .garmin import SyncError

        pause = getattr(source, "pause", 0)
        for k, act in enumerate(sorted(need.values(), key=lambda a: a.start, reverse=True), 1):
            notify(Progress("segments", k - 1, len(need), act.day))
            try:
                details = source.details(act.garmin_id)
            except SyncError:
                break  # limite Garmin : la suite viendra plus tard
            save_stream(session, act, details)
            session.commit()
            fetched += 1
            if pause and k < len(need):
                import time

                time.sleep(pause)
    efforts = records = 0
    for seg in segs:
        shape = Shape.of(tracks.loads(seg.points_json))
        best_before = min((e.elapsed_s for e in seg.efforts), default=None)
        existing = {e.activity_id: e for e in seg.efforts}
        keep = set()
        for act in todo[seg.id]:
            samples = load_stream(session, act.id)
            timing = time_on(samples, shape) if samples else None
            if timing is None:
                continue
            keep.add(act.id)
            e = existing.get(act.id)
            if e is None:
                e = SegmentEffort(segment=seg, activity_id=act.id, elapsed_s=0, distance_m=0)
                session.add(e)
                efforts += 1
                if best_before is not None and timing.elapsed_s < best_before:
                    records += 1
            e.elapsed_s, e.distance_m = round(timing.elapsed_s, 1), round(timing.distance_m, 1)
            e.start_offset_s, e.avg_hr = timing.start_offset_s, timing.avg_hr
        for act_id, e in existing.items():
            if act_id not in keep and session.get(ActivityStream, act_id) is not None:
                seg.efforts.remove(e)  # n'emprunte plus le segment (sortie exclue, segment modifié…)
    session.flush()
    return {"fetched": fetched, "efforts": efforts, "records": records,
            "pending": max(len(need) - fetched, 0)}


def analyse(session: Session, source, segment_ids: list[int], notify=None):
    """Analyse lancée depuis la page d'un segment, en tâche de fond ; notée dans l'historique des synchros."""
    from .models import SyncRun

    names = ", ".join(f"« {s.name} »" for s in session.scalars(select(Segment).where(Segment.id.in_(segment_ids))))
    run = SyncRun(mode="segments", message=f"Segment {names}")
    session.add(run)
    session.commit()
    res = refresh(session, source, segment_ids, notify)
    run.status, run.finished_at = "ok", datetime.now()
    run.message += (f" : {res['fetched']} sortie(s) téléchargée(s), {res['efforts']} passage(s) ajouté(s)"
                    + (f", {res['pending']} en attente (limite Garmin, reprise à la prochaine synchro)" if res["pending"] else "")
                    + ".")
    session.commit()
    return run


def missing_count(session: Session, seg: Segment) -> int:
    return sum(1 for a in candidates(session, seg) if session.get(ActivityStream, a.id) is None)


# ---------------------------------------------------------------- création et analyse
def create(session: Session, act: Activity, start_idx: int, end_idx: int, name: str) -> Segment:
    pts = tracks.loads(act.track.points_json) if act.track else []
    if not 0 <= start_idx < end_idx < len(pts):
        raise ValueError("Choisis un départ puis une arrivée plus loin sur le tracé.")
    part = pts[start_idx:end_idx + 1]
    proj = Projector(part[0][0])
    dist = length([proj.xy(p) for p in part])
    if dist < MIN_SEGMENT_M:
        raise ValueError(f"Segment trop court ({round(dist)} m) : 100 m au minimum.")
    seg = Segment(name=name.strip()[:120] or f"Segment de {dist / 1000:.1f} km".replace(".", ","),
                  family_id=act.sport.family_id if act.sport else None, points_json=tracks.dumps(part),
                  distance_m=round(dist, 1), source_activity_id=act.id)
    session.add(seg)
    session.flush()
    return seg


@dataclass
class Profile:
    km: list[float]
    ele: list[float]
    gain: float
    loss: float
    grade: float | None  # pente moyenne %
    max_grade: float | None  # sur 100 m glissants


def profile(session: Session, seg: Segment) -> Profile | None:
    """Profil d'altitude d'après les données point par point d'un passage (le plus récent qui en a)."""
    shape = Shape.of(tracks.loads(seg.points_json))
    efforts = sorted(seg.efforts, key=lambda e: e.activity.start, reverse=True)
    for e in efforts:
        samples = load_stream(session, e.activity_id) or []
        path = [shape.proj.xy((s[1], s[2])) for s in samples]
        wins = windows(path, shape)
        if not wins:
            continue
        i, j = wins[0]
        part = [s for s in samples[int(i):math.ceil(j) + 1] if s[5] is not None]
        if len(part) < 2:
            continue
        d0 = part[0][3]
        km = [round((s[3] - d0) / 1000, 3) for s in part]
        ele = [s[5] for s in part]
        gain = sum(max(b - a, 0) for a, b in zip(ele, ele[1:]))
        loss = sum(max(a - b, 0) for a, b in zip(ele, ele[1:]))
        total = (part[-1][3] - d0) or None
        grades = []
        k = 0
        for m in range(len(part)):
            while part[m][3] - part[k][3] > 100:
                k += 1
            span = part[m][3] - part[k][3]
            if span >= 50:
                grades.append((part[m][5] - part[k][5]) / span * 100)
        return Profile(km, ele, round(gain), round(loss), round((ele[-1] - ele[0]) / total * 100, 1) if total else None,
                       round(max(grades), 1) if grades else None)
    return None


def ranked(seg: Segment) -> list[tuple[int, SegmentEffort]]:
    """(rang, passage), meilleur temps d'abord ; sorties exclues écartées."""
    good = [e for e in seg.efforts if not e.activity.excluded]
    return [(k + 1, e) for k, e in enumerate(sorted(good, key=lambda e: e.elapsed_s))]


def recent_records(session: Session, now: datetime, days: int = 7) -> list[SimpleRecord]:
    """Records battus par les passages ajoutés ces derniers jours (segments avec au moins 2 passages)."""
    out = []
    since = now - timedelta(days=days)
    for seg in session.scalars(select(Segment)):
        rk = ranked(seg)
        if len(rk) < 2:
            continue
        best = rk[0][1]
        if best.created_at >= since:
            out.append(SimpleRecord(seg, best, rk[1][1].elapsed_s - best.elapsed_s))
    return out


@dataclass
class SimpleRecord:
    segment: Segment
    effort: SegmentEffort
    gain_s: float  # secondes gagnées sur l'ancien record
