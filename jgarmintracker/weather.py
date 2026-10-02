"""Météo au départ des sorties (0.13.0) : lecture de la réponse Garmin, libellés, statistiques par météo.

Garmin (endpoint activity/{id}/weather) donne la température en °F et le vent en mph, quelle que soit la langue
du compte : on convertit ici, une fois, avant d'enregistrer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Activity, ActivityWeather

MPH_KMH = 1.609344


def f_to_c(value) -> float | None:
    return round((float(value) - 32) * 5 / 9, 1) if isinstance(value, (int, float)) else None


def mph_to_kmh(value) -> float | None:
    return round(float(value) * MPH_KMH, 1) if isinstance(value, (int, float)) else None


def parse(raw: dict | None) -> dict:
    """Réponse Garmin -> champs de ActivityWeather (tous None si rien d'utile)."""
    raw = raw or {}
    sky = ((raw.get("weatherTypeDTO") or {}).get("desc") or "").strip()
    return {
        "temp_c": f_to_c(raw.get("temp")),
        "feels_c": f_to_c(raw.get("apparentTemp")),
        "dew_c": f_to_c(raw.get("dewPoint")),
        "humidity": raw.get("relativeHumidity") if isinstance(raw.get("relativeHumidity"), (int, float)) else None,
        "wind_kmh": mph_to_kmh(raw.get("windSpeed")),
        "gust_kmh": mph_to_kmh(raw.get("windGust")),
        "wind_deg": raw.get("windDirection") if isinstance(raw.get("windDirection"), (int, float)) else None,
        "sky": "" if sky.lower() == "unknown" else sky[:60],
        "station": str((raw.get("weatherStationDTO") or {}).get("id") or "")[:40],
    }


def save(session: Session, act: Activity, raw: dict | None) -> bool:
    """Enregistre la météo (ou son absence, pour ne pas la redemander). True s'il y a une température."""
    values = parse(raw)
    row = ActivityWeather(activity_id=act.id, raw_json=json.dumps(raw or {}, ensure_ascii=False), **values)
    session.merge(row)
    return values["temp_c"] is not None


def missing(session: Session) -> list[Activity]:
    """Activités sans météo demandée, plus récentes d'abord."""
    stmt = (select(Activity).outerjoin(ActivityWeather, ActivityWeather.activity_id == Activity.id)
            .where(ActivityWeather.activity_id.is_(None)).order_by(Activity.start.desc()))
    return list(session.scalars(stmt))


# ---------------------------------------------------------------- affichage
# Mots de la description Garmin (anglais) -> (libellé, icône Phosphor). Le premier qui correspond l'emporte.
SKIES: list[tuple[tuple[str, ...], str, str]] = [
    (("thunder", "storm"), "Orage", "cloud-lightning"),
    (("snow", "sleet", "flurr", "ice"), "Neige", "cloud-snow"),
    (("rain", "shower", "drizzle"), "Pluie", "cloud-rain"),
    (("fog", "mist", "haze"), "Brouillard", "cloud-fog"),
    (("partly", "mostly sunny", "few clouds", "scattered"), "Éclaircies", "cloud-sun"),
    (("cloud", "overcast"), "Nuageux", "cloud"),
    (("sunny", "clear", "fair"), "Ensoleillé", "sun"),
    (("wind",), "Venteux", "wind"),
]
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]


def sky_label(desc: str | None) -> tuple[str, str]:
    """(libellé, icône) ; ciel inconnu : (« », thermomètre)."""
    text = (desc or "").lower()
    for words, label, icon in SKIES:
        if any(w in text for w in words):
            return label, icon
    return (desc or ""), "thermometer"


def compass(deg: float | None) -> str:
    """Direction d'où vient le vent, en points cardinaux français (O pour ouest)."""
    return "" if deg is None else COMPASS[round(deg / 22.5) % 16]


# ---------------------------------------------------------------- statistiques
TEMP_BANDS = [(None, 5, "moins de 5 °C"), (5, 10, "5 à 10 °C"), (10, 15, "10 à 15 °C"), (15, 20, "15 à 20 °C"),
              (20, 25, "20 à 25 °C"), (25, None, "25 °C et plus")]
WIND_BANDS = [(None, 10, "moins de 10 km/h"), (10, 20, "10 à 20 km/h"), (20, 30, "20 à 30 km/h"),
              (30, None, "30 km/h et plus")]


@dataclass
class Band:
    label: str
    count: int = 0
    distance_m: float = 0.0
    moving_s: float = 0.0

    @property
    def speed(self) -> float | None:
        """Vitesse moyenne pondérée par la distance (m/s) : total des km / total du temps."""
        return self.distance_m / self.moving_s if self.moving_s else None


def _band(value: float, bands) -> int | None:
    for i, (lo, hi, _label) in enumerate(bands):
        if (lo is None or value >= lo) and (hi is None or value < hi):
            return i
    return None


def by_weather(activities: list[Activity]) -> dict:
    """Allure moyenne par tranche de température et de vent ; sorties avec distance et météo seulement."""
    temps = [Band(label) for _lo, _hi, label in TEMP_BANDS]
    winds = [Band(label) for _lo, _hi, label in WIND_BANDS]
    used = 0
    for a in activities:
        w = a.weather
        secs = a.moving_s or a.duration_s
        if not w or not a.distance_m or not secs:
            continue
        hit = False
        for value, bands, out in ((w.temp_c, TEMP_BANDS, temps), (w.wind_kmh, WIND_BANDS, winds)):
            if value is None:
                continue
            b = out[_band(value, bands)]
            b.count += 1
            b.distance_m += a.distance_m
            b.moving_s += secs
            hit = True
        used += hit
    return {"temps": temps, "winds": winds, "used": used}
