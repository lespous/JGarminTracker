import json
from datetime import date, timedelta

from sqlalchemy import func, select

from jgarmintracker.models import Activity, DailyHealth, SyncRun
from jgarmintracker.sync import parse_activity, parse_sleep, parse_summary, parse_vo2max, plan, sync

from .conftest import TODAY, FakeSource


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_first_sync_fills_everything(synced):
    s = synced
    assert count(s, Activity) == 32
    run = s.scalar(select(SyncRun))
    assert (run.status, run.mode, run.activities_added) == ("ok", "incremental", 32)
    a = s.scalar(select(Activity).where(Activity.name == "Vélo dimanche"))
    assert a.sport.label == "Vélo › Route" and a.sport_source == "rule"
    assert a.distance_m == 62000 and a.avg_power == 185
    assert json.loads(a.raw_json)["activityId"] == a.garmin_id
    assert s.scalar(select(Activity).where(Activity.name == "Paddle lac")).sport.label == "Autre"


def test_health_rows_gaps_and_vo2max(synced):
    s = synced
    # Jour sans montre (13/06) : pas de ligne. Le 18/06 a un résumé mais une nuit pas encore complète.
    assert s.get(DailyHealth, date(2025, 6, 13)) is None
    last = s.get(DailyHealth, TODAY)
    assert last.resting_hr and last.sleep_s is None and last.raw_sleep
    d = s.get(DailyHealth, date(2025, 6, 12))
    assert d.sleep_s == d.deep_s + d.light_s + d.rem_s
    assert d.sleep_score and d.bb_max >= d.bb_min
    assert s.get(DailyHealth, date(2025, 6, 10)).stress_avg is None  # -1 de Garmin = pas de mesure
    assert s.get(DailyHealth, date(2025, 6, 15)).vo2max == 48.3


def test_second_sync_adds_nothing_and_resyncs_last_days(synced):
    source = FakeSource()
    run = sync(synced, source, today=TODAY)
    assert (run.activities_added, run.days_added) == (0, 0)
    assert count(synced, Activity) == 32
    # Re-synchro des 3 derniers jours, pas de tout l'historique.
    assert source.days_asked == [TODAY - timedelta(days=2), TODAY - timedelta(days=1), TODAY]


def test_changed_activity_is_updated_but_keeps_manual_sport(synced):
    s = synced
    a = s.scalar(select(Activity).where(Activity.name == "Paddle lac"))
    from jgarmintracker.models import Sport
    yoga = s.scalar(select(Sport).where(Sport.name == "Yoga"))
    a.sport_id, a.sport_locked, a.sport_source = yoga.id, True, "manual"
    s.commit()
    source = FakeSource()
    next(x for x in source.activities if x["activityName"] == "Paddle lac")["activityName"] = "Paddle lac (édité)"
    run = sync(s, source, today=TODAY)
    assert run.activities_updated == 1
    s.refresh(a)
    assert a.name == "Paddle lac (édité)" and a.sport_id == yoga.id


def test_rate_limit_stops_cleanly_and_resumes(session):
    run = sync(session, FakeSource(fail_on=date(2025, 6, 1)), today=TODAY, history_days=40)
    assert run.status == "error" and "429" in run.message
    kept = session.scalar(select(func.max(DailyHealth.day)))
    assert kept == date(2025, 5, 31)  # tout ce qui précède l'erreur est gardé
    source = FakeSource()
    run = sync(session, source, today=TODAY, history_days=40)
    assert run.status == "ok"
    assert source.days_asked[0] == date(2025, 6, 1)  # reprise où elle s'était arrêtée


def test_full_resync_rereads_history(synced):
    source = FakeSource()
    run = sync(synced, source, today=TODAY, full=True, history_days=30)
    assert run.mode == "full" and len(source.days_asked) == 30


def test_plan_on_empty_db_uses_history(session):
    act, health = plan(session, TODAY, full=False, days=3, history_days=365)
    assert act == health == TODAY - timedelta(days=364)


def test_parsers_tolerate_missing_fields():
    assert parse_summary(None)["resting_hr"] is None
    assert parse_sleep({})["sleep_s"] is None
    assert parse_vo2max(None) == {} and parse_vo2max({"generic": None}) == {}
    a = parse_activity({"activityId": 5, "startTimeLocal": "2025-01-02T07:08:09.0", "activityType": None})
    assert a["start"].isoformat() == "2025-01-02T07:08:09" and a["type_key"] == "" and a["distance_m"] is None
