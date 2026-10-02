"""Forme (0.15.0) : charge d'entraînement, récupération, et liens sommeil / poids -> performance.

Charge : TRIMP de Banister, calculé sur le PC à partir de la FC moyenne de chaque sortie
    TRIMP = durée (min) × r × 0,64·e^(1,92·r)   (femmes : 0,86·e^(1,67·r))
    r = (FC moyenne − FC de repos) / (FC max − FC de repos)
Puis, jour par jour : « condition » (moyenne exponentielle 42 jours), « fatigue » (7 jours), « fraîcheur »
(condition − fatigue), et ratio aigu / chronique (charge moyenne des 7 derniers jours / des 28 derniers jours).
Les sorties exclues des statistiques ne comptent pas.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .models import Activity, DailyHealth, Profile, Sport, WeightEntry
from .stats import age_on, days_between, health_rows, rolling_mean

CTL_DAYS, ATL_DAYS = 42, 7
MIN_ACTIVE_DAYS = 6  # jours d'entraînement sur 28 : en dessous (reprise après une coupure), pas de ratio
MAX_RATIO = 3.0
MIN_CHRONIC = 10  # charge moyenne sur 28 jours en dessous de laquelle le ratio n'a pas de sens (reprise)
WARMUP_DAYS = 120  # historique pris avant la période pour que les moyennes exponentielles soient stables


# ---------------------------------------------------------------- charge
@dataclass
class HrParams:
    rest: float
    max: float
    female: bool
    max_source: str  # « profil », « 220 − âge », « mesurée »


def hr_params(session: Session, today: date) -> HrParams:
    prof = session.get(Profile, 1)
    if prof and prof.max_hr:
        mx, src = float(prof.max_hr), "profil"
    elif prof and (age := age_on(prof.birth_date, today)):
        mx, src = float(220 - age), "220 − âge"
    else:
        maxes = sorted(m for m, in session.execute(select(Activity.max_hr).where(Activity.max_hr.is_not(None))))
        mx, src = (float(maxes[int(len(maxes) * 0.99) - 1 if len(maxes) > 1 else 0]) if maxes else 190.0), "mesurée"
    rhrs = [r for r, in session.execute(select(DailyHealth.resting_hr).where(DailyHealth.resting_hr.is_not(None))
                                        .order_by(DailyHealth.day.desc()).limit(90))]
    rest = float(prof.rest_hr) if prof and prof.rest_hr else (statistics.median(rhrs) if rhrs else 60.0)
    return HrParams(rest, mx, bool(prof and prof.sex == "F"), src)


def trimp(act: Activity, p: HrParams) -> float | None:
    """Charge d'une sortie ; None sans FC moyenne ou sans durée."""
    if not act.avg_hr or not act.duration_s or p.max <= p.rest:
        return None
    r = min(max((act.avg_hr - p.rest) / (p.max - p.rest), 0), 1.1)
    k, b = (0.86, 1.67) if p.female else (0.64, 1.92)
    return act.duration_s / 60 * r * k * math.exp(b * r)


def daily_loads(session: Session, start: date, end: date, p: HrParams) -> tuple[dict[date, float], int, int]:
    """{jour: charge}, sorties comptées, sorties sans FC (ignorées)."""
    acts = session.scalars(select(Activity).where(
        Activity.start >= datetime.combine(start, datetime.min.time()),
        Activity.start < datetime.combine(end + timedelta(days=1), datetime.min.time()),
        Activity.excluded.is_(False)))
    loads: dict[date, float] = {}
    counted = missing = 0
    for a in acts:
        t = trimp(a, p)
        if t is None:
            missing += 1
            continue
        counted += 1
        loads[a.day] = loads.get(a.day, 0) + t
    return loads, counted, missing


def acwr_label(ratio: float | None) -> tuple[str, str]:
    """(libellé, classe CSS) du ratio aigu / chronique."""
    if ratio is None:
        return "pas assez d'historique", "muted"
    if ratio < 0.8:
        return "sous-charge : tu en fais moins que d'habitude", "low"
    if ratio <= 1.3:
        return "zone idéale : progression sans excès", "ok"
    if ratio <= 1.5:
        return "attention : hausse rapide de la charge", "warn"
    return "risque : charge très au-dessus de l'habitude", "bad"


def form_label(tsb: float | None) -> str:
    if tsb is None:
        return ""
    if tsb > 15:
        return "très frais (peut-être en perte de condition)"
    if tsb > 5:
        return "frais, prêt pour un effort"
    if tsb >= -10:
        return "équilibré"
    if tsb >= -30:
        return "fatigué : entraînement chargé"
    return "très fatigué : pense à récupérer"


@dataclass
class Load:
    labels: list[str]
    days: list[date]
    load: list[float]
    ctl: list[float]
    atl: list[float]
    tsb: list[float]
    acwr: list[float | None]
    counted: int
    missing: int
    params: HrParams

    @property
    def today(self) -> dict:
        i = len(self.days) - 1
        week = sum(self.load[max(0, i - 6): i + 1])
        ratio = self.acwr[i] if self.acwr else None
        label, css = acwr_label(ratio)
        return {"week": week, "ratio": ratio, "ratio_label": label, "ratio_css": css,
                "ctl": self.ctl[i] if self.ctl else None, "atl": self.atl[i] if self.atl else None,
                "tsb": self.tsb[i] if self.tsb else None, "tsb_label": form_label(self.tsb[i] if self.tsb else None)}


def load_series(session: Session, start: date, end: date, today: date) -> Load:
    p = hr_params(session, today)
    warm = start - timedelta(days=WARMUP_DAYS)
    loads, counted, missing = daily_loads(session, warm, end, p)
    ctl = atl = 0.0
    kc, ka = 1 - math.exp(-1 / CTL_DAYS), 1 - math.exp(-1 / ATL_DAYS)
    out = Load([], [], [], [], [], [], [], 0, 0, p)
    history: list[float] = []
    for d in days_between(warm, end):
        x = loads.get(d, 0.0)
        history.append(x)
        ctl += (x - ctl) * kc
        atl += (x - atl) * ka
        if d < start:
            continue
        chronic = sum(history[-28:]) / 28 if len(history) >= 28 else None
        acute = sum(history[-7:]) / 7
        out.days.append(d)
        out.labels.append(d.strftime("%d/%m/%y"))
        out.load.append(round(x, 1))
        out.ctl.append(round(ctl, 1))
        out.atl.append(round(atl, 1))
        out.tsb.append(round(ctl - atl, 1))
        active = sum(1 for v in history[-28:] if v > 0)
        ok = chronic and chronic >= MIN_CHRONIC and active >= MIN_ACTIVE_DAYS
        out.acwr.append(round(min(acute / chronic, MAX_RATIO), 2) if ok else None)
    _, out.counted, out.missing = daily_loads(session, start, end, p)
    return out


# ---------------------------------------------------------------- récupération
def recovery_series(session: Session, days: list[date]) -> dict:
    """FC de repos, Body Battery max, sommeil et VFC, jour par jour, avec moyennes 7 jours."""
    if not days:
        return {"rhr7": [], "bb": [], "sleep7": [], "hrv": [], "hrv_low": [], "hrv_high": [], "has_hrv": False}
    rows = health_rows(session, days[0] - timedelta(days=6), days[-1])
    span = days_between(days[0] - timedelta(days=6), days[-1])

    def col(attr, scale=1.0):
        return [round(getattr(rows[d], attr) / scale, 2) if d in rows and getattr(rows[d], attr) is not None else None
                for d in span]

    cut = 6
    hrv = col("hrv_night")[cut:]
    return {
        "rhr7": rolling_mean(col("resting_hr"))[cut:],
        "bb": rolling_mean(col("bb_max"))[cut:],
        "sleep7": rolling_mean(col("sleep_s", 3600))[cut:],
        "hrv": hrv, "hrv_low": col("hrv_low")[cut:], "hrv_high": col("hrv_high")[cut:],
        "has_hrv": any(v is not None for v in hrv),
    }


# ---------------------------------------------------------------- liens avec la performance
MIN_PEERS = 5
PEER_DAYS = 60


def relative_speeds(session: Session, family_id: int) -> list[tuple[Activity, float]]:
    """(sortie, écart en % à la vitesse habituelle du même sport, sur ±60 jours). Positif = plus rapide que
    d'habitude. Compare chaque sortie à ses semblables : la forme du jour, pas le type de sortie."""
    acts = list(session.scalars(
        select(Activity).join(Sport).options(joinedload(Activity.sport))
        .where(Sport.family_id == family_id, Activity.excluded.is_(False), Activity.avg_speed > 0,
               Activity.distance_m >= 1000).order_by(Activity.start)))
    by_sport: dict[int, list[Activity]] = {}
    for a in acts:
        by_sport.setdefault(a.sport_id, []).append(a)
    out = []
    for group in by_sport.values():
        for a in group:
            peers = [b.avg_speed for b in group if b is not a and abs((b.start - a.start).days) <= PEER_DAYS]
            if len(peers) >= MIN_PEERS:
                out.append((a, (a.avg_speed / statistics.median(peers) - 1) * 100))
    return out


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def strength(r: float | None) -> str:
    if r is None:
        return "pas assez de données"
    a = abs(r)
    return "aucun lien net" if a < 0.1 else "lien faible" if a < 0.3 else "lien modéré" if a < 0.5 else "lien fort"


@dataclass
class Link:
    """Nuage de points x (sommeil, poids…) / y (% de vitesse) et moyennes par tranche."""
    points: list[dict] = field(default_factory=list)  # {x, y, name, date, url_id}
    bins: list[dict] = field(default_factory=list)  # {label, n, avg}
    r: float | None = None
    slope: float | None = None  # % de vitesse par unité de x

    @property
    def n(self) -> int:
        return len(self.points)

    @property
    def strength(self) -> str:
        return strength(self.r)


def _link(pairs: list[tuple[Activity, float, float]], edges: list[tuple[float | None, float | None, str]]) -> Link:
    link = Link()
    for a, x, y in pairs:
        link.points.append({"x": round(x, 2), "y": round(y, 1), "name": a.name, "date": a.start.strftime("%d/%m/%Y"),
                            "id": a.id})
    xs, ys = [p[1] for p in pairs], [p[2] for p in pairs]
    link.r = pearson(xs, ys)
    if link.r is not None:
        link.slope = link.r * statistics.pstdev(ys) / statistics.pstdev(xs)
    for lo, hi, label in edges:
        sel = [y for _a, x, y in pairs if (lo is None or x >= lo) and (hi is None or x < hi)]
        link.bins.append({"label": label, "n": len(sel), "avg": round(statistics.fmean(sel), 1) if sel else None})
    return link


SLEEP_BINS = [(None, 6, "moins de 6 h"), (6, 7, "6 à 7 h"), (7, 8, "7 à 8 h"), (8, None, "8 h et plus")]


def sleep_link(session: Session, family_id: int) -> Link:
    """Sommeil de la nuit précédant la sortie (rattaché au jour du réveil = jour de la sortie)."""
    rel = relative_speeds(session, family_id)
    if not rel:
        return Link()
    days = {a.day for a, _ in rel}
    sleeps = {d: s for d, s in session.execute(select(DailyHealth.day, DailyHealth.sleep_s)
                                               .where(DailyHealth.day.in_(days), DailyHealth.sleep_s > 0))}
    pairs = [(a, sleeps[a.day] / 3600, y) for a, y in rel if a.day in sleeps]
    return _link(pairs, SLEEP_BINS)


WEIGHT_MIN_ENTRIES = 10
WEIGHT_MIN_WEEKS = 8
WEIGHT_MAX_AGE_DAYS = 14


@dataclass
class WeightLink:
    ready: bool
    entries: int
    weeks: float
    link: Link


def weight_link(session: Session, family_id: int) -> WeightLink:
    """Poids de la dernière pesée (au plus 14 jours avant la sortie). Il faut au moins 10 pesées sur 8 semaines."""
    rows = session.scalars(select(WeightEntry).order_by(WeightEntry.day)).all()
    weeks = (rows[-1].day - rows[0].day).days / 7 if len(rows) >= 2 else 0
    ready = len(rows) >= WEIGHT_MIN_ENTRIES and weeks >= WEIGHT_MIN_WEEKS
    if not ready:
        return WeightLink(False, len(rows), weeks, Link())
    pairs = []
    for a, y in relative_speeds(session, family_id):
        before = [w for w in rows if w.day <= a.day and (a.day - w.day).days <= WEIGHT_MAX_AGE_DAYS]
        if before:
            pairs.append((a, before[-1].weight_kg, y))
    ws = [w.weight_kg for w in rows]
    lo, hi = min(ws), max(ws)
    step = max((hi - lo) / 3, 0.5)
    edges = [(None, lo + step, f"moins de {lo + step:.1f} kg".replace(".", ",")),
             (lo + step, lo + 2 * step, f"{lo + step:.1f} à {lo + 2 * step:.1f} kg".replace(".", ",")),
             (lo + 2 * step, None, f"{lo + 2 * step:.1f} kg et plus".replace(".", ","))]
    return WeightLink(True, len(rows), weeks, _link(pairs, edges))


def families_with_pace(session: Session) -> list:
    """Familles dont au moins un sport a une allure ou une vitesse, les plus pratiquées d'abord."""
    from sqlalchemy import func

    from .models import SportFamily

    rows = session.execute(select(SportFamily, func.count(Activity.id)).join(Sport, Sport.family_id == SportFamily.id)
                           .join(Activity, Activity.sport_id == Sport.id).where(Sport.pace_unit != "none")
                           .group_by(SportFamily.id).order_by(func.count(Activity.id).desc())).all()
    return [f for f, _n in rows]


# ---------------------------------------------------------------- VFC (lecture de la réponse Garmin)
def parse_hrv(raw: dict | None) -> dict:
    summ = (raw or {}).get("hrvSummary") or {}
    base = summ.get("baseline") or {}

    def num(v):
        return float(v) if isinstance(v, (int, float)) and v > 0 else None

    return {"hrv_night": num(summ.get("lastNightAvg")), "hrv_week": num(summ.get("weeklyAvg")),
            "hrv_status": (summ.get("status") or None) and str(summ.get("status"))[:20],
            "hrv_low": num(base.get("balancedLow")), "hrv_high": num(base.get("balancedUpper")),
            "raw_hrv": json.dumps(raw or {}, ensure_ascii=False)}


HRV_STATUS = {"BALANCED": "équilibrée", "UNBALANCED": "déséquilibrée", "LOW": "basse", "POOR": "faible"}
