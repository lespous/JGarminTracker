"""0.12.0 : objectifs, entretien du matériel, carte de chaleur."""

from datetime import date

from sqlalchemy import select

from jgarmintracker import db as dbm
from jgarmintracker import gear, goals, maintenance
from jgarmintracker.units import NBSP as N
from jgarmintracker.models import Activity, Gear, GearService, GearTask, Goal
from jgarmintracker.stats import activities_between

from .conftest import TODAY
from .test_friends import act_id, client  # noqa: F401  (fixture client réutilisée)


def test_bounds_and_format():
    assert goals.bounds("week", TODAY) == (date(2025, 6, 16), date(2025, 6, 22))
    assert goals.bounds("month", date(2024, 2, 10)) == (date(2024, 2, 1), date(2024, 2, 29))
    assert goals.bounds("year", TODAY) == (date(2025, 1, 1), date(2025, 12, 31))
    assert goals.previous("month", date(2025, 1, 1)) == (date(2024, 12, 1), date(2024, 12, 31))
    assert goals.fmt("distance", 1500) == f"1{N}500 km" and goals.fmt("distance", 12.34) == "12,3 km"
    assert goals.fmt("duration", 2.5) == "2h30" and goals.fmt("count", 1) == "1 sortie" and goals.fmt("count", 3) == "3 sorties"
    assert goals.fmt("elevation", 2400) == f"2{N}400 m"


def test_goal_progress(synced):
    s = synced
    run_sport = s.scalar(select(Activity.sport_id).where(Activity.name == "Course du soir 1"))
    week = Goal(metric="count", target=3, period="week", scope="")
    year = Goal(metric="distance", target=500, period="year", scope=f"s{run_sport}")
    s.add_all([week, year])
    s.flush()
    p = goals.progress(s, week, TODAY)
    expected_count = len(activities_between(s, date(2025, 6, 16), TODAY))
    assert p.value == expected_count and p.days_left == 5  # mercredi : jeudi à dimanche + aujourd'hui
    assert abs(p.expected - 3 * 3 / 7) < 1e-9 and p.per_week is None and len(p.history) == 8
    y = goals.progress(s, year, TODAY)
    runs = [a for a in activities_between(s, date(2025, 1, 1), TODAY) if a.sport_id == run_sport]
    assert abs(y.value - sum(a.distance_m for a in runs) / 1000) < 1e-6
    assert y.per_week and abs(y.per_week - y.remaining / (y.days_left / 7)) < 1e-9
    assert y.gap == y.value - y.expected and len(y.history) == 3
    assert goals.title(year, y.scope_label).startswith("500 km par année · ")


def test_maintenance(synced):
    s = synced
    bike = Gear(name="Vélo", kind="bike", since=date(2025, 1, 1))
    s.add(bike)
    s.flush()
    rides = s.scalars(select(Activity).where(Activity.distance_m > 0)).all()
    gear.assign(rides, bike)
    total = sum(a.distance_m for a in rides) / 1000
    chain = GearTask(name="Chaîne", every_km=total / 2)
    yearly = GearTask(name="Révision", every_months=12)
    bike.tasks += [chain, yearly]
    s.flush()
    st = maintenance.status(s, chain, TODAY)
    assert abs(st.km - total) < 1e-6 and st.due and st.text.startswith("en retard de")
    assert not maintenance.status(s, yearly, TODAY).due  # 5,5 mois sur 12
    assert [x.task.name for x in maintenance.due(s, TODAY)] == ["Chaîne"]
    svc = maintenance.mark_done(s, chain, TODAY, 35.0)
    s.flush()
    assert abs(svc.km - total) < 0.1 and svc.name == "Chaîne"
    st = maintenance.status(s, chain, TODAY)
    assert st.km == 0 and not st.due and st.last.id == svc.id and st.text.startswith("dans")
    # Retrait : plus de rappel ; suppression de la tâche : le journal reste.
    yearly.every_months = 3
    assert maintenance.status(s, yearly, TODAY).due
    bike.retired = TODAY
    assert maintenance.due(s, TODAY) == []
    maintenance.delete_task(s, chain)
    s.flush()
    kept = s.get(GearService, svc.id)
    assert kept is not None and kept.task_id is None and kept.name == "Chaîne"
    assert maintenance.duration_text(3) == "3 jours" and maintenance.duration_text(30) == "4 semaines"
    assert maintenance.duration_text(200) == "7 mois"


def test_goal_and_maintenance_pages(client):  # noqa: F811
    html = client.get("/progress").get_data(as_text=True)
    assert 'id="goals"' in html and "Aucun objectif pour l'instant" in html
    client.post("/goals/add", data={"metric": "distance", "target": "1 500", "period": "year", "scope": ""})
    client.post("/goals/add", data={"metric": "count", "target": "0", "period": "week"})  # refusé
    with dbm.new_session() as s:
        goal = s.scalar(select(Goal))
        assert s.query(Goal).count() == 1 and goal.target == 1500
        goal_id = goal.id
    assert f"1{N}500 km par année" in client.get("/").get_data(as_text=True)  # tableau de bord
    html = client.get(f"/progress?goal_edit={goal_id}").get_data(as_text=True)
    assert f"/goals/{goal_id}/update" in html and "Périodes précédentes" in html
    client.post(f"/goals/{goal_id}/update", data={"metric": "count", "target": "3", "period": "week", "scope": ""})
    assert "3 sorties par semaine" in client.get("/").get_data(as_text=True)
    assert "Supprimer l'objectif" in client.get(f"/progress?goal_confirm={goal_id}").get_data(as_text=True)
    client.post(f"/goals/{goal_id}/delete")
    with dbm.new_session() as s:
        assert s.query(Goal).count() == 0

    # Entretien : tâche due -> bandeau, pastille, alerte sur la carte ; « Fait » la remet à zéro.
    client.post("/gear/add", data={"name": "Vélo", "kind": "bike", "since": "2025-01-01"})
    with dbm.new_session() as s:
        g = s.scalar(select(Gear))
        sport_id = s.scalar(select(Activity.sport_id).where(Activity.name == "Course du soir 1"))
        gear_id = g.id
    client.post("/gear/assign", data={"gear_id": gear_id, "sport": sport_id, "replace": "on"})
    client.post(f"/gear/{gear_id}/tasks/add", data={"name": "Chaîne", "every_km": "50"})
    client.post(f"/gear/{gear_id}/tasks/add", data={"name": "Sans intervalle"})  # refusé
    dash = client.get("/").get_data(as_text=True)
    assert "Chaîne · Vélo" in dash and "Fait aujourd'hui" in dash and "entretien(s) à faire" in dash
    assert "Chaîne : en retard de" in client.get("/gear").get_data(as_text=True)
    with dbm.new_session() as s:
        task_id = s.scalar(select(GearTask.id))
        assert s.query(GearTask).count() == 1
    page = client.get(f"/gear/{gear_id}").get_data(as_text=True)
    assert 'id="maintenance"' in page and "Plaquettes de frein" in page  # suggestions
    client.post(f"/gear/tasks/{task_id}/done", data={"day": "2025-06-17", "cost": "39,90", "note": "KMC"})
    dash = client.get("/").get_data(as_text=True)
    assert "Fait aujourd'hui" not in dash
    page = client.get(f"/gear/{gear_id}").get_data(as_text=True)
    assert "Journal" in page and "39,90 €" in page and "KMC" in page
    assert "Supprimer l'entretien" in client.get(f"/gear/{gear_id}?task_confirm={task_id}").get_data(as_text=True)
    client.post(f"/gear/tasks/{task_id}/delete")
    with dbm.new_session() as s:
        assert s.query(GearTask).count() == 0 and s.scalar(select(GearService)).task_id is None
        svc_id = s.scalar(select(GearService.id))
    client.post(f"/gear/services/{svc_id}/delete")
    with dbm.new_session() as s:
        assert s.query(GearService).count() == 0


def test_heat_map(client):  # noqa: F811
    html = client.get("/map?view=heat").get_data(as_text=True)
    assert "Carte de chaleur" in html and ", true)" in html and 'name="view" value="heat"' in html
    assert '<option value="0" selected>' in html  # tout l'historique par défaut
    html = client.get("/map").get_data(as_text=True)
    assert ", false)" in html and '<option value="12" selected>' in html
