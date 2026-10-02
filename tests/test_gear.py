"""0.11.0 : matériel (vélos, chaussures) affecté aux sorties, en bloc ou par défaut d'un sport."""

import io
from datetime import date

import pytest
from sqlalchemy import select

from jgarmintracker import db as dbm
from jgarmintracker import gear
from jgarmintracker.classifier import Classifier
from jgarmintracker.models import Activity, Gear
from jgarmintracker.sync import sync

from .conftest import TODAY, FakeSource
from .test_friends import act_id, client, image_bytes  # noqa: F401  (fixture client réutilisée)


def runs(s, start=None, end=None):
    sport_id = s.scalar(select(Activity.sport_id).where(Activity.name == "Course du soir 1"))
    return sport_id, gear.candidates(s, [sport_id], start, end)


def test_assign_one_per_kind(synced):
    s = synced
    old = Gear(name="Vieilles", kind="shoes", since=date(2025, 1, 1), retired=date(2025, 3, 31))
    new = Gear(name="Neuves", kind="shoes", since=date(2025, 4, 1), max_km=800, price=160)
    bike = Gear(name="Vélo", kind="bike")
    s.add_all([old, new, bike])
    s.flush()
    sport_id, all_runs = runs(s)
    assert len(all_runs) == 24 and all_runs[0].start > all_runs[-1].start  # plus récentes d'abord

    r = gear.assign(all_runs, old)
    assert (r.added, r.replaced, r.already) == (24, 0, 0)
    # Nouvelles chaussures à partir du 15/03 : remplacent les vieilles sur ces sorties.
    _, recent = runs(s, date(2025, 3, 15))
    preview = gear.plan_assign(recent, new, replace=True)
    r = gear.assign(recent, new, replace=True)
    assert r.replaced == preview.replaced == len(recent) > 0 and r.changed == len(recent)
    assert all(a.gear == [new] for a in recent)
    # Sans remplacement : les sorties qui ont déjà des chaussures les gardent.
    r = gear.assign(all_runs, new, replace=False)
    assert r.kept == 24 - len(recent) and r.already == len(recent) and r.changed == 0
    # Types différents : un vélo s'ajoute aux chaussures.
    gear.assign(recent[:1], bike)
    assert {g.kind for g in recent[0].gear} == {"shoes", "bike"}
    gear.set_kind(recent[0], "shoes", None)
    assert recent[0].gear == [bike]

    w = gear.wear(new, 840_000)
    assert w.warn and w.worn and round(w.ratio, 2) == 1.05
    assert not gear.wear(new, 100_000).warn and gear.wear(bike, 5000).ratio is None
    assert gear.cost_per_km(new, 400_000) == 0.4 and gear.cost_per_km(new, 0) is None


def test_defaults_on_sync(session):
    """Le matériel par défaut d'un sport est posé sur les nouvelles sorties, pendant sa période de service."""
    sport_id = Classifier(session).classify(Activity(type_key="running", name="Course du soir 1"))[0]
    early = Gear(name="Anciennes", kind="shoes", since=date(2025, 1, 1), retired=date(2025, 3, 31))
    late = Gear(name="Récentes", kind="shoes", since=date(2025, 4, 1))
    session.add_all([early, late])
    session.flush()
    gear.make_default(session, early, [sport_id])
    gear.make_default(session, late, [sport_id])
    assert early.default_sports == []  # même type : le dernier choisi reprend le sport
    early.default_sports = list(late.default_sports)  # les deux, chacun sur sa période
    session.commit()

    sync(session, FakeSource(), today=TODAY, history_days=180)
    acts = session.scalars(select(Activity).where(Activity.sport_id == sport_id)).all()
    assert acts and all(len(a.gear) == 1 for a in acts)
    assert all(a.gear[0] is (early if a.day <= date(2025, 3, 31) else late) for a in acts)
    bike = session.scalar(select(Activity).where(Activity.name == "Vélo dimanche"))
    assert bike.gear == []  # autre sport


def test_gear_pages(client):  # noqa: F811
    assert "Aucun matériel pour l'instant" in client.get("/gear").get_data(as_text=True)
    r = client.post("/gear/add", data={"name": "Chaussures route", "kind": "shoes", "brand": "Asics Novablast 4",
                                       "since": "2025-03-01", "max_km": "1 000", "price": "150",
                                       "photo": (io.BytesIO(image_bytes()), "asics.png")},
                    content_type="multipart/form-data", follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "« Chaussures route » ajouté" in html and 'id="assign"' in html
    client.post("/gear/add", data={"name": "Vélo de route", "kind": "bike", "icon": "bicycle", "color": "#123456"})
    client.post("/gear/add", data={"name": ""})  # refusé
    with dbm.new_session() as s:
        shoes = s.scalar(select(Gear).where(Gear.name == "Chaussures route"))
        bike = s.scalar(select(Gear).where(Gear.kind == "bike"))
        assert shoes.max_km == 1000 and shoes.has_photo and bike.color == "#123456" and s.query(Gear).count() == 2
        sport_id = s.scalar(select(Activity.sport_id).where(Activity.name == "Course du soir 1"))
        shoes_id, bike_id = shoes.id, bike.id
    assert client.get(f"/gear/{shoes_id}/photo.jpg").mimetype == "image/jpeg"
    assert client.get(f"/gear/{bike_id}/photo.jpg").status_code == 404

    # Aperçu puis affectation en bloc, à partir de la mise en service.
    q = {"gear_id": shoes_id, "sport": sport_id, "from": "2025-03-01", "replace": "on"}
    preview = client.get("/gear/assign/preview", query_string=q).get_data(as_text=True)
    assert "recevront « Chaussures route »" in preview
    assert "Coche au moins un sport" in client.get("/gear/assign/preview", query_string={"gear_id": shoes_id}).get_data(as_text=True)
    r = client.post("/gear/assign", data={**q, "make_default": "on"}, follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "affecté à" in html and "prochaines sorties synchronisées" in html and "Usure" in html
    with dbm.new_session() as s:
        g = s.get(Gear, shoes_id)
        n = len(g.activities)
        assert n > 0 and all(a.start.date() >= date(2025, 3, 1) for a in g.activities)
        assert [sp.id for sp in g.default_sports] == [sport_id]

    # Liste : filtre et mini-avatar ; fiche d'une sortie : choix par type.
    listing = client.get(f"/activities?gear={shoes_id}").get_data(as_text=True)
    assert "Matériel : Chaussures route" in listing and f"/gear/{shoes_id}/photo.jpg" in listing
    assert listing.count('class="gear-mini"') == n
    run = act_id("Course du soir 24")
    page = client.get(f"/activities/{run}").get_data(as_text=True)
    assert 'id="gear"' in page and 'name="gear_shoes"' in page and 'name="gear_bike"' in page
    client.post(f"/activities/{run}/gear", data={"gear_shoes": "", "gear_bike": str(bike_id)})
    with dbm.new_session() as s:
        assert [g.name for g in s.get(Activity, run).gear] == ["Vélo de route"]
    client.post(f"/activities/{run}/gear", data={"gear_shoes": str(bike_id)})  # mauvais type : ignoré
    with dbm.new_session() as s:
        assert [g.kind for g in s.get(Activity, run).gear] == ["bike"]

    # Modifier : retrait, sports par défaut retirés ; retrait avant la mise en service refusé.
    r = client.post(f"/gear/{shoes_id}/update", data={"name": "Chaussures route", "kind": "shoes",
                                                      "since": "2025-03-01", "retired": "2025-02-01", "max_km": "1 000"},
                    follow_redirects=True)
    assert "date de retrait" in r.get_data(as_text=True)
    with dbm.new_session() as s:
        g = s.get(Gear, shoes_id)
        assert g.retired is None and g.default_sports == [] and g.max_km == 1000
    assert "Supprimer « Vélo de route »" in client.get(f"/gear/{bike_id}?confirm=1").get_data(as_text=True)
    client.post(f"/gear/{bike_id}/delete")
    with dbm.new_session() as s:
        assert s.get(Gear, bike_id) is None and s.get(Activity, run).gear == []
    assert "Matériel" in client.get("/gear").get_data(as_text=True)
