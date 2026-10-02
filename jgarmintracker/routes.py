"""Parcours répétés (0.13.0) : regroupe les sorties faites sur le même tracé, dans le même sens.

Deux sorties sont le même parcours quand elles sont de la même famille de sports, que leurs distances diffèrent de
5 % au plus, que départs et arrivées sont à moins de 300 m, et qu'au moins 80 % des points du tracé (rééchantillonné
en 100 points répartis sur la distance) sont à moins de 200 m du point correspondant de l'autre. Comparer les points
dans l'ordre impose le même sens. Tout est calculé sur le PC, à partir des tracés déjà en base.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from . import tracks, units
from .models import Activity, ActivityTrack, RouteGroup, Sport

SAMPLES = 100
MAX_DIST_GAP = 0.05
MAX_END_M = 300
MAX_POINT_M = 200
MIN_SHARED = 0.8
MIN_DISTANCE_M = 1000
M_PER_DEG_LAT = 110_540


@dataclass
class Signature:
    activity_id: int
    family_id: int | None
    distance_m: float
    xy: list[tuple[float, float]]  # SAMPLES points en mètres (projection locale commune)

    @property
    def start(self):
        return self.xy[0]

    @property
    def end(self):
        return self.xy[-1]


def _project(points: list[tracks.Point], lat0: float) -> list[tuple[float, float]]:
    k = math.cos(math.radians(lat0)) * 111_320
    return [(lon * k, lat * M_PER_DEG_LAT) for lat, lon in points]


def resample(xy: list[tuple[float, float]], n: int = SAMPLES) -> list[tuple[float, float]]:
    """n points régulièrement espacés le long du tracé (par la distance, pas par l'indice)."""
    cum = [0.0]
    for (x0, y0), (x1, y1) in zip(xy, xy[1:]):
        cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
    total = cum[-1]
    if total <= 0:
        return [xy[0]] * n
    out, j = [], 0
    for i in range(n):
        target = total * i / (n - 1)
        while j < len(cum) - 2 and cum[j + 1] < target:
            j += 1
        seg = cum[j + 1] - cum[j] or 1e-9
        t = min(max((target - cum[j]) / seg, 0), 1)
        (x0, y0), (x1, y1) = xy[j], xy[j + 1]
        out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return out


def signature(act: Activity, points: list[tracks.Point], lat0: float) -> Signature | None:
    if len(points) < 10 or not act.distance_m or act.distance_m < MIN_DISTANCE_M:
        return None
    return Signature(act.id, act.sport.family_id if act.sport else None, act.distance_m,
                     resample(_project(points, lat0)))


def _d(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def same_route(a: Signature, b: Signature) -> bool:
    if a.family_id != b.family_id:
        return False
    if abs(a.distance_m - b.distance_m) > MAX_DIST_GAP * max(a.distance_m, b.distance_m):
        return False
    if _d(a.start, b.start) > MAX_END_M or _d(a.end, b.end) > MAX_END_M:
        return False
    close = sum(_d(p, q) <= MAX_POINT_M for p, q in zip(a.xy, b.xy))
    return close >= MIN_SHARED * SAMPLES


def _candidates(session: Session) -> list[tuple[Activity, list[tracks.Point]]]:
    stmt = (select(Activity, ActivityTrack.points_json).join(ActivityTrack, ActivityTrack.activity_id == Activity.id)
            .options(joinedload(Activity.sport).joinedload(Sport.family))
            .where(ActivityTrack.n_points >= 10, Activity.excluded.is_(False), Activity.distance_m >= MIN_DISTANCE_M)
            .order_by(Activity.start))
    return [(a, tracks.loads(pts)) for a, pts in session.execute(stmt)]


def auto_name(act: Activity) -> str:
    place = json.loads(act.raw_json or "{}").get("locationName") or (act.sport.family.name if act.sport else "Parcours")
    return f"{place} · {units.number(act.distance_m / 1000, 0 if act.distance_m >= 10_000 else 1)} km"


def rebuild(session: Session) -> dict:
    """Recalcule tous les regroupements. Les parcours existants gardent leur numéro et leur nom (leur sortie de
    référence est essayée en premier) ; ceux qui n'ont plus qu'une sortie disparaissent."""
    rows = _candidates(session)
    lat0 = sum(p[0][0] for _a, p in rows) / len(rows) if rows else 50.0
    sigs: dict[int, Signature] = {}
    acts: dict[int, Activity] = {}
    for act, pts in rows:
        if sig := signature(act, pts, lat0):
            sigs[act.id], acts[act.id] = sig, act
    groups = list(session.scalars(select(RouteGroup).order_by(RouteGroup.id)))
    reps: list[tuple[RouteGroup | None, Signature]] = [(g, sigs[g.rep_activity_id]) for g in groups
                                                        if g.rep_activity_id in sigs]
    members: dict[int, list[int]] = {}  # index dans reps -> ids des activités
    for act_id, sig in sigs.items():
        for i, (_g, rep) in enumerate(reps):
            if same_route(sig, rep):
                members.setdefault(i, []).append(act_id)
                break
        else:
            reps.append((None, sig))
            members.setdefault(len(reps) - 1, []).append(act_id)
    for a in session.scalars(select(Activity).where(Activity.route_id.is_not(None))):
        a.route_id = None
    kept = set()
    used = {g.name for g, _rep in reps if g is not None and g.custom_name}
    for i, (g, rep) in enumerate(reps):
        ids = members.get(i, [])
        if len(ids) < 2:
            continue
        if g is None:
            g = RouteGroup(rep_activity_id=rep.activity_id)
            session.add(g)
            session.flush()
        if not g.custom_name:
            base, n = auto_name(acts[g.rep_activity_id]), 2
            g.name = base
            while g.name in used:  # deux parcours différents au même endroit, même distance : « (2) »
                g.name, n = f"{base} ({n})", n + 1
            used.add(g.name)
        for act_id in ids:
            acts[act_id].route_id = g.id
        kept.add(g.id)
    for g in groups:
        if g.id not in kept:
            session.delete(g)
    session.flush()
    return {"routes": len(kept), "activities": sum(len(v) for v in members.values() if len(v) >= 2)}


@dataclass
class Passage:
    activity: Activity
    rank: int  # 1 = meilleur temps


def passages(group: RouteGroup) -> list[Passage]:
    """Sorties du parcours, de la plus récente à la plus ancienne, avec leur rang au temps."""
    acts = [a for a in group.activities if not a.excluded and a.duration_s]
    order = sorted(acts, key=lambda a: a.duration_s)
    rank = {a.id: i + 1 for i, a in enumerate(order)}
    return [Passage(a, rank[a.id]) for a in sorted(acts, key=lambda a: a.start, reverse=True)]
