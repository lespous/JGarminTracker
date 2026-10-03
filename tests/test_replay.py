"""0.18.0 : rejouer une sortie (données point par point à la demande, sens du parcours)."""

from sqlalchemy import select

from jgarmintracker import db as dbm
from jgarmintracker.garmin import RateLimited
from jgarmintracker.models import Activity, ActivityStream

from .conftest import FakeSource
from .test_friends import act_id, client  # noqa: F401  (fixture client réutilisée)
from .test_segments import fake_details


def test_stream_on_demand(client):  # noqa: F811
    run = act_id("Course du soir 24")
    with dbm.new_session() as s:
        gid = s.get(Activity, run).garmin_id
    FakeSource.DETAILS = {gid: fake_details([(50.0, 4.0), (50.0, 4.01), (50.01, 4.01)], 3.0)}
    try:
        page = client.get(f"/activities/{run}").get_data(as_text=True)
        assert 'id="replay"' in page and "replayPlayer(map" in page and f"/activities/{run}/stream.json" in page
        r = client.get(f"/activities/{run}/stream.json")
        data = r.get_json()
        assert r.status_code == 200 and len(data["samples"]) > 100 and data["samples"][0][0] == 0
        assert data["samples"][-1][5] is not None  # altitude
        FakeSource.DETAILS = {}  # deuxième fois : depuis la base, sans appel
        assert client.get(f"/activities/{run}/stream.json").get_json()["samples"] == data["samples"]
        with dbm.new_session() as s:
            assert s.get(ActivityStream, run).n == len(data["samples"])
        # Garmin n'a rien : liste vide, gardée pour ne pas redemander.
        other = act_id("Course du soir 23")
        assert client.get(f"/activities/{other}/stream.json").get_json() == {"samples": []}
        with dbm.new_session() as s:
            assert s.get(ActivityStream, other).n == 0
    finally:
        FakeSource.DETAILS = {}


def test_stream_garmin_error(client, monkeypatch):  # noqa: F811
    def boom(self, garmin_id):
        raise RateLimited()

    monkeypatch.setattr(FakeSource, "details", boom)
    run = act_id("Vélo dimanche")
    r = client.get(f"/activities/{run}/stream.json")
    assert r.status_code == 503 and r.get_json()["samples"] == [] and r.get_json()["error"]
    with dbm.new_session() as s:
        assert s.get(ActivityStream, run) is None  # rien de gardé : on réessaiera


def test_route_page_has_player(client):  # noqa: F811
    from .test_routes_weather import add, loop
    from jgarmintracker import routes
    from jgarmintracker.models import RouteGroup

    with dbm.new_session() as s:
        sport_id = s.scalar(select(Activity.sport_id).where(Activity.name == "Course du soir 1"))
        for k in range(2):
            add(s, f"Tour {k}", loop(10), 10.0, 50, k, sport_id)
        routes.rebuild(s)
        s.commit()
        g = s.scalar(select(RouteGroup))
        gid, rep = g.id, g.rep_activity_id
    html = client.get(f"/routes/{gid}").get_data(as_text=True)
    assert 'id="replay"' in html and f"/activities/{rep}/stream.json" in html
