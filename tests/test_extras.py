"""0.2.0 : détails supplémentaires des activités (vitesse max, D−, zones cardio, cadence, meilleurs temps…)."""

import sqlite3
from datetime import date

from sqlalchemy import select

from jgarmintracker import db as dbm
from jgarmintracker.models import Activity, Sport
from jgarmintracker.stats import activities_between, records
from jgarmintracker.sync import parse_activity_extras, sync

from .conftest import TODAY, FakeSource


def test_parse_extras():
    e = parse_activity_extras({"maxSpeed": 9.7, "elevationLoss": 91, "hrTimeInZone_2": 452.9, "lapCount": 5.0,
                               "averageRunningCadenceInStepsPerMinute": 165, "maxRunningCadenceInStepsPerMinute": 192,
                               "avgStrideLength": 105.2, "fastestSplit_1000": 340.2, "pr": True})
    assert e["max_speed"] == 9.7 and e["elevation_loss_m"] == 91 and e["hr_zone_2"] == 452.9
    assert e["lap_count"] == 5 and e["cadence_max"] == 192 and e["stride_cm"] == 105.2
    assert e["fastest_1k_s"] == 340.2 and e["is_pr"] and e["hr_zone_5"] is None
    assert parse_activity_extras({})["is_pr"] is False


def test_sync_fills_extras(synced):
    bike = synced.scalar(select(Activity).where(Activity.name == "Vélo dimanche"))
    assert bike.max_speed > bike.avg_speed and bike.fastest_40k_s and bike.is_pr
    assert sum(bike.hr_zones) == bike.duration_s
    run = synced.scalar(select(Activity).where(Activity.name == "Course du soir 24"))
    assert run.cadence_avg and run.stride_cm and run.steps and run.fastest_1k_s and run.fastest_5k_s


def test_existing_db_gets_columns_and_backfill(tmp_path):
    """Base 0.1 : les colonnes n'existent pas encore ; au démarrage elles sont ajoutées puis remplies depuis le JSON."""
    path = tmp_path / "old.db"
    dbm.init_db(path)
    with dbm.new_session() as s:
        sync(s, FakeSource(), today=TODAY, history_days=30)
    con = sqlite3.connect(path)
    for col in dbm.NEW_COLUMNS["activities"]:
        con.execute(f"ALTER TABLE activities DROP COLUMN {col}")
    con.execute("DELETE FROM applied_upgrades")
    con.commit()
    con.close()

    dbm.init_db(path)
    with dbm.new_session() as s:
        bike = s.scalar(select(Activity).where(Activity.name == "Vélo dimanche"))
        assert bike.max_speed and bike.elevation_loss_m and bike.hr_zone_3 and bike.is_pr


def test_records_include_splits_and_max_speed(synced):
    route = synced.scalar(select(Sport).where(Sport.name == "Route", Sport.pace_unit == "min_km"))
    acts = activities_between(synced, date(2025, 1, 1), TODAY, [route.id])
    rec = records(acts, "min_km")
    labels = [label for label, *_ in rec.splits]
    assert labels == ["1 km", "5 km"]
    assert rec.splits[0][2].name == "Course du soir 24"  # la plus rapide
    assert rec.max_speed.max_speed == max(a.max_speed for a in acts)
