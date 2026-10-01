from datetime import date

from sqlalchemy import select

from jgarmintracker import units
from jgarmintracker.models import Sport, SportFamily
from jgarmintracker.stats import (
    activities_between,
    health_series,
    health_summary,
    linear_trend,
    monthly_volume,
    pace_series,
    records,
    rolling_mean,
    week_compare,
    week_label,
    week_start,
    weekly_volume,
)

from .conftest import TODAY


def test_units_belgian_formats():
    assert units.km(12345) == "12,3 km"
    assert units.km(1234567) == f"1{units.NBSP}234,6 km"
    assert units.km(5000) == "5,00 km"
    assert units.pace(1000 / 312, "min_km") == "5:12 /km"
    assert units.pace(100 / 112, "min_100m") == "1:52 /100 m"
    assert units.pace(28.4 / 3.6, "kmh") == "28,4 km/h"
    assert units.pace(0, "min_km") == units.pace(None, "kmh") == "—"
    assert units.hmm(3 * 3600 + 5 * 60 + 29) == "3:05"
    assert units.hms(3725) == "1:02:05" and units.hms(312) == "5:12"
    assert units.day(date(2025, 6, 1)) == "01/06/2025"
    assert units.bpm(51.6) == "52 bpm"


def test_iso_weeks():
    assert week_start(date(2025, 6, 18)) == date(2025, 6, 16)
    assert week_start(date(2025, 6, 22)) == date(2025, 6, 16)  # dimanche
    assert week_start(date(2025, 1, 1)) == date(2024, 12, 30)  # semaine à cheval sur deux années
    assert week_label(date(2024, 12, 30)) == "S01 · 30/12"


def test_rolling_mean_keeps_gaps():
    values = [50, None, 52, 54, None, None, None, None, None, None, 60]
    out = rolling_mean(values, window=7, min_points=3)
    assert out[:3] == [None, None, None]  # moins de 3 valeurs dans la fenêtre
    assert out[3] == 52.0
    assert out[10] is None  # une seule valeur dans les 7 derniers jours


def test_linear_trend():
    assert linear_trend([0, 1, 2], [1, 3, 5]) == (2.0, 1.0)
    assert linear_trend([1], [1]) is None


def test_week_compare(synced):
    wc = week_compare(synced, TODAY)
    assert wc.monday == date(2025, 6, 16)
    # Courses hebdomadaires du mardi comprises : 17/06 cette semaine, 10/06 la précédente.
    assert wc.current.count == 4 and wc.previous.count == 6
    names = [f.family.name for f in wc.families]
    assert names == ["Course", "Vélo", "Natation", "Marche & rando", "Renforcement", "Autre"]
    course = next(f for f in wc.families if f.family.name == "Course")
    assert course.current.distance_m == 12000 + 11000 and course.previous.distance_m == 14000 + 9500


def test_weekly_volume_stacks_by_sport(synced):
    vol = weekly_volume(synced, TODAY, weeks=12, metric="distance")
    assert len(vol["labels"]) == 12 and vol["labels"][-1] == "S25 · 16/06"
    by_label = {d["label"]: d["data"] for d in vol["datasets"]}
    assert by_label["Vélo › Route"][-2] == 62.0
    assert by_label["Course › Trail"][-1] == 12.0  # « Trail des collines », classé par son nom


def test_progress_pace_improves_and_records(synced):
    route = synced.scalar(select(Sport).join(Sport.family).where(SportFamily.name == "Course", Sport.name == "Route"))
    acts = activities_between(synced, date(2025, 1, 1), TODAY, [route.id])
    series = pace_series(acts, "min_km")
    assert len(series["values"]) == 24
    assert series["change"] < -30  # environ 40 s/km plus rapide sur la période
    rec = records(acts, "min_km")
    assert rec.longest.distance_m == 11000
    assert rec.best_pace.name == "Course du soir 24"
    monthly = monthly_volume(acts, TODAY, months=6)
    assert monthly["labels"][0] == "janv. 25" and monthly["count"][0] == 4


def test_health_series_and_summary(synced):
    h = health_series(synced, TODAY, days=30)
    assert len(h["labels"]) == 30 and h["labels"][-1] == "mer. 18/06"
    i13 = h["labels"].index("ven. 13/06")
    assert h["rhr"][i13] is None and h["bb"][i13] is None
    assert h["sleep"][-1] is None  # nuit pas encore complète
    assert all(isinstance(v, list) and v[0] <= v[1] for v in h["bb"] if v)
    s = health_summary(synced, TODAY, 7)
    assert s.rhr and s.rhr_prev and s.vo2max == 48.3 and s.days_with_data == 6  # 13/06 sans montre
