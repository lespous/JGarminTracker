"""Seul module qui importe `garminconnect` (bibliothèque non officielle, testée avec la version 0.3.17).

Si Garmin ou la bibliothèque changent, c'est ici seulement que le code bouge. `sync.py` ne voit qu'une
« source » avec quatre méthodes : activities_between, daily_summary, sleep, vo2max.

Le mot de passe n'est jamais écrit : seuls les jetons de session le sont, dans %USERPROFILE%\\.jgarmin\\tokens
(ou $JGARMIN_TOKENS), hors du dossier du projet.
"""

from __future__ import annotations

import functools
import logging
import os
from datetime import date
from pathlib import Path
from typing import Callable

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

try:  # 404 = pas de donnée ce jour-là ; classe présente dans les versions récentes seulement.
    from garminconnect import GarminConnectNotFoundError
except ImportError:  # pragma: no cover
    GarminConnectNotFoundError = None

# La bibliothèque journalise en WARNING des détails techniques : on garde l'écran propre.
logging.getLogger("garminconnect").setLevel(logging.ERROR)


class SyncError(Exception):
    """Erreur affichable telle quelle à l'utilisateur."""


class SessionExpired(SyncError):
    def __init__(self, detail: str = ""):
        super().__init__("Session Garmin expirée ou absente : lance `jgarmin login`." + (f" ({detail})" if detail else ""))


class RateLimited(SyncError):
    def __init__(self):
        super().__init__("Garmin refuse temporairement les requêtes (trop de demandes, erreur 429). "
                         "Attends une quinzaine de minutes puis relance la synchro : elle reprendra où elle s'est arrêtée.")


class GarminError(SyncError):
    pass


def tokens_dir() -> Path:
    return Path(os.environ.get("JGARMIN_TOKENS") or Path.home() / ".jgarmin" / "tokens")


def has_tokens() -> bool:
    return (tokens_dir() / "garmin_tokens.json").exists()


def _translate(func):
    """Traduit les exceptions de la bibliothèque en messages lisibles ; 404 -> None (pas de donnée)."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except GarminConnectAuthenticationError as e:
            raise SessionExpired() from e
        except GarminConnectTooManyRequestsError as e:
            raise RateLimited() from e
        except GarminConnectConnectionError as e:
            if GarminConnectNotFoundError and isinstance(e, GarminConnectNotFoundError):
                return None
            raise GarminError(f"Erreur de communication avec Garmin : {e}") from e

    return wrapper


def login(email: str, password: str, prompt_mfa: Callable[[], str]) -> str:
    """Connexion avec identifiants (et code MFA si le compte l'exige). Enregistre les jetons, renvoie le nom affiché."""
    api = Garmin(email, password, prompt_mfa=prompt_mfa)
    try:
        api.login()
    except GarminConnectAuthenticationError as e:
        raise GarminError(f"Connexion refusée par Garmin. Vérifie l'e-mail et le mot de passe. ({e})") from e
    except GarminConnectTooManyRequestsError as e:
        raise RateLimited() from e
    except GarminConnectConnectionError as e:
        raise GarminError(f"Connexion impossible : {e}") from e
    path = tokens_dir()
    path.mkdir(parents=True, exist_ok=True)
    api.client.dump(str(path))
    return api.get_full_name() or api.display_name or email


def logout() -> bool:
    """Supprime les jetons enregistrés. Renvoie True s'il y en avait."""
    f = tokens_dir() / "garmin_tokens.json"
    if f.exists():
        f.unlink()
        return True
    return False


class GarminSource:
    """Source réelle : appels à Garmin Connect via garminconnect."""

    pause = 0.4  # secondes entre deux jours, par politesse envers l'API

    def __init__(self, api: Garmin):
        self.api = api

    @classmethod
    def connect(cls) -> GarminSource:
        """Reprend la session depuis les jetons enregistrés. Ne demande jamais de mot de passe."""
        if not has_tokens():
            raise SessionExpired("aucun jeton enregistré")
        api = Garmin()
        try:
            api.login(str(tokens_dir()))
        except GarminConnectTooManyRequestsError as e:
            raise RateLimited() from e
        except (GarminConnectAuthenticationError, GarminConnectConnectionError) as e:
            raise SessionExpired() from e
        return cls(api)

    @property
    def user(self) -> str:
        return self.api.get_full_name() or self.api.display_name or ""

    @_translate
    def activities_between(self, start: date, end: date) -> list[dict]:
        return self.api.get_activities_by_date(start.isoformat(), end.isoformat(), sortorder="asc") or []

    @_translate
    def daily_summary(self, day: date) -> dict | None:
        """Résumé du jour : FC au repos, Body Battery, pas, stress."""
        try:
            return self.api.get_user_summary(day.isoformat())
        except GarminConnectConnectionError as e:
            if "No data received" in str(e):  # jour sans montre portée
                return None
            raise

    @_translate
    def sleep(self, day: date) -> dict | None:
        """Nuit terminée le matin de `day` (Garmin rattache la nuit au jour du réveil)."""
        return self.api.get_sleep_data(day.isoformat())

    @_translate
    def vo2max(self, start: date, end: date) -> list | dict | None:
        return self.api.get_max_metrics_range(start.isoformat(), end.isoformat())
