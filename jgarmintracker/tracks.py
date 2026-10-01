"""Tracés GPS : lecture de la réponse Garmin, simplification, mini-carte SVG."""

from __future__ import annotations

import json
import math

Point = tuple[float, float]  # (lat, lon)

MAX_POINTS = 2000  # demandés à Garmin par activité (tracé déjà simplifié par Garmin)
PREVIEW_W, PREVIEW_H = 64, 40


def parse_track(details: dict | None) -> list[Point]:
    """Réponse « activity details » -> [(lat, lon)], points invalides écartés, arrondis à ~1 m."""
    poly = ((details or {}).get("geoPolylineDTO") or {}).get("polyline") or []
    out: list[Point] = []
    for p in poly:
        if not isinstance(p, dict) or p.get("valid") is False:
            continue
        lat, lon = p.get("lat"), p.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and (lat or lon):
            pt = (round(lat, 5), round(lon, 5))
            if not out or out[-1] != pt:
                out.append(pt)
    return out


def has_track(raw_activity: dict) -> bool:
    """D'après la liste d'activités Garmin : y a-t-il un tracé à demander ?"""
    return bool(raw_activity.get("hasPolyline"))


def thin(points: list[Point], max_n: int) -> list[Point]:
    """Garde au plus max_n points, régulièrement espacés, premier et dernier compris."""
    if len(points) <= max_n or max_n < 2:
        return list(points)
    step = (len(points) - 1) / (max_n - 1)
    return [points[round(i * step)] for i in range(max_n)]


def bounds(points: list[Point]) -> tuple[float, float, float, float]:
    lats, lons = [p[0] for p in points], [p[1] for p in points]
    return min(lats), min(lons), max(lats), max(lons)


def preview_path(points: list[Point], w: int = PREVIEW_W, h: int = PREVIEW_H, pad: float = 3, max_n: int = 80) -> str:
    """Chemin SVG (« M x y L … ») du parcours dans une boîte w×h, proportions respectées (projection locale)."""
    if len(points) < 2:
        return ""
    pts = thin(points, max_n)
    lat0 = sum(p[0] for p in pts) / len(pts)
    k = math.cos(math.radians(lat0))  # un degré de longitude est plus court qu'un degré de latitude
    xs = [p[1] * k for p in pts]
    ys = [-p[0] for p in pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1e-9
    scale = min((w - 2 * pad) / span, (h - 2 * pad) / span)
    ox = pad + ((w - 2 * pad) - (max(xs) - min(xs)) * scale) / 2
    oy = pad + ((h - 2 * pad) - (max(ys) - min(ys)) * scale) / 2
    coords = [(ox + (x - min(xs)) * scale, oy + (y - min(ys)) * scale) for x, y in zip(xs, ys)]
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in coords)


def dumps(points: list[Point]) -> str:
    return json.dumps([list(p) for p in points], separators=(",", ":"))


def loads(text: str | None) -> list[Point]:
    return [tuple(p) for p in json.loads(text or "[]")]
