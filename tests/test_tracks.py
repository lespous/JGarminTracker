"""0.3.0 : tracés GPS (données inventées autour de 0° N / 0° E)."""

import re

import pytest
from sqlalchemy import func, select

from jgarmintracker import db as dbm
from jgarmintracker import tracks
from jgarmintracker.models import Activity, ActivityTrack, SyncRun
from jgarmintracker.sync import sync

from .conftest import TODAY, FakeSource


def test_parse_track_skips_invalid_and_duplicates():
    details = {"geoPolylineDTO": {"polyline": [
        {"lat": 0.123456789, "lon": 0.1, "valid": True}, {"lat": 0.123456789, "lon": 0.1},
        {"lat": None, "lon": None, "valid": False}, {"lat": 0.2, "lon": 0.2, "valid": False}, {"lat": 0.3, "lon": 0.3},
    ]}}
    assert tracks.parse_track(details) == [(0.12346, 0.1), (0.3, 0.3)]
    assert tracks.parse_track(None) == [] and tracks.parse_track({"geoPolylineDTO": None}) == []


def test_thin_keeps_ends():
    pts = [(i, i) for i in range(1000)]
    out = tracks.thin(pts, 50)
    assert len(out) == 50 and out[0] == pts[0] and out[-1] == pts[-1]
    assert tracks.thin(pts[:10], 50) == pts[:10]


def test_preview_path_fits_box_and_keeps_proportions():
    # Rectangle deux fois plus large que haut (en km), à l'équateur.
    pts = [(0.0, 0.0), (0.0, 0.02), (0.01, 0.02), (0.01, 0.0)]
    path = tracks.preview_path(pts, w=64, h=40, pad=2)
    nums = [float(x) for x in re.findall(r"[\d.]+", path)]
    xs, ys = nums[0::2], nums[1::2]
    assert min(xs) >= 2 and max(xs) <= 62 and min(ys) >= 2 and max(ys) <= 38
    assert (max(xs) - min(xs)) == pytest.approx(2 * (max(ys) - min(ys)), rel=0.02)
    assert tracks.preview_path([(0, 0)]) == ""


def test_sync_fetches_tracks_once(synced):
    s = synced
    assert s.scalar(select(func.count()).select_from(ActivityTrack)) == 29  # activités en extérieur
    assert s.scalar(select(func.count()).select_from(ActivityTrack).where(ActivityTrack.n_points > 0)) == 25
    assert s.scalar(select(SyncRun.tracks_added)) == 25
    run = s.scalar(select(Activity).where(Activity.name == "Course du soir 1"))
    assert run.track.n_points == 61 and run.track.preview_path.startswith("M")
    indoor = s.scalar(select(Activity).where(Activity.name == "Renfo maison"))
    assert indoor.track is None
    source = FakeSource()
    sync(s, source, today=TODAY)
    assert source.tracks_asked == []  # déjà demandés, même les vides


def test_rate_limit_during_tracks_keeps_progress(session):
    run = sync(session, FakeSource(tracks_before_429=10), today=TODAY, history_days=180)
    assert run.status == "error" and "429" in run.message
    assert session.scalar(select(func.count()).select_from(ActivityTrack)) == 10
    source = FakeSource()
    assert sync(session, source, today=TODAY, history_days=180).status == "ok"
    assert len(source.tracks_asked) == 19


def test_existing_db_gets_track_table(tmp_path):
    path = tmp_path / "v02.db"
    dbm.init_db(path)
    import sqlite3

    con = sqlite3.connect(path)
    con.execute("DROP TABLE activity_tracks")
    con.execute("ALTER TABLE sync_runs DROP COLUMN tracks_added")
    con.commit()
    con.close()
    dbm.init_db(path)
    with dbm.new_session() as s:
        assert sync(s, FakeSource(), today=TODAY, history_days=60).tracks_added > 0
