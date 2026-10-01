"""Agrégats : semaines ISO, mois, moyennes glissantes, allures, tendances, records.

Les libellés des axes (jours, semaines, mois) sont préparés ici : Chart.js reçoit des catégories, pas des dates.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from . import units
from .models import Activity, DailyHealth, Sport, SportFamily


# ---------------------------------------------------------------- dates
def week_start(d: date) -> date:
    """Lundi de la semaine ISO contenant d."""
    return d - timedelta(days=d.weekday())


def week_label(monday: date) -> str:
    return f"S{monday.isocalendar().week:02d} · {monday:%d/%m}"


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


# ---------------------------------------------------------------- séries
def rolling_mean(values: list[float | None], window: int = 7, min_points: int = 3) -> list[float | None]:
    """Moyenne glissante sur les `window` derniers jours (jour courant inclus), en ignorant les trous.

    Renvoie None tant que la fenêtre contient moins de `min_points` valeurs : un trou reste un trou.
    """
    out: list[float | None] = []
    for i in range(len(values)):
        seen = [v for v in values[max(0, i - window + 1): i + 1] if v is not None]
        out.append(round(sum(seen) / len(seen), 1) if len(seen) >= min_points else None)
    return out


def linear_trend(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    """Droite des moindres carrés y = a·x + b. None s'il y a moins de 2 points distincts."""
    if len(xs) < 2 or len(set(xs)) < 2:
        return None
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return a, my - a * mx


# ---------------------------------------------------------------- activités
def activities_between(session: Session, start: date, end: date, sport_ids: list[int] | None = None) -> list[Activity]:
    """Activités dont le début (heure locale) tombe entre start et end inclus."""
    stmt = select(Activity).options(joinedload(Activity.sport).joinedload(Sport.family)).where(
        Activity.start >= datetime.combine(start, datetime.min.time()),
        Activity.start < datetime.combine(end + timedelta(days=1), datetime.min.time()),
    )
    if sport_ids is not None:
        stmt = stmt.where(Activity.sport_id.in_(sport_ids))
    return list(session.scalars(stmt.order_by(Activity.start)).unique())


@dataclass
class Totals:
    count: int = 0
    distance_m: float = 0.0
    duration_s: float = 0.0
    elevation_m: float = 0.0

    def add(self, a: Activity) -> None:
        self.count += 1
        self.distance_m += a.distance_m or 0
        self.duration_s += a.duration_s or 0
        self.elevation_m += a.elevation_gain_m or 0


def totals(activities: list[Activity]) -> Totals:
    t = Totals()
    for a in activities:
        t.add(a)
    return t


@dataclass
class FamilyWeek:
    family: SportFamily
    current: Totals
    previous: Totals


@dataclass
class WeekCompare:
    monday: date
    current: Totals
    previous: Totals
    families: list[FamilyWeek] = field(default_factory=list)


def week_compare(session: Session, today: date, sport_ids: list[int] | None = None) -> WeekCompare:
    """Semaine en cours (lundi -> today) contre la semaine précédente entière."""
    monday = week_start(today)
    cur = activities_between(session, monday, today, sport_ids)
    prev = activities_between(session, monday - timedelta(days=7), monday - timedelta(days=1), sport_ids)
    by_family: dict[int, tuple[Totals, Totals]] = defaultdict(lambda: (Totals(), Totals()))
    families: dict[int, SportFamily] = {}
    for idx, rows in ((0, cur), (1, prev)):
        for a in rows:
            if a.sport:
                families[a.sport.family_id] = a.sport.family
                by_family[a.sport.family_id][idx].add(a)
    rows = [FamilyWeek(families[fid], c, p) for fid, (c, p) in by_family.items()]
    rows.sort(key=lambda r: r.family.position)
    return WeekCompare(monday, totals(cur), totals(prev), rows)


def weekly_volume(session: Session, today: date, weeks: int = 12, metric: str = "duration") -> dict:
    """Volume par semaine et par sport, pour des barres empilées. metric : duration (heures) | distance (km)."""
    first = week_start(today) - timedelta(weeks=weeks - 1)
    mondays = [first + timedelta(weeks=i) for i in range(weeks)]
    index = {m: i for i, m in enumerate(mondays)}
    per_sport: dict[int, list[float]] = {}
    sports: dict[int, Sport] = {}
    for a in activities_between(session, first, today):
        if not a.sport:
            continue
        value = (a.duration_s or 0) / 3600 if metric == "duration" else (a.distance_m or 0) / 1000
        if not value:
            continue
        sports[a.sport_id] = a.sport
        per_sport.setdefault(a.sport_id, [0.0] * weeks)[index[week_start(a.day)]] += value
    ordered = sorted(sports.values(), key=lambda s: (s.family.position, s.position))
    return {
        "labels": [week_label(m) for m in mondays],
        "datasets": [{"label": s.label, "color": s.color, "data": [round(v, 2) for v in per_sport[s.id]]}
                     for s in ordered],
        "unit": "h" if metric == "duration" else "km",
    }


def monthly_volume(activities: list[Activity], today: date, months: int = 12) -> dict:
    """Distance (km) et durée (h) par mois, sur les `months` derniers mois."""
    first = add_months(month_start(today), -(months - 1))
    starts = [add_months(first, i) for i in range(months)]
    dist, dur, count = Counter(), Counter(), Counter()
    for a in activities:
        key = month_start(a.day)
        dist[key] += (a.distance_m or 0) / 1000
        dur[key] += (a.duration_s or 0) / 3600
        count[key] += 1
    return {
        "labels": [units.month_label(m.year, m.month, short=True) for m in starts],
        "distance": [round(dist[m], 1) for m in starts],
        "duration": [round(dur[m], 2) for m in starts],
        "count": [count[m] for m in starts],
    }


def pace_series(activities: list[Activity], unit: str, min_distance_m: float = 0) -> dict:
    """Allure (secondes par km / 100 m) ou vitesse (km/h) de chaque sortie, avec tendance linéaire."""
    points = []
    for a in activities:
        if (a.distance_m or 0) < max(min_distance_m, 1):
            continue
        v = units.pace_value(a.avg_speed, unit)
        if v is not None:
            points.append((a, v))
    if not points:
        return {"labels": [], "values": [], "trend": [], "names": [], "change": None}
    t0 = points[0][0].start
    xs = [(a.start - t0).total_seconds() / 86400 for a, _ in points]
    ys = [v for _, v in points]
    fit = linear_trend(xs, ys)
    trend = [round(fit[0] * x + fit[1], 2) for x in xs] if fit else []
    return {
        "labels": [units.day(a.start) for a, _ in points],
        "values": [round(v, 2) for v in ys],
        "trend": trend,
        "names": [a.name for a, _ in points],
        # Variation sur la période selon la tendance (négatif = allure plus rapide pour min/km).
        "change": round(trend[-1] - trend[0], 2) if trend else None,
    }


@dataclass
class Records:
    longest: Activity | None = None
    longest_duration: Activity | None = None
    best_pace: Activity | None = None  # meilleure allure / vitesse moyenne sur une sortie de plus de 5 km
    most_elevation: Activity | None = None
    max_speed: Activity | None = None
    # Meilleurs temps mesurés par la montre à l'intérieur d'une sortie : [(libellé, mètres, activité, secondes)].
    splits: list[tuple[str, int, Activity, float]] = field(default_factory=list)


SPLITS = [("1 km", 1000, "fastest_1k_s"), ("1 mile", 1609, "fastest_mile_s"), ("5 km", 5000, "fastest_5k_s"),
          ("40 km", 40000, "fastest_40k_s")]


def records(activities: list[Activity], unit: str, min_pace_distance_m: float = 5000) -> Records:
    r = Records()
    with_dist = [a for a in activities if a.distance_m]
    if with_dist:
        r.longest = max(with_dist, key=lambda a: a.distance_m)
    with_dur = [a for a in activities if a.duration_s]
    if with_dur:
        r.longest_duration = max(with_dur, key=lambda a: a.duration_s)
    if unit != "none":
        long_enough = [a for a in with_dist if a.distance_m >= min_pace_distance_m and a.avg_speed]
        if unit == "min_100m":
            long_enough = [a for a in with_dist if a.distance_m >= 1000 and a.avg_speed]
        if long_enough:
            r.best_pace = max(long_enough, key=lambda a: a.avg_speed)
    with_elev = [a for a in activities if a.elevation_gain_m]
    if with_elev:
        r.most_elevation = max(with_elev, key=lambda a: a.elevation_gain_m)
    with_vmax = [a for a in activities if a.max_speed]
    if with_vmax and unit != "none":
        r.max_speed = max(with_vmax, key=lambda a: a.max_speed)
    for label, meters, attr in SPLITS:
        timed = [a for a in activities if getattr(a, attr)]
        if timed:
            best = min(timed, key=lambda a: getattr(a, attr))
            r.splits.append((label, meters, best, getattr(best, attr)))
    return r


# ---------------------------------------------------------------- santé
def health_rows(session: Session, start: date, end: date) -> dict[date, DailyHealth]:
    rows = session.scalars(select(DailyHealth).where(DailyHealth.day >= start, DailyHealth.day <= end))
    return {r.day: r for r in rows}


def health_series(session: Session, today: date, days: int = 30) -> dict:
    """Séries par jour (None = pas de donnée) et moyennes glissantes 7 jours, prêtes pour Chart.js."""
    start = today - timedelta(days=days - 1)
    span = days_between(start, today)
    rows = health_rows(session, start, today)

    def col(attr, scale: float = 1, digits: int = 1):
        out = []
        for d in span:
            v = getattr(rows[d], attr) if d in rows else None
            out.append(round(v / scale, digits) if v is not None else None)
        return out

    rhr = col("resting_hr", digits=0)
    sleep_h = col("sleep_s", 3600, 2)
    bb = [[rows[d].bb_min, rows[d].bb_max] if d in rows and rows[d].bb_min is not None
          and rows[d].bb_max is not None else None for d in span]
    steps = col("steps", digits=0)
    stress = col("stress_avg", digits=0)
    label = units.weekday_day if days <= 31 else units.short_day
    return {
        "labels": [label(d) for d in span],
        "rhr": rhr, "rhr7": rolling_mean(rhr),
        "sleep": sleep_h, "sleep7": rolling_mean(sleep_h),
        "deep": col("deep_s", 3600, 2), "light": col("light_s", 3600, 2),
        "rem": col("rem_s", 3600, 2), "awake": col("awake_s", 3600, 2),
        "score": col("sleep_score", digits=0),
        "bb": bb, "bb_charged": col("bb_charged", digits=0), "bb_max": col("bb_max", digits=0),
        "steps": steps, "steps7": rolling_mean(steps),
        "stress": stress, "stress7": rolling_mean(stress),
        "vo2max": col("vo2max", digits=1),
    }


@dataclass
class HealthSummary:
    """Moyennes d'une période, et celles de la période précédente de même longueur pour comparer."""
    rhr: float | None
    rhr_prev: float | None
    sleep_h: float | None
    sleep_h_prev: float | None
    score: float | None
    score_prev: float | None
    bb_max: float | None
    bb_max_prev: float | None
    steps: float | None
    steps_prev: float | None
    stress: float | None
    stress_prev: float | None
    vo2max: float | None
    days_with_data: int


def _avg(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def health_summary(session: Session, today: date, days: int) -> HealthSummary:
    cur = list(health_rows(session, today - timedelta(days=days - 1), today).values())
    prev = list(health_rows(session, today - timedelta(days=2 * days - 1), today - timedelta(days=days)).values())

    def pair(attr, scale=1):
        return (_avg((getattr(r, attr) / scale) if getattr(r, attr) is not None else None for r in cur),
                _avg((getattr(r, attr) / scale) if getattr(r, attr) is not None else None for r in prev))

    rhr, sleep, score, bb, steps, stress = (pair("resting_hr"), pair("sleep_s", 3600), pair("sleep_score"),
                                            pair("bb_max"), pair("steps"), pair("stress_avg"))
    vo2 = [r for r in sorted(cur, key=lambda r: r.day) if r.vo2max is not None]
    return HealthSummary(rhr[0], rhr[1], sleep[0], sleep[1], score[0], score[1], bb[0], bb[1], steps[0], steps[1],
                         stress[0], stress[1], vo2[-1].vo2max if vo2 else None, len(cur))
