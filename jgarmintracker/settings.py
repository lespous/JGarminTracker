"""Réglages enregistrés dans la base (table settings), avec leurs valeurs par défaut."""

from __future__ import annotations

import json
import re
import unicodedata

from sqlalchemy.orm import Session

from . import themes
from .models import Setting

LAYOUTS = {"header": "En-tête", "col_left": "Colonne à gauche"}
MODES = {"system": "Selon Windows", "light": "Clair", "dark": "Sombre"}

DEFAULTS = {
    "layout": "header",
    "palette": themes.DEFAULT_PALETTE,
    "mode": "system",
    "palettes": [],  # palettes personnalisées : [{id, name, light, dark}], même format que Labs
    "history_months": 12,  # premier lancement et « relire tout »
    "resync_days": 3,  # jours de santé re-synchronisés à chaque fois
    "auto_sync": False,  # synchro en arrière-plan au lancement de l'interface
    "home": None,  # [lat, lon] posé à la main ; None = déduit des départs (voir home())
    "check_limits": {},  # {family_id: {avg, max}} en m/s ; vide = défauts de checks.py
    "unusual_pct": 25,  # « allure inhabituelle » : % plus rapide que ta médiane
    "weight_reminder_days": 7,  # rappel de pesée après N jours sans pesée (0 = pas de rappel)
    "weight_goal": None,  # objectif de poids en kg
    "hrv_unavailable": False,  # 0.15.0 : la montre ne mesure pas la VFC (14 nuits vides) : plus d'historique demandé
}


def home(session: Session) -> tuple[list[float] | None, bool]:
    """Domicile pour centrer les cartes : (point, posé à la main ?). None s'il n'y a encore aucun tracé."""
    manual = get(session, "home")
    if isinstance(manual, list) and len(manual) == 2:
        return manual, True
    from sqlalchemy import select

    from . import tracks
    from .models import ActivityTrack

    ends = []
    for text, in session.execute(select(ActivityTrack.points_json).where(ActivityTrack.n_points > 1)):
        pts = tracks.loads(text)
        ends += [pts[0], pts[-1]]
    point = tracks.home_point(ends)
    return (list(point) if point else None), False


def get(session: Session, name: str):
    row = session.get(Setting, name)
    if row is None:
        return DEFAULTS[name]
    try:
        value = json.loads(row.value)
    except ValueError:
        return DEFAULTS[name]
    if name == "layout":
        value = {"col_right": "col_left"}.get(value, value)  # 0.4.0 proposait la colonne à droite
        return value if value in LAYOUTS else DEFAULTS[name]
    return value


def put(session: Session, name: str, value) -> None:
    if name not in DEFAULTS:
        raise KeyError(name)
    row = session.get(Setting, name)
    text = json.dumps(value, ensure_ascii=False)
    if row is None:
        session.add(Setting(name=name, value=text))
    else:
        row.value = text


def all_palettes(session: Session) -> dict[str, dict]:
    """Palettes fournies puis personnalisées : {nom: {light, dark, id (None si fournie)}}."""
    out = {name: {**p, "id": None} for name, p in themes.PALETTES.items()}
    for p in get(session, "palettes"):
        out[p["name"]] = {**themes.normalize(p), "id": p["id"]}
    return out


def active_palette(session: Session) -> dict:
    pals = all_palettes(session)
    return pals.get(get(session, "palette")) or pals[themes.DEFAULT_PALETTE]


def _slug(name: str) -> str:
    text = unicodedata.normalize("NFD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "palette"


def save_palette(session: Session, name: str, colors: dict, pal_id: str | None = None) -> str:
    """Crée ou met à jour une palette personnalisée. Renvoie son id. Lève PaletteError si invalide."""
    name = name.strip()[:60]
    if not name:
        raise themes.PaletteError("Donne un nom à la palette.")
    if name in themes.PALETTES:
        raise themes.PaletteError(f"« {name} » est le nom d'une palette fournie. Choisis-en un autre.")
    customs = list(get(session, "palettes"))
    if any(p["name"].casefold() == name.casefold() and p["id"] != pal_id for p in customs):
        raise themes.PaletteError(f"Une palette s'appelle déjà « {name} ».")
    colors = themes.normalize(colors, strict=True)
    old = next((p for p in customs if p["id"] == pal_id), None)
    entry = {"id": pal_id or _new_id(name, customs), "name": name, **colors}
    if old:
        customs[customs.index(old)] = entry
        if get(session, "palette") == old["name"]:  # palette active renommée : on suit
            put(session, "palette", name)
    else:
        customs.append(entry)
    put(session, "palettes", customs)
    return entry["id"]


def _new_id(name: str, customs: list[dict]) -> str:
    base, n = _slug(name), 1
    ids = {p["id"] for p in customs}
    while f"{base}-{n}" in ids:
        n += 1
    return f"{base}-{n}"


def delete_palette(session: Session, pal_id: str) -> str | None:
    customs = list(get(session, "palettes"))
    victim = next((p for p in customs if p["id"] == pal_id), None)
    if victim is None:
        return None
    customs.remove(victim)
    put(session, "palettes", customs)
    if get(session, "palette") == victim["name"]:
        put(session, "palette", themes.DEFAULT_PALETTE)
    return victim["name"]


def import_palettes(session: Session, text: str) -> tuple[list[str], list[str]]:
    """Importe le JSON de Labs. Renvoie (ajoutées ou mises à jour, ignorées car homonymes d'une palette fournie)."""
    done, skipped = [], []
    customs = {p["name"].casefold(): p for p in get(session, "palettes")}
    for p in themes.parse_import(text):
        if p["name"] in themes.PALETTES:
            skipped.append(p["name"])
            continue
        existing = customs.get(p["name"].casefold())
        save_palette(session, p["name"], p, existing["id"] if existing else None)
        customs = {q["name"].casefold(): q for q in get(session, "palettes")}
        done.append(p["name"])
    return done, skipped
