"""0.5.0 : domicile et lieux sur la carte, page Historique (récupération des périodes anciennes)."""

import json
from datetime import date

import pytest
from sqlalchemy import func, select

from jgarmintracker import db as dbm
from jgarmintracker import settings, tracks
from jgarmintracker.models import Activity, ActivityTrack, DailyHealth
from jgarmintracker.stats import coverage
from jgarmintracker.sync import sync, sync_history
from jgarmintracker.web import create_app

from .conftest import TODAY, FakeSource


def test_home_point_picks_most_frequent_area():
    home = [(0.10001, 0.20001), (0.10002, 0.19999), (0.10000, 0.20002)]
    away = [(0.5, 0.5), (0.9, 0.1)]
    assert tracks.home_point(home + away) == pytest.approx((0.10001, 0.20001), abs=1e-4)
    assert tracks.home_point([]) is None


def test_home_auto_then_manual(synced):
    point, manual = settings.home(synced)
    assert point and not manual
    settings.put(synced, "home", [0.5, 0.6])
    assert settings.home(synced) == ([0.5, 0.6], True)


def test_sync_history_fills_older_period_and_resumes(session):
    sync(session, FakeSource(), today=TODAY, history_days=7)  # base « récente » : une semaine
    before = session.scalar(select(func.count(Activity.id)))
    run = sync_history(session, FakeSource(fail_on=date(2025, 6, 1)), date(2025, 5, 20), date(2025, 6, 10))
    assert run.status == "error" and "429" in run.message and run.mode == "history"
    assert session.get(DailyHealth, date(2025, 5, 31)) and not session.get(DailyHealth, date(2025, 6, 1))
    source = FakeSource()
    run = sync_history(session, source, date(2025, 5, 20), date(2025, 6, 10))
    assert run.status == "ok" and source.days_asked[0] == date(2025, 6, 1)  # jours déjà en base sautés
    run = sync_history(session, FakeSource(), date(2025, 1, 1), date(2025, 4, 30), health=False)
    assert run.activities_added > 0 and session.scalar(select(func.count(Activity.id))) > before
    assert run.tracks_added > 0
    cov = coverage(session)
    assert cov[(2025, 2)]["activities"] == 4 and cov[(2025, 2)]["tracks"] > 0 and cov[(2025, 5)]["days"] == 12


@pytest.fixture
def client(tmp_path, monkeypatch):
    class FrozenDate(date):
        @classmethod
        def today(cls):
            return TODAY

    monkeypatch.setattr("jgarmintracker.web.date", FrozenDate)
    monkeypatch.setattr("jgarmintracker.sync.date", FrozenDate)
    app = create_app(tmp_path / "web.db")
    app.config.update(TESTING=True, SYNC_INLINE=True, SYNC_SOURCE=FakeSource)
    with dbm.new_session() as s:
        settings.put(s, "history_months", 1)
        s.commit()
    c = app.test_client()
    c.post("/sync")
    return c


def test_map_places_and_home(client):
    html = client.get("/map?months=24").get_data(as_text=True)
    assert 'id="place"' in html and "Autour de chez moi" in html
    start = html.index('routesMap("routes-map", ') + len('routesMap("routes-map", ')
    _, end = json.JSONDecoder().raw_decode(html[start:])
    home, _ = json.JSONDecoder().raw_decode(html[start + end:].lstrip(", "))
    assert home and abs(home[0]) < 1 and abs(home[1]) < 1  # tracés inventés autour de 0° / 0°
    assert "Lieu inconnu" in html  # les fixtures n'ont pas de locationName
    client.post("/settings/home", data={"lat": "0.33", "lon": "0.44"})
    assert "[0.33, 0.44]" in client.get("/map").get_data(as_text=True)
    assert "Revenir au calcul automatique" in client.get("/settings?tab=activities").get_data(as_text=True)
    client.post("/settings/home", data={"reset": "1"})
    with dbm.new_session() as s:
        assert settings.home(s)[1] is False
    r = client.post("/settings/home", data={"lat": "abc", "lon": ""}, follow_redirects=True)
    assert "Clique sur la carte" in r.get_data(as_text=True)


def test_history_page_and_start(client):
    html = client.get("/history").get_data(as_text=True)
    assert "Couverture" in html and 'data-ym="2025-06"' in html and 'data-year="2023"' in html
    assert client.get("/history?from_year=2019").get_data(as_text=True).count('class="linkish year-pick"') == 7
    r = client.post("/history", data={"from": "2025-01", "to": "2025-04", "activities": "on"}, follow_redirects=True)
    assert "Récupération lancée" in r.get_data(as_text=True)
    with dbm.new_session() as s:
        assert s.scalar(select(func.count(Activity.id)).where(Activity.start < "2025-05-01")) == 17
        assert s.scalar(select(func.count()).select_from(ActivityTrack)) > 0
    assert "Historique du 01/01/2025 au 30/04/2025" in client.get("/history").get_data(as_text=True)
    r = client.post("/history", data={"from": "2025-01", "to": "2025-02"}, follow_redirects=True)
    assert "Coche au moins" in r.get_data(as_text=True)
    r = client.post("/history", data={"from": "", "to": ""}, follow_redirects=True)
    assert "Choisis un mois" in r.get_data(as_text=True)
    assert "historique" in client.get("/sync").get_data(as_text=True)


def test_cli_history_without_session(tmp_path):
    from typer.testing import CliRunner

    from jgarmintracker.cli import app

    result = CliRunner().invoke(app, ["--db", str(tmp_path / "c.db"), "history", "--from", "2024-01", "--to", "2024-03"])
    assert result.exit_code == 1 and "jgarmin login" in result.output
