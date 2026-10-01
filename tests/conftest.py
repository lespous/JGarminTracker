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

    def __init__(self, fail_on: date | None = None):
        self.activities = json.loads((FIXTURES / "activities.json").read_text(encoding="utf-8"))
        self.summaries = json.loads((FIXTURES / "summaries.json").read_text(encoding="utf-8"))
        self.sleeps = json.loads((FIXTURES / "sleep.json").read_text(encoding="utf-8"))
        self.vo2 = json.loads((FIXTURES / "vo2max.json").read_text(encoding="utf-8"))
        self.fail_on = fail_on
        self.days_asked: list[date] = []

    def activities_between(self, start: date, end: date) -> list[dict]:
        return [a for a in self.activities if start.isoformat() <= a["startTimeLocal"][:10] <= end.isoformat()]

    def daily_summary(self, day: date):
        if self.fail_on and day >= self.fail_on:
            raise RateLimited()
        self.days_asked.append(day)
        return self.summaries.get(day.isoformat())

    def sleep(self, day: date):
        return self.sleeps.get(day.isoformat())

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
