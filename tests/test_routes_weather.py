"""0.13.0 : parcours répétés (même tracé, même sens) et météo au départ des sorties."""

import json
import math
from datetime import datetime, timedelta

from sqlalchemy import select

from jgarmintracker import db as dbm
from jgarmintracker import routes, tracks, weather
from jgarmintracker.models import Activity, ActivityTrack, ActivityWeather, RouteGroup
from jgarmintracker.sync import sync

from .conftest import TODAY, FakeSource
from .test_friends import act_id, client  # noqa: F401  (fixture client réutilisée)


# ---------------------------------------------------------------- météo
def test_weather_parse_and_labels():
    w = weather.parse({"temp": 66, "apparentTemp": 64, "dewPoint": 59, "relativeHumidity": 78, "windDirection": 250,
                       "windSpeed": 8, "windGust": None, "weatherTypeDTO": {"desc": "Unknown"},
                       "weatherStationDTO": {"id": "06432"}})
    assert w["temp_c"] == 18.9 and w["feels_c"] == 17.8 and w["wind_kmh"] == 12.9 and w["gust_kmh"] is None
    assert w["sky"] == "" and w["station"] == "06432" and w["humidity"] == 78
    assert weather.parse(None)["temp_c"] is None
    assert weather.sky_label("Mostly Cloudy") == ("Nuageux", "cloud")
    assert weather.sky_label("Partly Cloudy") == ("Éclaircies", "cloud-sun")
    assert weather.sky_label("Light Rain Showers") == ("Pluie", "cloud-rain") and weather.sky_label("")[1] == "thermometer"
    assert weather.compass(250) == "OSO" and weather.compass(0) == "N" and weather.compass(None) == ""


def test_weather_sync(synced):
    s = synced
    rows = s.scalars(select(ActivityWeather)).all()
    assert len(rows) == s.query(Activity).count() and weather.missing(s) == []  # demandée une fois pour toutes
    indoor = s.get(ActivityWeather, s.scalar(select(Activity.id).where(Activity.garmin_id == 10000027)))
    assert indoor.temp_c is None
    bike = s.scalar(select(Activity).where(Activity.name == "Vélo dimanche"))
    assert bike.weather.temp_c == round((41 + 29 * 1.8 - 32) * 5 / 9, 1) and bike.weather.sky == "Partly Cloudy"
    stats = weather.by_weather(s.scalars(select(Activity)).all())
    assert stats["used"] >= 25 and sum(b.count for b in stats["temps"]) == stats["used"]
    assert all(b.speed is None or b.speed > 0 for b in stats["temps"])


def test_weather_rate_limit_does_not_fail_sync(session):
    src = FakeSource()
    src.weather_before_429 = 5
    run = sync(session, src, today=TODAY, history_days=180)
    assert run.status == "ok"
    assert session.query(ActivityWeather).count() == 5 and len(weather.missing(session)) > 0
    run = sync(session, FakeSource(), today=TODAY, history_days=180)  # la suite à la synchro suivante
    assert run.status == "ok" and weather.missing(session) == []


# ---------------------------------------------------------------- parcours
def loop(km: float, reverse=False, shift=0.0, wobble=0.0, n=120):
    """Boucle carrée inventée autour de 0°/0° (≈ km de tour), décalée de shift degrés."""
    side = km / 4 / 111.32
    corners = [(0, 0), (side, 0), (side, side), (0, side), (0, 0)]
    pts = []
    for (a, b), (c, d) in zip(corners, corners[1:]):
        for i in range(n // 4):
            t = i / (n // 4)
            pts.append((a + (c - a) * t + shift + wobble * math.sin(i), b + (d - b) * t + wobble * math.cos(i)))
    pts.append(pts[0])
    return list(reversed(pts)) if reverse else pts


def add(s, name, pts, km, minutes, day, sport_id):
    a = Activity(garmin_id=hash(name) % 10**9, name=name, start=datetime(2025, 5, 1) + timedelta(days=day),
                 distance_m=km * 1000, duration_s=minutes * 60, sport_id=sport_id, raw_json=json.dumps({"locationName": "Mons"}))
    s.add(a)
    s.flush()
    s.add(ActivityTrack(activity_id=a.id, points_json=tracks.dumps([(round(p[0], 5), round(p[1], 5)) for p in pts]),
                        n_points=len(pts), preview_path=tracks.preview_path(pts)))
    return a


def test_route_grouping(session):
    s = session
    from jgarmintracker.models import Sport

    sport = s.scalar(select(Sport).where(Sport.name == "Route"))
    a1 = add(s, "Boucle 1", loop(8), 8.0, 45, 0, sport.id)
    a2 = add(s, "Boucle 2", loop(8, wobble=0.0004), 8.1, 43, 7, sport.id)  # bruit GPS ~40 m
    a3 = add(s, "Boucle 3", loop(8), 7.9, 47, 14, sport.id)
    rev = add(s, "À l'envers", loop(8, reverse=True), 8.0, 44, 21, sport.id)
    other = add(s, "Ailleurs", loop(8, shift=0.05), 8.0, 40, 28, sport.id)  # 5 km plus loin
    longer = add(s, "Plus longue", loop(12), 12.0, 70, 35, sport.id)
    s.flush()
    res = routes.rebuild(s)
    assert res == {"routes": 1, "activities": 3}
    g = s.scalar(select(RouteGroup))
    assert {a.id for a in g.activities} == {a1.id, a2.id, a3.id} and g.name == "Mons · 8,0 km"
    assert rev.route_id is None and other.route_id is None and longer.route_id is None
    ps = routes.passages(g)
    assert [p.activity.name for p in ps] == ["Boucle 3", "Boucle 2", "Boucle 1"] and [p.rank for p in ps] == [3, 1, 2]
    # Un nom choisi survit au recalcul ; une sortie exclue sort du parcours (qui disparaît à moins de 2 sorties).
    g.name, g.custom_name = "Tour du quartier", True
    a3.excluded = True
    routes.rebuild(s)
    assert s.scalar(select(RouteGroup)).name == "Tour du quartier" and a3.route_id is None
    a2.excluded = True
    routes.rebuild(s)
    assert s.query(RouteGroup).count() == 0 and a1.route_id is None


def test_routes_and_weather_pages(client):  # noqa: F811
    with dbm.new_session() as s:
        sport_id = s.scalar(select(Activity.sport_id).where(Activity.name == "Course du soir 1"))
        ids = [add(s, f"Tour {i}", loop(10), 10.0, 50 - i, i, sport_id).id for i in range(3)]
        routes.rebuild(s)
        s.commit()
        gid = s.scalar(select(RouteGroup.id))
    html = client.get("/routes").get_data(as_text=True)
    assert "1 parcours faits plusieurs fois" in html and f"/routes/{gid}" in html
    page = client.get(f"/routes/{gid}").get_data(as_text=True)
    assert "Passages" in page and "Meilleur temps" in page and 'id="times"' in page
    detail = client.get(f"/activities/{ids[0]}").get_data(as_text=True)
    assert "Même parcours" in detail and "3e sur 3" in detail and "Écart au meilleur" in detail
    client.post(f"/routes/{gid}/rename", data={"name": "Boucle du lac"})
    assert "Boucle du lac" in client.get("/routes").get_data(as_text=True)
    client.post(f"/routes/{gid}/rename", data={"name": ""})
    with dbm.new_session() as s:
        assert not s.get(RouteGroup, gid).custom_name
    assert "Parcours recalculés" in client.post("/routes/rebuild", follow_redirects=True).get_data(as_text=True)
    # Météo : fiche, liste, Progression.
    detail = client.get(f"/activities/{act_id('Vélo dimanche')}").get_data(as_text=True)
    assert "Météo au départ" in detail and "Éclaircies" in detail and "station 06999" in detail
    assert 'class="wx-chip"' in client.get("/activities").get_data(as_text=True)
    with dbm.new_session() as s:
        fam = s.scalar(select(Activity).where(Activity.name == "Course du soir 1")).sport.family_id
    prog = client.get(f"/progress?sport=f{fam}&period=all").get_data(as_text=True)
    assert "Selon la météo" in prog and "Température au départ" in prog
