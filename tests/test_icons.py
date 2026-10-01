"""0.8.0 : icônes des familles et des sports."""

import re
from pathlib import Path

import pytest
from sqlalchemy import select

from jgarmintracker import db as dbm
from jgarmintracker.icons import ICONS, guess_icon, valid
from jgarmintracker.models import Sport, SportFamily
from jgarmintracker.upgrades import assign_icons
from jgarmintracker.web import create_app

from .conftest import TODAY, FakeSource

STATIC = Path(__file__).resolve().parent.parent / "jgarmintracker" / "web" / "static"


def sport(s, family, name):
    return s.scalar(select(Sport).join(Sport.family).where(SportFamily.name == family, Sport.name == name))


def test_every_icon_has_a_css_rule():
    css = (STATIC / "icons.css").read_text(encoding="utf-8")
    declared = set(re.findall(r"\.ph-([a-z0-9-]+):before", css))
    assert set(ICONS) <= declared and declared - set(ICONS) == {"lock-simple", "download-simple"} and (STATIC / "Phosphor.woff2").stat().st_size > 100_000


def test_guess_icon():
    assert guess_icon("Course à pied") == "person-simple-run"
    assert guess_icon("Trail") == "mountains" and guess_icon("Tapis") == "sneaker-move"
    assert guess_icon("Vélo électrique") == "scooter" and guess_icon("VÉLO") == "bicycle"
    assert guess_icon("Marche & rando") == "person-simple-hike" and guess_icon("Marche") == "person-simple-walk"
    assert guess_icon("Musculation") == "barbell" and guess_icon("Yoga") == "person-simple-tai-chi"
    assert guess_icon("Route") is None and guess_icon(None, "Natation") == "person-simple-swim"
    assert valid("bicycle") == "bicycle" and valid("<script>") is None and valid("") is None


def test_seed_icons(session):
    assert session.scalar(select(SportFamily).where(SportFamily.name == "Vélo")).icon == "bicycle"
    route = sport(session, "Vélo", "Route")
    assert route.icon is None and route.icon_name == "bicycle"  # comme la famille
    assert sport(session, "Course", "Trail").icon_name == "mountains"
    assert sport(session, "Autre", "Autre").icon_name == "pulse"


def test_existing_db_gets_icons(session):
    for fam in session.scalars(select(SportFamily)):
        fam.icon = None
    for sp in session.scalars(select(Sport)):
        sp.icon = None
    session.scalar(select(SportFamily).where(SportFamily.name == "Course")).name = "Course à pied"
    assign_icons(session)
    assert sport(session, "Course à pied", "Route").icon_name == "person-simple-run"
    assert sport(session, "Natation", "Piscine").icon == "swimming-pool"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from datetime import date

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


def test_pick_icons_in_sports_page(client):
    html = client.get("/sports").get_data(as_text=True)
    assert 'class="icon-pick"' in html and html.count('name="icon" value="barbell"') >= 3
    assert "Comme la famille (Vélo)" in html
    with dbm.new_session() as s:
        velo = s.scalar(select(SportFamily).where(SportFamily.name == "Vélo"))
        vtt = sport(s, "Vélo", "VTT")
        fam_id, vtt_id = velo.id, vtt.id
    client.post(f"/families/{fam_id}/rename", data={"name": "Vélo", "icon": "person-simple-bike"})
    client.post(f"/sports/{vtt_id}/update", data={"name": "VTT", "family_id": fam_id, "pace_unit": "kmh",
                                                  "color": "#1B5E9E", "icon": ""})
    with dbm.new_session() as s:
        assert sport(s, "Vélo", "VTT").icon_name == "person-simple-bike"  # suit la famille
        assert sport(s, "Vélo", "Route").icon_name == "person-simple-bike"
    client.post(f"/sports/{vtt_id}/update", data={"name": "VTT", "family_id": fam_id, "pace_unit": "kmh",
                                                  "color": "#1B5E9E", "icon": "pas-une-icone"})
    with dbm.new_session() as s:
        assert sport(s, "Vélo", "VTT").icon is None  # valeur inconnue refusée
    listing = client.get("/activities").get_data(as_text=True)
    assert 'class="ph ph-person-simple-bike" style=' in listing and "icons.css" in listing
