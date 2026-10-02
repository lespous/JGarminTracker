"""0.14.0 : segments chronométrés sur toutes les sorties qui les empruntent."""

import math
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from jgarmintracker import db as dbm
from jgarmintracker import segments
from jgarmintracker.models import Activity, ActivityStream, Segment, SegmentEffort, Sport

from .conftest import FakeSource
from .test_friends import client  # noqa: F401  (fixture client réutilisée)
from .test_routes_weather import add, loop


def fake_details(points, speed_ms, hr=140, climb=False):
    """Réponse Garmin inventée : un point toutes les ~10 m, à vitesse constante, altitude montante si climb."""
    proj = segments.Projector(points[0][0])
    dense = []
    for a, b in zip(points, points[1:]):
        d = math.dist(proj.xy(a), proj.xy(b))
        n = max(1, int(d // 10))
        dense += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
    dense.append(points[-1])
    keys = ["directTimestamp", "directLatitude", "directLongitude", "sumDistance", "directHeartRate", "directElevation"]
    rows, dist, t0 = [], 0.0, 1_700_000_000_000
    for k, p in enumerate(dense):
        if k:
            dist += math.dist(proj.xy(dense[k - 1]), proj.xy(p))
        rows.append({"metrics": [t0 + dist / speed_ms * 1000, p[0], p[1], dist, hr, 50 + (dist / 20 if climb else 0)]})
    return {"metricDescriptors": [{"key": k, "metricsIndex": i} for i, k in enumerate(keys)], "activityDetailMetrics": rows}


def test_parse_stream_and_sparse_track():
    d = fake_details([(50.0, 4.0), (50.0, 4.01)], 5)  # pas en 0°/0° : Garmin y met les points sans position
    s = segments.parse_stream(d)
    assert s[0][0] == 0 and s[-1][3] == pytest.approx(715.6, abs=1) and s[-1][0] == pytest.approx(143.1, abs=0.2)
    assert segments.parse_stream({"metricDescriptors": []}) == []
    # Un tracé simplifié à deux points éloignés (ligne droite de 2 km) traverse bien un segment au milieu.
    shape = segments.Shape.of([(0.0, 0.005), (0.0, 0.0075), (0.0, 0.01)])
    path = [shape.proj.xy(p) for p in [(0.0, 0.0), (0.0, 0.018)]]
    (i, j), = segments.windows(path, shape)
    assert i == pytest.approx(0.005 / 0.018, abs=0.01) and j == pytest.approx(0.01 / 0.018, abs=0.01)
    back = [shape.proj.xy(p) for p in [(0.0, 0.018), (0.0, 0.0)]]
    assert segments.windows(back, shape) == []  # dans l'autre sens : pas le même segment


def test_segment_flow(session):
    s = session
    sport = s.scalar(select(Sport).where(Sport.name == "Route"))
    route = loop(8)
    acts = [add(s, f"Tour {k}", route, 8.0, 45, k * 7, sport.id) for k in range(3)]
    rev = add(s, "Envers", loop(8, reverse=True), 8.0, 44, 30, sport.id)
    far = add(s, "Ailleurs", loop(8, shift=0.05), 8.0, 44, 31, sport.id)
    for a in acts + [rev, far]:
        a.garmin_id = 900 + a.id
    speeds = {acts[0].id: 3.0, acts[1].id: 3.5, acts[2].id: 2.5}
    src = FakeSource()
    src.DETAILS = {a.garmin_id: fake_details(route, speeds[a.id], climb=True) for a in acts}
    src.DETAILS[rev.garmin_id] = fake_details(loop(8, reverse=True), 3.0)
    s.flush()

    with pytest.raises(ValueError):
        segments.create(s, acts[0], 10, 11, "trop court")
    seg = segments.create(s, acts[0], 30, 60, "Côte du parc")  # un quart de boucle, ~2 km
    assert 1900 < seg.distance_m < 2100
    found = {a.id for a in segments.candidates(s, seg)}
    assert found == {a.id for a in acts}  # ni l'envers, ni ailleurs

    res = segments.refresh(s, src, [seg.id])
    assert res["fetched"] == 3 and res["efforts"] == 3
    efforts = {e.activity_id: e for e in seg.efforts}
    for a in acts:
        assert efforts[a.id].elapsed_s == pytest.approx(seg.distance_m / speeds[a.id], rel=0.03)
    assert [e.activity_id for _r, e in segments.ranked(seg)] == [acts[1].id, acts[0].id, acts[2].id]
    prof = segments.profile(s, seg)
    assert prof and prof.gain == pytest.approx(seg.distance_m / 20, rel=0.05) and prof.grade == pytest.approx(5, abs=0.3)

    # Deuxième analyse : rien à retélécharger. Une sortie plus rapide ajoutée -> record récent.
    asked = len(src.details_asked)
    assert segments.refresh(s, src, [seg.id])["fetched"] == 0 and len(src.details_asked) == asked
    fast = add(s, "Tour rapide", route, 8.0, 40, 40, sport.id)
    fast.garmin_id = 999
    src.DETAILS[999] = fake_details(route, 4.0)
    res = segments.refresh(s, src)
    assert res["efforts"] == 1 and res["records"] == 1
    recs = segments.recent_records(s, datetime.now())
    assert len(recs) == 1 and recs[0].effort.activity_id == fast.id and recs[0].gain_s > 0
    assert segments.recent_records(s, datetime.now() + timedelta(days=8)) == []
    # Sortie exclue : hors classement.
    fast.excluded = True
    assert segments.ranked(seg)[0][1].activity_id == acts[1].id


def test_segment_pages(client):  # noqa: F811
    with dbm.new_session() as s:
        sport_id = s.scalar(select(Activity.sport_id).where(Activity.name == "Course du soir 1"))
        route = loop(10)
        ids = []
        for k in range(2):
            a = add(s, f"Boucle {k}", route, 10.0, 50, k, sport_id)
            a.garmin_id = 800 + k
            ids.append(a.id)
        s.commit()
    FakeSource.DETAILS = {800: fake_details(route, 3.0), 801: fake_details(route, 3.3)}
    try:
        page = client.get(f"/activities/{ids[0]}").get_data(as_text=True)
        assert 'id="seg-picker"' in page and "segmentPicker(" in page
        r = client.post("/segments/create", data={"activity_id": ids[0], "start_idx": 10, "end_idx": 40, "name": "Ligne droite"},
                        follow_redirects=True)
        html = r.get_data(as_text=True)
        assert "Segment « Ligne droite » créé" in html and "Classement" in html and "Profil d'altitude" in html
        with dbm.new_session() as s:
            seg = s.scalar(select(Segment))
            assert s.query(SegmentEffort).count() == 2 and s.query(ActivityStream).count() == 2
            seg_id = seg.id
        detail = client.get(f"/activities/{ids[1]}").get_data(as_text=True)
        assert "Segments traversés" in detail and "Ligne droite" in detail
        assert "Ligne droite" in client.get("/routes").get_data(as_text=True)
        r = client.post("/segments/create", data={"activity_id": ids[0], "start_idx": 10, "end_idx": 10}, follow_redirects=True)
        assert "Choisis un départ" in r.get_data(as_text=True)
        client.post(f"/segments/{seg_id}/rename", data={"name": "Faux plat"})
        assert "Faux plat" in client.get(f"/segments/{seg_id}").get_data(as_text=True)
        assert "Supprimer le segment" in client.get(f"/segments/{seg_id}?confirm=1").get_data(as_text=True)
        client.post(f"/segments/{seg_id}/delete")
        with dbm.new_session() as s:
            assert s.query(Segment).count() == 0 and s.query(SegmentEffort).count() == 0
            assert s.query(ActivityStream).count() == 2  # les données détaillées restent
        assert client.get("/sync").status_code == 200  # le journal affiche l'analyse « segments »
    finally:
        FakeSource.DETAILS = {}
