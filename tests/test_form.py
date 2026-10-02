"""0.15.0 : onglet Forme (charge, récupération, VFC, liens sommeil / poids -> vitesse)."""

import math
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from jgarmintracker import db as dbm
from jgarmintracker import form, settings
from jgarmintracker.models import Activity, DailyHealth, Profile, WeightEntry
from jgarmintracker.sync import fetch_hrv, sync

from .conftest import TODAY, FakeSource
from .test_friends import client  # noqa: F401  (fixture client réutilisée)


def test_trimp_and_labels():
    p = form.HrParams(rest=50, max=190, female=False, max_source="profil")
    a = Activity(avg_hr=155, duration_s=3600)
    r = (155 - 50) / 140
    assert form.trimp(a, p) == pytest.approx(60 * r * 0.64 * math.exp(1.92 * r))
    assert form.trimp(Activity(avg_hr=None, duration_s=3600), p) is None
    pf = form.HrParams(50, 190, True, "profil")
    assert form.trimp(a, pf) == pytest.approx(60 * r * 0.86 * math.exp(1.67 * r))
    assert form.acwr_label(0.7)[1] == "low" and form.acwr_label(1.0)[1] == "ok"
    assert form.acwr_label(1.4)[1] == "warn" and form.acwr_label(1.8)[1] == "bad" and form.acwr_label(None)[1] == "muted"
    assert form.form_label(20).startswith("très frais") and form.form_label(-40).startswith("très fatigué")
    assert form.strength(0.05) == "aucun lien net" and form.strength(-0.6) == "lien fort"
    assert form.pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1) and form.pearson([1, 1, 1], [1, 2, 3]) is None


def test_load_series(synced):
    s = synced
    s.add(Profile(id=1, max_hr=190, rest_hr=48))
    s.flush()
    p = form.hr_params(s, TODAY)
    assert (p.rest, p.max, p.max_source) == (48, 190, "profil")
    load = form.load_series(s, TODAY - timedelta(days=89), TODAY, TODAY)
    assert len(load.days) == 90 and load.days[-1] == TODAY and load.counted > 5
    assert all(c >= 0 for c in load.ctl) and load.ctl[-1] > 0
    assert load.tsb[-1] == pytest.approx(load.ctl[-1] - load.atl[-1], abs=0.11)
    week = sum(load.load[-7:])
    assert load.today["week"] == pytest.approx(week) and load.today["ratio"] is not None
    # Sans profil : FC max mesurée (99e centile des FC max des sorties), FC de repos d'après la santé.
    s.delete(s.get(Profile, 1))
    s.flush()
    p = form.hr_params(s, TODAY)
    assert p.max_source == "mesurée" and 120 < p.max < 230 and 30 < p.rest < 90


def test_hrv_fetch_and_guard(session):
    src = FakeSource()
    sync(session, src, today=TODAY, history_days=60)
    rows = session.scalars(select(DailyHealth).where(DailyHealth.hrv_night.is_not(None))).all()
    assert rows and rows[0].hrv_status == "BALANCED" and rows[0].hrv_low == 38 and rows[0].hrv_high == 52
    asked = list(src.hrv_asked)
    assert asked == sorted(asked, reverse=True)  # plus récentes d'abord
    assert not settings.get(session, "hrv_unavailable")


def test_hrv_guard_without_hrv(session):
    src = FakeSource()
    src.HRV = False
    sync(session, src, today=TODAY, history_days=60)
    assert len(src.hrv_asked) == 14 and settings.get(session, "hrv_unavailable")  # abandon après 14 nuits vides
    src2 = FakeSource()
    src2.HRV = False
    fetch_hrv(session, src2, TODAY + timedelta(days=2), lambda p: None)
    assert len(src2.hrv_asked) <= 3  # ensuite : seulement les dernières nuits


def test_links(synced):
    s = synced
    fam = form.families_with_pace(s)[0]
    rel = form.relative_speeds(s, fam.id)
    assert rel and all(-60 < y < 60 for _a, y in rel)
    link = form._link([(a, 6 + k % 3, y) for k, (a, y) in enumerate(rel)], form.SLEEP_BINS)
    assert link.n == len(rel) and sum(b["n"] for b in link.bins) == link.n
    wl = form.weight_link(s, fam.id)
    assert not wl.ready and wl.entries == 0
    for k in range(10):
        s.add(WeightEntry(day=TODAY - timedelta(days=7 * k), weight_kg=75 + k * 0.3))
    s.flush()
    wl = form.weight_link(s, fam.id)
    assert wl.ready and wl.entries == 10 and wl.weeks == 9 and len(wl.link.bins) == 3
    assert all(abs(p["x"] - 75) < 5 for p in wl.link.points)


def test_form_page(client):  # noqa: F811
    html = client.get("/form").get_data(as_text=True)
    assert "Charge des 7 derniers jours" in html and "Ratio aigu / chronique" in html
    assert "Variabilité cardiaque" in html and "0 pesée sur 10" in html and ">Forme<" in html
    html = client.get("/form?period=365").get_data(as_text=True)
    assert 'class="chip on" href="/form?period=365"' in html
