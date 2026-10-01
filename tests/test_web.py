from datetime import date

import pytest
from sqlalchemy import select

from jgarmintracker import db as dbm
from jgarmintracker.garmin import SessionExpired
from jgarmintracker.models import Activity, Sport, SportFamily, SportRule, SyncRun, Tag
from jgarmintracker.web import create_app

from .conftest import TODAY, FakeSource


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Les pages calculent « aujourd'hui » : on le fige sur la date des fixtures.
    class FrozenDate(date):
        @classmethod
        def today(cls):
            return TODAY

    monkeypatch.setattr("jgarmintracker.web.date", FrozenDate)
    monkeypatch.setattr("jgarmintracker.sync.date", FrozenDate)
    app = create_app(tmp_path / "web.db")
    app.config.update(TESTING=True, SYNC_INLINE=True, SYNC_SOURCE=FakeSource)
    return app


@pytest.fixture
def client(app):
    c = app.test_client()
    assert c.post("/sync").status_code == 302  # synchro avec FakeSource, sans réseau
    return c


def ids(family, name):
    with dbm.new_session() as s:
        return s.scalar(select(Sport.id).join(Sport.family).where(SportFamily.name == family, Sport.name == name))


def test_empty_db_shows_welcome(app):
    r = app.test_client().get("/")
    assert r.status_code == 200 and "jgarmin login".encode() in r.data


def test_pages_render(client):
    with dbm.new_session() as s:
        act_id = s.scalar(select(Activity.id))
    f_course = f"f{dbm.new_session().scalar(select(SportFamily.id).where(SportFamily.name == 'Course'))}"
    for url in ["/", "/?metric=distance", "/activities", "/activities?sport=" + f_course + "&q=course&dmin=5&tmax=90",
                "/activities?from=2025-06-01&to=2025-06-18&dmin=abc", f"/activities/{act_id}",
                "/progress", "/progress?sport=" + f_course + "&months=6", "/progress?months=24",
                f"/progress?sport=s{ids('Vélo', 'Route')}", f"/progress?sport=s{ids('Natation', 'Piscine')}",
                f"/progress?sport=s{ids('Renforcement', 'Musculation')}",
                "/health", "/health?days=90", "/health?days=365", "/sports", "/sports?edit=1", "/sports?confirm=2",
                "/sports/rules/test?field=name&match_type=contains&pattern=course&sport_id=1",
                "/tags", "/sync", "/sync/status"]:
        r = client.get(url)
        assert r.status_code == 200, url


def test_sport_selects_are_filled(client):
    import re

    html = client.get("/activities").get_data(as_text=True)
    selects = re.findall(r'<select class="sport".*?</select>', html, re.S)
    assert selects and all("Home trainer" in s for s in selects)
    bulk = re.search(r'<select name="sport_id" aria-label="Sport pour les activités cochées">.*?</select>', html, re.S)
    assert "Musculation" in bulk.group(0)


def test_progress_periods(client):
    for url in ["/progress?period=ytd", "/progress?period=last_year", "/progress?period=all", "/progress?months=6",
                "/progress?period=custom&from=2025-06-20&to=2025-01-01", "/progress?period=custom&from=abc",
                "/progress?period=3m&from=2020-01-01"]:
        assert client.get(url).status_code == 200, url
    html = client.get("/progress?period=custom&from=2025-03-01&to=2025-03-31").get_data(as_text=True)
    assert "du 01/03/2025 au 31/03/2025" in html and "par semaine" in html and "période préc." in html
    html = client.get("/progress?period=ytd").get_data(as_text=True)
    assert "Période analysée : du 01/01/2025 au 18/06/2025" in html and "par mois" in html
    assert 'value="ytd" selected' in html
    assert "Aucune activité" in client.get("/progress?period=last_year").get_data(as_text=True)


def test_dashboard_shows_week_and_charts(client):
    html = client.get("/").get_data(as_text=True)
    assert "Semaine du 16/06/2025" in html
    assert "Volume des 12 dernières semaines" in html and "Course › Trail" in html


def test_activity_detail_shows_extras(client):
    with dbm.new_session() as s:
        bike = s.scalar(select(Activity.id).where(Activity.name == "Vélo dimanche"))
        run = s.scalar(select(Activity.id).where(Activity.name == "Course du soir 24"))
    html = client.get(f"/activities/{bike}").get_data(as_text=True)
    for text in ("Vitesse max", "Dénivelé −", "Zone 3 · Aérobie", "Meilleurs temps", "40 km", "record personnel"):
        assert text in html, text
    html = client.get(f"/activities/{run}").get_data(as_text=True)
    for text in ("Allure max", "Cadence moyenne", "Longueur de foulée", "1 km", "5 km"):
        assert text in html, text
    progress = client.get("/progress").get_data(as_text=True)
    assert "Meilleur 1 km" in progress and "Allure max" in progress


def test_maps(client):
    import json
    import re

    with dbm.new_session() as s:
        outdoor = s.scalar(select(Activity.id).where(Activity.name == "Course du soir 1"))
        indoor = s.scalar(select(Activity.id).where(Activity.name == "Renfo maison"))
    html = client.get(f"/activities/{outdoor}").get_data(as_text=True)
    assert 'id="track-map"' in html and "leaflet.js" in html
    assert 'id="track-map"' not in client.get(f"/activities/{indoor}").get_data(as_text=True)
    listing = client.get("/activities").get_data(as_text=True)
    assert listing.count('<td class="preview"><a') == 25
    html = client.get("/map?months=24").get_data(as_text=True)
    start = html.index('routesMap("routes-map", ') + len('routesMap("routes-map", ')
    routes, _ = json.JSONDecoder().raw_decode(html[start:])
    assert len(routes) == 25 and all(len(r["points"]) >= 2 and r["color"].startswith("#") for r in routes)
    with dbm.new_session() as s:
        course = f"f{s.scalar(select(SportFamily.id).where(SportFamily.name == 'Course'))}"
    for url in ["/map", f"/map?sport={course}&months=0", "/map?months=1"]:
        assert client.get(url).status_code == 200, url


def test_sync_page_logs_run(client):
    html = client.get("/sync").get_data(as_text=True)
    assert "32 activité(s)" in html and "terminée" in html


def test_sync_without_tokens_explains_login(app):
    def no_session():
        raise SessionExpired()

    app.config["SYNC_SOURCE"] = no_session
    c = app.test_client()
    c.post("/sync")
    assert "jgarmin login" in c.get("/sync/status").get_data(as_text=True)
    with dbm.new_session() as s:
        assert s.scalar(select(SyncRun.status)) == "error"


def test_change_sport_one_activity_locks_it(client):
    yoga = ids("Renforcement", "Yoga")
    with dbm.new_session() as s:
        act = s.scalar(select(Activity).where(Activity.name == "Paddle lac"))
    r = client.get(f"/activities/{act.id}/sport?sport_id={yoga}")
    assert r.status_code == 200 and "Yoga" in r.get_data(as_text=True)
    client.post(f"/activities/{act.id}/sport", data={"sport_id": yoga, "scope": "one", "next": "/activities"})
    with dbm.new_session() as s:
        a = s.get(Activity, act.id)
        assert a.sport_id == yoga and a.sport_locked and a.sport_source == "manual"
    client.post(f"/activities/{act.id}/unlock")
    with dbm.new_session() as s:
        assert s.get(Activity, act.id).sport.label == "Autre"


def test_change_sport_by_type_creates_rule(client):
    other = ids("Autre", "Autre")
    with dbm.new_session() as s:
        act = s.scalar(select(Activity).where(Activity.type_key == "running"))
    client.post(f"/activities/{act.id}/sport", data={"sport_id": other, "scope": "type_key"})
    with dbm.new_session() as s:
        assert {a.sport_id for a in s.scalars(select(Activity).where(Activity.type_key == "running"))} == {other}
        assert s.scalar(select(SportRule).where(SportRule.pattern == "running", SportRule.origin == "learned"))


def test_bulk_sport_and_tags(client):
    trail = ids("Course", "Trail")
    with dbm.new_session() as s:
        picked = s.scalars(select(Activity.id).where(Activity.type_key == "running").limit(2)).all()
    client.post("/activities/bulk/sport", data={"act": picked, "sport_id": trail})
    client.post("/activities/bulk/tags", data={"act": picked, "tag": "Préparation", "action": "add"})
    with dbm.new_session() as s:
        acts = [s.get(Activity, i) for i in picked]
        assert all(a.sport_id == trail and a.sport_locked for a in acts)
        assert all([t.name for t in a.tags] == ["Préparation"] for a in acts)
        # Sans « créer une règle », les autres courses ne bougent pas.
        assert not s.scalar(select(SportRule).where(SportRule.origin == "learned"))
        tag_id = s.scalar(select(Tag.id))
    assert "Préparation" in client.get(f"/activities?tag={tag_id}").get_data(as_text=True)
    client.post(f"/tags/{tag_id}/delete")
    with dbm.new_session() as s:
        assert s.scalar(select(Tag)) is None and s.get(Activity, picked[0]) is not None


def test_rules_and_sports_management(client):
    piscine = ids("Natation", "Piscine")
    r = client.post("/sports/rules/save", data={"field": "name", "match_type": "contains", "pattern": "paddle",
                                                 "sport_id": piscine}, follow_redirects=True)
    assert "1 activité(s) reclassée(s)" in r.get_data(as_text=True)
    r = client.post("/sports/rules/save", data={"field": "name", "match_type": "regex", "pattern": "(",
                                                 "sport_id": piscine}, follow_redirects=True)
    assert "Expression régulière invalide" in r.get_data(as_text=True)
    client.post("/sports/add", data={"name": "Ski de fond", "new_family": "Hiver", "pace_unit": "kmh", "color": "#123456"})
    with dbm.new_session() as s:
        ski = s.scalar(select(Sport).where(Sport.name == "Ski de fond"))
        assert ski.family.name == "Hiver" and ski.color == "#123456"
    client.post(f"/sports/{piscine}/delete")
    with dbm.new_session() as s:
        assert s.get(Sport, piscine) is None
        assert s.scalar(select(Activity).where(Activity.name == "Piscine midi")).sport.label == "Autre"


def test_sports_order_and_family_delete(client):
    def order():
        with dbm.new_session() as s:
            fams = s.scalars(select(SportFamily).order_by(SportFamily.position)).all()
            return [f.name for f in fams], {f.name: [sp.name for sp in f.sports] for f in fams}

    fams, sports = order()
    assert fams[:2] == ["Course", "Vélo"]
    with dbm.new_session() as s:
        velo = s.scalar(select(SportFamily.id).where(SportFamily.name == "Vélo"))
        trail = s.scalar(select(Sport.id).where(Sport.name == "Trail"))
        natation = s.scalar(select(SportFamily.id).where(SportFamily.name == "Natation"))
    client.post(f"/families/{velo}/move?dir=up")
    client.post(f"/sports/{trail}/move?dir=up")
    fams, sports = order()
    assert fams[:2] == ["Vélo", "Course"] and sports["Course"][:2] == ["Trail", "Route"]
    client.post(f"/families/{velo}/move?dir=up")  # déjà en tête : rien ne bouge
    assert order()[0][0] == "Vélo"
    # Tri par utilisation : Course (24 + 2 sorties) avant Vélo, « Autre » toujours en dernier.
    client.post("/sports/sort-by-usage")
    fams, sports = order()
    assert fams[0] == "Course" and fams[-1] == "Autre" and sports["Course"][0] == "Route"
    # Supprimer une famille entière (confirmation, puis activités reclassées).
    html = client.get(f"/sports?confirm_family={natation}").get_data(as_text=True)
    assert "Supprimer la famille « Natation »" in html
    r = client.post(f"/families/{natation}/delete", follow_redirects=True)
    assert "Famille « Natation » supprimée avec 2 sport(s)" in r.get_data(as_text=True)
    assert "Natation" not in order()[0]
    with dbm.new_session() as s:
        assert s.scalar(select(Activity).where(Activity.name == "Piscine midi")).sport.label == "Autre"
        autre = s.scalar(select(SportFamily.id).where(SportFamily.name == "Autre"))
    r = client.post(f"/families/{autre}/delete", follow_redirects=True)
    assert "ne peut pas être supprimée" in r.get_data(as_text=True)


def test_fallback_sport_cannot_be_deleted(client):
    r = client.post(f"/sports/{ids('Autre', 'Autre')}/delete", follow_redirects=True)
    assert "ne peut pas être supprimé" in r.get_data(as_text=True)
