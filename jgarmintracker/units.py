"""Formatage à l'affichage (formats belges : virgule décimale, espace des milliers, jj/mm/aaaa).

Tout est stocké en SI (secondes, mètres, m/s) ; la conversion se fait uniquement ici.
"""

from __future__ import annotations

from datetime import date, datetime

NBSP = " "  # espace fine insécable, séparateur des milliers
DASH = "—"


def number(value: float | None, decimals: int = 0) -> str:
    """1234.5 -> « 1 234,5 »."""
    if value is None:
        return DASH
    text = f"{value:,.{decimals}f}"
    return text.replace(",", NBSP).replace(".", ",")


def km(meters: float | None, decimals: int | None = None) -> str:
    if meters is None:
        return DASH
    k = meters / 1000
    if decimals is None:
        decimals = 2 if k < 10 else 1
    return f"{number(k, decimals)} km"


def mmss(seconds: float | None) -> str:
    """Secondes -> « m:ss » (allures)."""
    if seconds is None:
        return DASH
    total = round(seconds)
    return f"{total // 60}:{total % 60:02d}"


def hmm(seconds: float | None) -> str:
    """Durée totale -> « 3h56 », ou « 50min » sous l'heure. Le « : » est réservé aux allures (4:21 /km)."""
    if seconds is None:
        return DASH
    minutes = round(seconds / 60)
    h, m = divmod(minutes, 60)
    return f"{h}h{m:02d}" if h else f"{m}min"


def hms(seconds: float | None) -> str:
    """Durée d'une activité -> « 1h38min11s », « 50min02s » ou « 45s » (sans espaces : compact en tableau)."""
    if seconds is None:
        return DASH
    total = round(seconds)
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h}h{m:02d}min{s:02d}s"
    return f"{m}min{s:02d}s" if m else f"{s}s"


def pace_seconds(speed_ms: float | None, per_m: float = 1000) -> float | None:
    """Vitesse (m/s) -> secondes pour per_m mètres (1000 pour min/km, 100 pour min/100 m)."""
    if not speed_ms or speed_ms <= 0:
        return None
    return per_m / speed_ms


def kmh_value(speed_ms: float | None) -> float | None:
    if not speed_ms or speed_ms <= 0:
        return None
    return speed_ms * 3.6


def pace(speed_ms: float | None, unit: str) -> str:
    """Allure ou vitesse selon l'unité du sport : min_km | kmh | min_100m | none."""
    if unit == "min_km":
        s = pace_seconds(speed_ms, 1000)
        return f"{mmss(s)} /km" if s else DASH
    if unit == "min_100m":
        s = pace_seconds(speed_ms, 100)
        return f"{mmss(s)} /100 m" if s else DASH
    if unit == "kmh":
        v = kmh_value(speed_ms)
        return f"{number(v, 1)} km/h" if v else DASH
    return DASH


def pace_value(speed_ms: float | None, unit: str) -> float | None:
    """Valeur numérique pour les graphiques : secondes (allures) ou km/h (vitesse)."""
    if unit == "min_km":
        return pace_seconds(speed_ms, 1000)
    if unit == "min_100m":
        return pace_seconds(speed_ms, 100)
    if unit == "kmh":
        return kmh_value(speed_ms)
    return None


def bpm(value: float | None) -> str:
    return DASH if value is None else f"{round(value)} bpm"


def meters(value: float | None) -> str:
    return DASH if value is None else f"{number(value)} m"


def day(value: date | datetime | None) -> str:
    return DASH if value is None else value.strftime("%d/%m/%Y")


def short_day(value: date | datetime | None) -> str:
    return DASH if value is None else value.strftime("%d/%m")


WEEKDAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]
MONTHS_SHORT = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def weekday_day(value: datetime | date) -> str:
    """« sam. 26/09 »."""
    return f"{WEEKDAYS[value.weekday()]} {value:%d/%m}"


def month_label(year: int, month: int, short: bool = False) -> str:
    names = MONTHS_SHORT if short else MONTHS
    return f"{names[month - 1]} {year}" if not short else f"{names[month - 1]} {year % 100:02d}"
