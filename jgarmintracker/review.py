"""Bilan de l'année (0.16.0) : chiffres, records, calendrier, matériel, amis, lieux, santé, météo.

Année en cours : bilan à date, comparé à la même période de l'année précédente, avec une projection de fin
d'année au rythme actuel. Les sorties exclues des statistiques ne comptent pas.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import form, units
from .models import Activity, DailyHealth, SegmentEffort, Sport
from .stats import Totals, activities_between, records, totals, week_start, week_streaks

MONTHS_SHORT = units.MONTHS_SHORT


def years(session: Session) -> list[int]:
    """Années avec au moins une sortie, la plus récente d'abord."""
    first, last = session.execute(select(func.min(Activity.start), func.max(Activity.start))).one()
    return list(range(last.year, first.year - 1, -1)) if first else []


@dataclass
class FamilyLine:
    family: object
    totals: Totals
    share: float  # part du temps total, en %
    records: object
    unit: str


@dataclass
class Review:
    year: int
    start: date
    end: date
    partial: bool
    totals: Totals
    prev: Totals
    prev_label: str
    projection: Totals | None
    families: list[FamilyLine]
    months: list[dict]
    best_month: dict | None
    longest: Activity | None
    longest_time: Activity | None
    most_climb: Activity | None
    active_days: int
    active_weeks: int
    best_streak: int
    calendar: list[list[dict | None]]  # semaines (colonnes) × 7 jours ; None hors année
    gear: list[tuple] = field(default_factory=list)  # (matériel, km, sorties)
    friends: list[tuple] = field(default_factory=list)  # (ami, sorties, km)
    routes: list[tuple] = field(default_factory=list)  # (parcours, passages)
    segment_records: list = field(default_factory=list)  # SegmentEffort meilleurs de tous les temps faits cette année
    places: list[tuple] = field(default_factory=list)  # (lieu, sorties)
    n_places: int = 0
    health: dict = field(default_factory=dict)
    weather: dict = field(default_factory=dict)

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def _pct(cur: float, old: float) -> float | None:
    return (cur - old) / old * 100 if old else None


def delta(cur: float, old: float) -> float | None:
    return _pct(cur, old)


def _calendar(acts: list[Activity], year: int, end: date, params) -> list[list[dict | None]]:
    """Calendrier façon GitHub : colonnes = semaines (lundi en haut), niveau 0 à 4 selon la charge du jour."""
    loads: dict[date, float] = {}
    for a in acts:
        t = form.trimp(a, params)
        if t is None:  # sans FC : estimation d'après la durée (intensité moyenne)
            t = (a.duration_s or 0) / 60 * 0.8
        loads[a.day] = loads.get(a.day, 0) + t
    values = sorted(v for v in loads.values() if v > 0)
    qs = [values[int(len(values) * q)] for q in (0.25, 0.5, 0.75)] if len(values) >= 4 else []

    def level(v: float) -> int:
        if v <= 0:
            return 0
        return 1 + sum(v > q for q in qs) if qs else 2

    first = date(year, 1, 1)
    cur = week_start(first)
    last = date(year, 12, 31)
    weeks = []
    while cur <= last:
        col = []
        for k in range(7):
            d = cur + timedelta(days=k)
            if d.year != year:
                col.append(None)
            else:
                v = loads.get(d, 0)
                col.append({"day": d, "load": round(v), "level": level(v), "future": d > end})
        weeks.append(col)
        cur += timedelta(days=7)
    return weeks


def review(session: Session, year: int, today: date) -> Review:
    start = date(year, 1, 1)
    end = min(date(year, 12, 31), today)
    partial = end < date(year, 12, 31)
    acts = activities_between(session, start, end)
    tot = totals(acts)
    prev_start = date(year - 1, 1, 1)
    prev_end = date(year - 1, end.month, min(end.day, 28 if end.month == 2 else end.day)) if partial else date(year - 1, 12, 31)
    prev = totals(activities_between(session, prev_start, prev_end))
    prev_label = f"{year - 1} à la même date" if partial else str(year - 1)

    projection = None
    if partial and tot.count:
        k = 365 / ((end - start).days + 1)
        projection = Totals(round(tot.count * k), tot.distance_m * k, tot.duration_s * k, tot.elevation_m * k)

    by_fam: dict[int, list[Activity]] = {}
    fams = {}
    for a in acts:
        if a.sport:
            by_fam.setdefault(a.sport.family_id, []).append(a)
            fams[a.sport.family_id] = a.sport.family
    lines = []
    for fid, items in by_fam.items():
        units_ = [a.sport.pace_unit for a in items if a.sport.pace_unit != "none"]
        unit = max(set(units_), key=units_.count) if units_ else "none"
        t = totals(items)
        lines.append(FamilyLine(fams[fid], t, t.duration_s / tot.duration_s * 100 if tot.duration_s else 0,
                                records(items, unit), unit))
    lines.sort(key=lambda f: -f.totals.duration_s)

    months = []
    for m in range(1, 13):
        items = [a for a in acts if a.start.month == m]
        t = totals(items)
        months.append({"month": m, "label": MONTHS_SHORT[m - 1], "count": t.count, "km": t.distance_m / 1000,
                       "hours": t.duration_s / 3600, "future": date(year, m, 1) > end})
    best_month = max((m for m in months if m["count"]), key=lambda m: m["hours"], default=None)

    days = sorted({a.day for a in acts})
    best_streak, _cur = week_streaks(days, end)

    r = Review(
        year, start, end, partial, tot, prev, prev_label, projection, lines, months, best_month,
        max((a for a in acts if a.distance_m), key=lambda a: a.distance_m, default=None),
        max((a for a in acts if a.duration_s), key=lambda a: a.duration_s, default=None),
        max((a for a in acts if a.elevation_gain_m), key=lambda a: a.elevation_gain_m, default=None),
        len(days), len({week_start(d) for d in days}), best_streak,
        _calendar(acts, year, end, form.hr_params(session, today)),
    )

    gear: dict[int, list] = {}
    friends: dict[int, list] = {}
    routes: Counter = Counter()
    route_obj = {}
    places: Counter = Counter()
    for a in acts:
        for g in a.gear:
            e = gear.setdefault(g.id, [g, 0.0, 0])
            e[1] += (a.distance_m or 0) / 1000
            e[2] += 1
        for f in a.friends:
            e = friends.setdefault(f.id, [f, 0, 0.0])
            e[1] += 1
            e[2] += (a.distance_m or 0) / 1000
        if a.route_id:
            routes[a.route_id] += 1
            route_obj[a.route_id] = a.route
        place = json.loads(a.raw_json or "{}").get("locationName")
        if place:
            places[place] += 1
    r.gear = sorted((tuple(v) for v in gear.values()), key=lambda v: -v[1])[:5]
    r.friends = sorted((tuple(v) for v in friends.values()), key=lambda v: (-v[1], -v[2]))[:5]
    r.routes = [(route_obj[rid], n) for rid, n in routes.most_common(5) if n >= 2]
    r.places, r.n_places = places.most_common(8), len(places)

    # Records de segments (meilleur temps de tous les temps) réalisés cette année.
    ids = {a.id for a in acts}
    from . import segments as seg_mod
    from .models import Segment

    for seg in session.scalars(select(Segment)):
        rk = seg_mod.ranked(seg)
        if rk and rk[0][1].activity_id in ids and len(rk) >= 2:
            r.segment_records.append(rk[0][1])

    # Santé : moyennes de l'année et de l'année précédente (même période).
    def avg(col, a, b):
        return session.scalar(select(func.avg(col)).where(DailyHealth.day >= a, DailyHealth.day <= b, col.is_not(None)))

    r.health = {
        "rhr": avg(DailyHealth.resting_hr, start, end), "rhr_prev": avg(DailyHealth.resting_hr, prev_start, prev_end),
        "sleep_h": (avg(DailyHealth.sleep_s, start, end) or 0) / 3600 or None,
        "sleep_prev_h": (avg(DailyHealth.sleep_s, prev_start, prev_end) or 0) / 3600 or None,
        "steps": avg(DailyHealth.steps, start, end),
        "rhr_first": avg(DailyHealth.resting_hr, start, start + timedelta(days=29)),
        "rhr_last": avg(DailyHealth.resting_hr, end - timedelta(days=29), end),
    }

    with_w = [a for a in acts if a.weather and a.weather.temp_c is not None]
    rainy = [a for a in with_w if any(w in (a.weather.sky or "").lower() for w in ("rain", "shower", "drizzle", "thunder"))]
    r.weather = {
        "coldest": min(with_w, key=lambda a: a.weather.temp_c, default=None),
        "hottest": max(with_w, key=lambda a: a.weather.temp_c, default=None),
        "windiest": max((a for a in with_w if a.weather.wind_kmh is not None), key=lambda a: a.weather.wind_kmh, default=None),
        "rainy": len(rainy), "n": len(with_w),
        "avg_temp": statistics.fmean(a.weather.temp_c for a in with_w) if with_w else None,
    }
    return r
