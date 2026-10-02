import json
from datetime import date
from pathlib import Path

import pytest

from jgarmintracker import db as dbm
from jgarmintracker.garmin import RateLimited
from jgarmintracker.sync import sync

FIXTURES = Path(__file__).resolve().parent / "fixtures"
# Date de référence des fixtures (inventées) : un mercredi.
TODAY = date(2025, 6, 18)


class FakeSource:
    """Lit tests/fixtures/*.json au lieu d'appeler Garmin. Aucun accès réseau."""

    pause = 0

    def __init__(self, fail_on: date | None = None, tracks_before_429: int | None = None):
        self.activities = json.loads((FIXTURES / "activities.json").read_text(encoding="utf-8"))
        self.summaries = json.loads((FIXTURES / "summaries.json").read_text(encoding="utf-8"))
        self.sleeps = json.loads((FIXTURES / "sleep.json").read_text(encoding="utf-8"))
        self.vo2 = json.loads((FIXTURES / "vo2max.json").read_text(encoding="utf-8"))
        self.tracks = json.loads((FIXTURES / "tracks.json").read_text(encoding="utf-8"))
        self.fail_on = fail_on
        self.tracks_before_429 = tracks_before_429
        self.days_asked: list[date] = []
        self.tracks_asked: list[int] = []

    def activities_between(self, start: date, end: date) -> list[dict]:
        return [a for a in self.activities if start.isoformat() <= a["startTimeLocal"][:10] <= end.isoformat()]

    def daily_summary(self, day: date):
        if self.fail_on and day >= self.fail_on:
            raise RateLimited()
        self.days_asked.append(day)
        return self.summaries.get(day.isoformat())

    def sleep(self, day: date):
        return self.sleeps.get(day.isoformat())

    def track(self, garmin_id: int):
        if self.tracks_before_429 is not None and len(self.tracks_asked) >= self.tracks_before_429:
            raise RateLimited()
        self.tracks_asked.append(garmin_id)
        return self.tracks.get(str(garmin_id))

    DETAILS: dict[int, dict] = {}  # données point par point inventées, posées par les tests des segments
    details_asked: list[int] = []

    def details(self, garmin_id: int):
        self.details_asked = [*self.details_asked, garmin_id]
        return self.DETAILS.get(garmin_id)

    weather_before_429: int | None = None
    weather_asked: list[int] = []

    def weather(self, garmin_id: int):
        """Météo inventée, en °F et mph comme Garmin ; rien pour les sorties en salle (renfo, home trainer)."""
        if self.weather_before_429 is not None and len(self.weather_asked) >= self.weather_before_429:
            raise RateLimited()
        self.weather_asked = [*self.weather_asked, garmin_id]
        if garmin_id in (10000027, 10000031):
            return None
        n = garmin_id % 100
        return {"temp": 41 + n * 1.8, "apparentTemp": 39 + n * 1.8, "dewPoint": 40, "relativeHumidity": 70,
                "windSpeed": n % 20, "windGust": None, "windDirection": (n * 37) % 360,
                "weatherTypeDTO": {"desc": "Partly Cloudy" if n % 2 else "Unknown"}, "weatherStationDTO": {"id": "06999"}}

    def vo2max(self, start: date, end: date):
        return [v for v in self.vo2 if start.isoformat() <= v["generic"]["calendarDate"] <= end.isoformat()]


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Jetons et règles locales pointent vers un dossier temporaire : jamais ceux de l'utilisateur."""
    monkeypatch.setenv("JGARMIN_TOKENS", str(tmp_path / "tokens"))
    monkeypatch.setenv("JGARMIN_RULES", str(tmp_path / "sports.local.json"))
    monkeypatch.setenv("JGARMIN_DB", str(tmp_path / "env.db"))


@pytest.fixture
def session(tmp_path):
    dbm.init_db(tmp_path / "test.db")
    with dbm.new_session() as s:
        yield s


@pytest.fixture
def synced(session):
    """Base remplie avec les fixtures, historique de 180 jours."""
    run = sync(session, FakeSource(), today=TODAY, history_days=180)
    assert run.status == "ok", run.message
    return session
