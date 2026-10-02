"""0.7.0 : page Vérifications, activités exclues des statistiques, pointes GPS ignorées."""

from datetime import date

import pytest
from sqlalchemy import select

from jgarmintracker import checks, settings
from jgarmintracker import db as dbm
from jgarmintracker.models import Activity
from jgarmintracker.stats import activities_between, records, week_compare
from jgarmintracker.web import create_app

from .conftest import TODAY, FakeSource


def run(session, name):
    return session.scalar(select(Activity).where(Activity.name == name))


def plant_anomalies(s):
    """Une course trop rapide pour un humain, une très rapide pour moi (montre prêtée), une pointe GPS."""
    run(s, "Course du soir 20").avg_speed = 1000 / 140  # 2:20 /km : impossible
    run(s, "Course du soir 21").avg_speed = 1000 / 250  # 4:10 /km contre ~5:30 : inhabituel
    run(s, "Course du soir 22").max_speed = 12.0  # 1:23 /km en pointe : saut de GPS
    s.commit()


def test_display_conversions():
    assert checks.from_display("2:30", "min_km") == pytest.approx(1000 / 150)
    assert checks.from_display("60", "kmh") == pytest.approx(60 / 3.6)
    assert checks.from_display("1:00", "min_100m") == pytest.approx(100 / 60)
    assert checks.from_display("", "min_km") is None
    assert checks.to_display(1000 / 150, "min_km") == "2:30" and checks.to_display(60 / 3.6, "kmh") == "60"
    with pytest.raises(ValueError):
        checks.from_display("vite", "min_km")


def test_find_issues(synced):
    assert not any(checks.find_issues(synced).values())  # données inventées normales : rien
    plant_anomalies(synced)
    found = checks.find_issues(synced)
    assert [f.activity.name for f in found["impossible"]] == ["Course du soir 20"]
    assert [f.activity.name for f in found["unusual"]] == ["Course du soir 21"]
    assert "% plus rapide" in found["unusual"][0].detail
    assert [f.activity.name for f in found["spike"]] == ["Course du soir 22"]
    assert checks.count_issues(synced) == 3
    # « C'est bien moi », pointe ignorée, exclusion : les alertes disparaissent.
    run(synced, "Course du soir 21").review_ok = True
    run(synced, "Course du soir 22").ignore_max_speed = True
    run(synced, "Course du soir 20").excluded = True
    assert checks.count_issues(synced) == 0


def test_custom_limits(synced):
    course = run(synced, "Course du soir 1").sport.family_id
    settings.put(synced, "check_limits", {str(course): {"avg": 1000 / 400, "max": None}})  # 6:40 /km
    assert len(checks.find_issues(synced)["impossible"]) > 10


def test_excluded_activity_leaves_every_statistic(synced):
    bike = run(synced, "Vélo dimanche")
    before = week_compare(synced, date(2025, 6, 15))
    bike.excluded, bike.exclude_reason = True, "Montre prêtée"
    synced.commit()
    after = week_compare(synced, date(2025, 6, 15))
    assert after.current.count == before.current.count - 1
    assert bike not in activities_between(synced, date(2025, 6, 1), TODAY)
    assert bike in activities_between(synced, date(2025, 6, 1), TODAY, include_excluded=True)


def test_ignored_spike_leaves_records(synced):
    plant_anomalies(synced)
    acts = activities_between(synced, date(2025, 1, 1), TODAY, [run(synced, "Course du soir 1").sport_id])
    assert records(acts, "min_km").max_speed.name == "Course du soir 22"
    run(synced, "Course du soir 22").ignore_max_speed = True
    assert records(acts, "min_km").max_speed.name != "Course du soir 22"


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
    with dbm.new_session() as s:
        settings.put(s, "history_months", 6)
        s.commit()
    c = app.test_client()
    c.post("/sync")
    with dbm.new_session() as s:
        plant_anomalies(s)
    return c


def act_id(name):
    with dbm.new_session() as s:
        return s.scalar(select(Activity.id).where(Activity.name == name))


def test_checks_page_and_actions(client):
    html = client.get("/checks").get_data(as_text=True)
    assert "Course du soir 20" in html and "Course du soir 21" in html and "Course du soir 22" in html
    # Une case « tout cocher » par section qui a des alertes, reliée aux lignes de sa section.
    for key in ("impossible", "unusual", "spike"):
        assert f'class="check-section" data-section="{key}"' in html
        assert f'class="act-check" data-section="{key}"' in html
    assert 'title="Activités à vérifier">3<' in html  # pastille dans la navigation
    # Exclure la « montre prêtée » : elle reste dans la liste, grisée, mais sort de la progression.
    client.post("/activities/bulk/exclude", data={"act": [act_id("Course du soir 21")], "reason": "Montre prêtée",
                                                  "action": "exclude"})
    listing = client.get("/activities").get_data(as_text=True)
    assert "exclue · Montre prêtée" in listing and "excluded-row" in listing
    assert "Course du soir 21" in client.get("/activities?status=excluded").get_data(as_text=True)
    assert "Course du soir 21" not in client.get("/activities?status=kept").get_data(as_text=True)
    assert "Exclue des statistiques" in client.get(f"/activities/{act_id('Course du soir 21')}").get_data(as_text=True)
    # Pointe ignorée et « c'est bien moi ».
    client.post(f"/activities/{act_id('Course du soir 22')}/ignore-max")
    client.post(f"/activities/{act_id('Course du soir 20')}/review")
    html = client.get("/checks").get_data(as_text=True)
    assert "Rien à signaler" in html and "Pointes de vitesse ignorées" in html
    assert 'title="Activités à vérifier"' not in html
    # Réintégrer.
    client.post("/activities/bulk/exclude", data={"act": [act_id("Course du soir 21")], "action": "include"})
    with dbm.new_session() as s:
        a = s.get(Activity, act_id("Course du soir 21"))
        assert not a.excluded and a.exclude_reason is None


def test_bulk_ignore_spikes(client):
    client.post("/activities/bulk/ignore-max", data={"act": [act_id("Course du soir 22")]})
    with dbm.new_session() as s:
        assert s.get(Activity, act_id("Course du soir 22")).ignore_max_speed
        assert not checks.find_issues(s)["spike"]
    r = client.post("/activities/bulk/ignore-max", data={}, follow_redirects=True)
    assert "Coche au moins" in r.get_data(as_text=True)


def test_change_sport_from_checks(client):
    with dbm.new_session() as s:
        bike = s.scalar(select(Activity.sport_id).where(Activity.name == "Vélo dimanche"))
    client.post("/activities/bulk/sport", data={"act": [act_id("Course du soir 20")], "sport_id": bike})
    with dbm.new_session() as s:
        a = s.get(Activity, act_id("Course du soir 20"))
        assert a.sport_id == bike and a.sport_locked


def test_settings_limits(client):
    html = client.get("/settings?tab=activities").get_data(as_text=True)
    assert 'value="2:30"' in html and 'value="60"' in html
    with dbm.new_session() as s:
        course = s.scalar(select(Activity).where(Activity.name == "Course du soir 1")).sport.family_id
    r = client.post("/settings/checks", data={f"avg_{course}": "3:00", f"max_{course}": "", "unusual_pct": "30"},
                    follow_redirects=True)
    assert "Limites des vérifications enregistrées" in r.get_data(as_text=True)
    with dbm.new_session() as s:
        assert checks.limits(s)[course] == {"avg": pytest.approx(1000 / 180), "max": None}
        assert settings.get(s, "unusual_pct") == 30
    r = client.post("/settings/checks", data={f"avg_{course}": "vite", "unusual_pct": "30"}, follow_redirects=True)
    assert "Valeurs illisibles" in r.get_data(as_text=True)
