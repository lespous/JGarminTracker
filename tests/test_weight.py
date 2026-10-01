"""0.10.0 : suivi du poids (pesées, IMC, objectif, rappel) et menu des sports en palette."""

from datetime import date, timedelta

import pytest

from jgarmintracker import db as dbm
from jgarmintracker import settings, weight
from jgarmintracker.models import Profile, WeightEntry
from jgarmintracker.web import create_app

from .conftest import TODAY, FakeSource


def test_add_replaces_same_day_and_updates_profile(session):
    weight.add(session, date(2025, 6, 1), 75.04)
    weight.add(session, date(2025, 6, 1), 74.8)
    weight.add(session, date(2025, 5, 20), 76.0)
    assert session.get(WeightEntry, date(2025, 6, 1)).weight_kg == 74.8
    assert session.get(Profile, 1).weight_kg == 74.8  # dernière pesée, pas la dernière saisie
    with pytest.raises(ValueError):
        weight.add(session, date(2025, 6, 2), 7)


def test_reminder(session):
    assert weight.reminder(session, TODAY) == weight.Reminder(True, None, 7)  # jamais pesé
    weight.add(session, TODAY - timedelta(days=3), 75)
    assert not weight.reminder(session, TODAY).due
    assert weight.reminder(session, TODAY + timedelta(days=4)).due
    settings.put(session, "weight_reminder_days", 0)
    assert not weight.reminder(session, TODAY + timedelta(days=40)).due


def test_series_and_summary(session):
    for i, kg in enumerate([80, 79.5, 79, 78.6, 78.2, 78, 77.2]):  # du 01/05 au 12/06/2025, chaque jeudi
        weight.add(session, date(2025, 5, 1) + timedelta(days=7 * i), kg)
    settings.put(session, "weight_goal", 75.0)
    s = weight.series(session, date(2025, 5, 20), TODAY, 180)
    assert s["labels"][0] == "22/05/25" and s["weight"][0] == 78.6
    assert s["avg"][0] == pytest.approx((80 + 79.5 + 79 + 78.6) / 4, abs=0.01)  # moyenne avec les pesées d'avant
    assert s["bmi"][0] == 24.3
    sm = weight.summary(session, date(2025, 5, 20), TODAY, 180)
    assert sm.change == -1.4 and sm.last.weight_kg == 77.2 and sm.to_goal == -2.2 and sm.count == 4
    assert weight.bmi_label(sm.bmi) == "corpulence normale"


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
    c = app.test_client()
    c.post("/sync")
    return c


def test_weight_pages(client):
    home = client.get("/").get_data(as_text=True)
    assert "Pesée de la semaine" in home and 'class="due-dot"' in home  # rappel : jamais pesé
    r = client.post("/weight/add", data={"weight_kg": "74,6", "next": "/"}, follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "Pesée du 18/06/2025 enregistrée : 74,6 kg" in html and "Pesée de la semaine" not in html
    assert 'class="due-dot"' not in html
    client.post("/weight/add", data={"day": "2025-06-04", "weight_kg": "75,4"})
    client.post("/profile", data={"height_cm": "180"})
    page = client.get("/health").get_data(as_text=True)
    assert 'id="weight-chart"' in page and "−0,8 kg" in page.replace("-0,8", "−0,8") and "23,0" in page
    # Validation
    for data, msg in (({"weight_kg": "abc"}, "Indique ton poids"), ({"weight_kg": "500"}, "entre 25 et 300"),
                      ({"weight_kg": "70", "day": "2030-01-01"}, "dans le futur")):
        assert msg in client.post("/weight/add", data=data, follow_redirects=True).get_data(as_text=True)
    # Suppression avec confirmation
    assert "Confirmer la suppression" in client.get("/health?confirm_weight=2025-06-18").get_data(as_text=True)
    client.post("/weight/2025-06-18/delete")
    with dbm.new_session() as s:
        assert s.get(WeightEntry, date(2025, 6, 18)) is None and s.get(Profile, 1).weight_kg == 75.4


def test_weight_settings(client):
    r = client.post("/settings/weight", data={"weight_reminder_days": "10", "weight_goal": "72,5"}, follow_redirects=True)
    assert "Réglages du poids enregistrés" in r.get_data(as_text=True)
    with dbm.new_session() as s:
        assert settings.get(s, "weight_reminder_days") == 10 and settings.get(s, "weight_goal") == 72.5
    assert "entre 0 (pas de rappel) et 90" in client.post(
        "/settings/weight", data={"weight_reminder_days": "-1"}, follow_redirects=True).get_data(as_text=True)
    client.post("/settings/weight", data={"weight_reminder_days": "0", "weight_goal": ""})
    assert "Pesée de la semaine" not in client.get("/").get_data(as_text=True)


def test_sport_menu_is_icon_palette(client):
    html = client.get("/activities").get_data(as_text=True)
    assert html.count('class="sm-tile"') == 13 and 'style="--c: #2E86DE"' in html
