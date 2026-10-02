"""Image du bilan de l'année (0.16.0) : carte PNG 1080 × 1350 (format portrait des réseaux sociaux), dessinée sur
le PC avec Pillow, aux couleurs sombres du thème choisi. Rien n'est envoyé nulle part."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import units
from .review import Review, delta

W, H = 1080, 1350
PAD = 72
FONTS = Path(r"C:\Windows\Fonts")


def _font(size: int, bold: bool = False, mono: bool = False):
    names = ["CascadiaMono.ttf", "consola.ttf"] if mono else (["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"])
    for n in names:
        try:
            return ImageFont.truetype(str(FONTS / n), size)
        except OSError:
            continue
    for n in (["DejaVuSansMono.ttf"] if mono else ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]):
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t: float):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def render(r: Review, palette: dict) -> bytes:
    p = palette["dark"]
    bg, tile, fg, muted, line, accent = (_hex(p[k]) for k in ("bg", "tile", "fg", "muted", "line", "accent"))
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    # En-tête
    d.text((PAD, 64), "JGARMINTRACKER", font=_font(26, mono=True), fill=accent)
    d.text((PAD - 6, 96), str(r.year), font=_font(170, bold=True), fill=fg)
    sub = "Mon année sportive" + (f" · au {r.end:%d/%m}" if r.partial else "")
    d.text((PAD, 296), sub, font=_font(36), fill=muted)

    # Quatre grands chiffres
    stats = [("sorties", units.number(r.totals.count)), ("km", units.number(r.totals.distance_m / 1000)),
             ("heures", units.number(r.totals.duration_s / 3600)), ("m de D+", units.number(r.totals.elevation_m))]
    cw = (W - 2 * PAD - 3 * 20) / 4
    y = 380
    for k, (label, value) in enumerate(stats):
        x = PAD + k * (cw + 20)
        d.rounded_rectangle((x, y, x + cw, y + 150), 18, fill=tile)
        d.text((x + 24, y + 22), value, font=_font(54, bold=True), fill=fg)
        d.text((x + 24, y + 96), label, font=_font(26), fill=muted)
    dk = delta(r.totals.distance_m, r.prev.distance_m)
    if dk is not None:
        txt = f"{'+' if dk >= 0 else '−'}{units.number(abs(dk))} % de km par rapport à {r.prev_label}"
        d.text((PAD, y + 168), txt, font=_font(26), fill=accent if dk >= 0 else muted)

    # Familles : barre de la part du temps
    y = 610
    for fl in r.families[:3]:
        name = fl.family.name
        val = f"{units.number(fl.totals.distance_m / 1000)} km · {units.hmm(fl.totals.duration_s)}"
        d.text((PAD, y), name, font=_font(30, bold=True), fill=fg)
        d.text((W - PAD - d.textlength(val, font=_font(28)), y + 2), val, font=_font(28), fill=muted)
        d.rounded_rectangle((PAD, y + 46, W - PAD, y + 58), 6, fill=line)
        d.rounded_rectangle((PAD, y + 46, PAD + max((W - 2 * PAD) * fl.share / 100, 12), y + 58), 6, fill=accent)
        y += 84

    # Calendrier de l'année
    y = max(y + 10, 870)
    d.text((PAD, y), "Chaque jour de l'année", font=_font(26), fill=muted)
    y += 44
    weeks = r.calendar
    cell = (W - 2 * PAD) / len(weeks)
    size = cell - 3
    levels = [_mix(tile, accent, t) for t in (0, 0.3, 0.55, 0.8, 1.0)]
    for i, col in enumerate(weeks):
        for j, c in enumerate(col):
            if c is None:
                continue
            x0, y0 = PAD + i * cell, y + j * cell
            fill = _mix(bg, tile, 0.5) if c["future"] else levels[c["level"]]
            d.rounded_rectangle((x0, y0, x0 + size, y0 + size), 3, fill=fill)
    y += 7 * cell + 34

    # Faits marquants
    facts = []
    if r.longest:
        facts.append(("Plus longue sortie", f"{units.km(r.longest.distance_m)} · {r.longest.start:%d/%m}"))
    if r.best_month:
        facts.append(("Mois record", f"{units.MONTHS[r.best_month['month'] - 1]} · {units.hmm(r.best_month['hours'] * 3600)}"))
    if r.best_streak:
        facts.append(("Plus longue série", f"{r.best_streak} semaines actives"))
    if r.gear:
        facts.append(("Matériel", f"{r.gear[0][0].name} · {units.number(r.gear[0][1])} km"))
    elif r.friends:
        facts.append(("Avec", f"{r.friends[0][0].name} · {r.friends[0][1]} sorties"))
    colw = (W - 2 * PAD) / 2
    for k, (label, value) in enumerate(facts[:4]):
        x = PAD + (k % 2) * colw
        yy = y + (k // 2) * 88
        d.text((x, yy), label, font=_font(24), fill=muted)
        d.text((x, yy + 32), value, font=_font(32, bold=True), fill=fg)

    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()
