"""Photos (profil et amis) : recadrées en carré, réduites, gardées en JPEG dans la base. Jamais dans Git."""

from __future__ import annotations

import hashlib
import io

from PIL import Image, ImageOps, UnidentifiedImageError

SIZE = 256  # pixels de côté
MAX_UPLOAD = 20 * 1024 * 1024  # photo de téléphone comprise


class PhotoError(ValueError):
    pass


def process(data: bytes) -> bytes:
    """Image envoyée (JPEG, PNG, WebP, HEIC si pris en charge…) -> JPEG carré SIZE × SIZE, orientation corrigée."""
    if not data:
        raise PhotoError("Aucun fichier reçu.")
    if len(data) > MAX_UPLOAD:
        raise PhotoError("Photo trop lourde (20 Mo au maximum).")
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)  # photos de téléphone prises de côté
        img = ImageOps.fit(img.convert("RGB"), (SIZE, SIZE), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
    except (UnidentifiedImageError, OSError) as e:
        raise PhotoError("Fichier illisible : envoie une photo JPEG, PNG ou WebP.") from e
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


def etag(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:16]


def initials(*names: str | None) -> str:
    """« Marie Dupont » -> « MD » ; pour les avatars sans photo."""
    words = [w for n in names for w in (n or "").split() if w[:1].isalpha()]
    return "".join(w[0] for w in words[:2]).upper() or "?"


def hue(text: str) -> int:
    """Teinte stable (0-359) d'après un nom : la même personne garde la même couleur d'avatar."""
    return int(hashlib.md5((text or "").encode()).hexdigest()[:4], 16) % 360
