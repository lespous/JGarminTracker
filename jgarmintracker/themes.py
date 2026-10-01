"""Palettes de couleurs (mêmes 8 couleurs que les thèmes de Labs) et CSS du thème actif.

Une palette = 8 couleurs pour le mode clair et 8 pour le sombre :
  bg (fond), surface (zones en retrait), tile (cartes et panneaux), fg (texte), muted (texte secondaire),
  line (bordures), accent, accent_fg (texte sur l'accent).
Les palettes de Labs viennent de site-perso/server/app/themes.php ; « Sarcelle » est celle de JBudget.
"""

from __future__ import annotations

import re

KEYS = {
    "bg": "Fond",
    "surface": "Surface (zones en retrait)",
    "tile": "Cartes et panneaux",
    "fg": "Texte",
    "muted": "Texte secondaire",
    "line": "Bordures",
    "accent": "Accent",
    "accent_fg": "Texte sur l'accent",
}


def _p(light: str, dark: str) -> dict:
    return {"light": dict(zip(KEYS, light.split())), "dark": dict(zip(KEYS, dark.split()))}


DEFAULT_PALETTE = "Sarcelle"
PALETTES: dict[str, dict] = {
    "Sarcelle": _p("#f3f5f6 #ebeff1 #ffffff #18212b #5a6572 #d9dfe4 #2a6b62 #ffffff",
                   "#12181d #222c34 #1a2229 #e4eaee #98a5b0 #2c3740 #6fc0b2 #0f1a18"),
    "Graphite": _p("#f6f6f7 #ececef #fbfbfc #18181b #55555e #d9d9de #c2410c #fbfbfc",
                   "#0d0d10 #17171b #131316 #ececef #a1a1aa #2a2a30 #fb8a4c #0d0d10"),
    "Forêt": _p("#f4f6f4 #e7ece8 #fafbfa #15201a #4d5b52 #d3dbd5 #1f7a4d #fafbfa",
                "#0c120f #141d18 #101814 #e6ede8 #9aaba0 #24302a #5cc98f #0c120f"),
    "Cobalt": _p("#f5f6f8 #e9ecf2 #fbfcfd #111827 #4b5563 #d6dbe4 #1d4ed8 #fbfcfd",
                 "#0b0e14 #141a24 #10151e #e8ecf3 #9aa4b5 #252d3b #6f9bff #0b0e14"),
    "Terminal": _p("#f3f4f1 #e6e8e2 #f9faf8 #171a14 #50564a #d0d4c9 #4d7c0f #f9faf8",
                   "#0a0b09 #12140f #0f110d #e3e7dc #98a08c #23271e #a3e635 #0a0b09"),
    "Encre et cobalt": _p("#eef0f4 #e3e6ee #fcfcfd #12141a #565c6b #dadee6 #2f4bff #fcfcfd",
                          "#0b0c10 #1b1e26 #14161c #e8eaf0 #979cab #262a34 #7b8dff #0b0c10"),
    "Vert sapin": _p("#f6f8f6 #e7ede8 #fbfcfb #122019 #4d5c54 #d3ddd5 #1c7a4f #f6f8f6",
                     "#0b1310 #121d18 #0f1814 #e2ebe5 #93a69b #21302a #5bc793 #0b1310"),
    "Ardoise et ambre": _p("#eef0f3 #f8f9fb #f8f9fb #14171e #525a68 #d4d8df #a65c06 #f8f9fb",
                           "#111318 #1a1d24 #1a1d24 #e1e4ea #8e96a6 #2a2e38 #f2a83b #111318"),
    "Papier froid et framboise": _p("#f5f6f8 #e7e9ee #f9fafb #101114 #555a64 #d5d8de #cf1f59 #f9fafb",
                                    "#111215 #1d1e23 #16171b #ededf0 #9b9ea8 #2c2e34 #ff5c8e #111215"),
}

# Couleurs de sens (hausse, baisse, alerte) : indépendantes de la palette, une série par mode.
SEMANTIC = {
    "light": {"out": "#a8413a", "in": "#2d7a4c", "warn": "#9a6614", "warn-soft": "#f6ead2", "err-soft": "#f6dedb"},
    "dark": {"out": "#e08a82", "in": "#7cc99a", "warn": "#e0b060", "warn-soft": "#3a3020", "err-soft": "#3e2422"},
}

HEX = re.compile(r"^#[0-9a-f]{6}$")


class PaletteError(ValueError):
    pass


def normalize(colors: dict, strict: bool = False) -> dict:
    """{light: {8 clés}, dark: {8 clés}} validé. Clés manquantes : déduites comme dans Labs (tile, accent_fg = bg)."""
    base = PALETTES[DEFAULT_PALETTE]
    out: dict = {}
    for mode in ("light", "dark"):
        src = (colors or {}).get(mode) or {}
        out[mode] = {}
        for k in KEYS:
            v = str(src.get(k) or "").strip().lower()
            if not HEX.match(v):
                if strict and v:
                    raise PaletteError(f"{mode}.{k} : couleur attendue au format #rrggbb (reçu « {v} »).")
                v = out[mode]["bg"] if k in ("tile", "accent_fg") and "bg" in out[mode] else base[mode][k]
            out[mode][k] = v
    return out


def _lum(hex_: str) -> float:
    def ch(c: int) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def contrast_warnings(pal: dict) -> list[str]:
    """Paires de couleurs sous le seuil de lisibilité WCAG (4,5:1 texte, 3:1 texte secondaire)."""
    out = []
    names = {"light": "clair", "dark": "sombre"}
    for mode, c in pal.items():
        for fg, bg, label, minimum in (("fg", "bg", "texte sur le fond", 4.5), ("fg", "tile", "texte sur les cartes", 4.5),
                                       ("muted", "tile", "texte secondaire sur les cartes", 3.0),
                                       ("accent_fg", "accent", "texte sur l'accent", 4.5)):
            ratio = contrast(c[fg], c[bg])
            if ratio < minimum:
                out.append(f"Mode {names[mode]} : {label} peu lisible ({str(ratio).replace('.', ',')}:1, "
                           f"minimum conseillé {str(minimum).replace('.', ',')}:1).")
    return out


def _vars(c: dict, mode: str) -> str:
    v = {
        "bg": c["bg"], "surface": c["tile"], "soft": c["surface"], "ink": c["fg"], "muted": c["muted"],
        "line": c["line"], "accent": c["accent"], "accent-ink": c["accent_fg"],
        "accent-soft": f"color-mix(in oklab, {c['accent']} 16%, {c['tile']})",
        **SEMANTIC[mode],
    }
    return "".join(f"--{k}:{val};" for k, val in v.items()) + f"color-scheme:{mode};"


def theme_css(pal: dict, mode: str) -> str:
    """CSS des variables de l'interface. mode : system | light | dark (attribut data-mode sur <html>)."""
    pal = normalize(pal)
    light, dark = _vars(pal["light"], "light"), _vars(pal["dark"], "dark")
    if mode == "dark":
        return f"html:root{{{dark}}}"
    if mode == "light":
        return f"html:root{{{light}}}"
    return f"html:root{{{light}}}@media (prefers-color-scheme: dark){{html:root{{{dark}}}}}"


def parse_import(text: str) -> list[dict]:
    """JSON de Labs (réglage « palettes ») -> [{name, light, dark}].

    Accepte la liste stockée par Labs, une seule palette, ou un objet {nom: {light, dark}}.
    """
    import json

    try:
        data = json.loads(text)
    except ValueError as e:
        raise PaletteError(f"JSON illisible : {e}") from e
    if isinstance(data, dict) and "light" in data:
        data = [data]
    elif isinstance(data, dict):
        data = [{"name": k, **v} for k, v in data.items() if isinstance(v, dict)]
    if not isinstance(data, list) or not data:
        raise PaletteError("Aucune palette trouvée : colle la liste JSON des palettes de Labs.")
    out = []
    for i, item in enumerate(data, 1):
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            raise PaletteError(f"Palette n° {i} : nom manquant.")
        out.append({"name": str(item["name"]).strip()[:60], **normalize(item, strict=True)})
    return out
