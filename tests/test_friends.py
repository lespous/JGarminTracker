"""0.9.0 : amis (avec photo) associés aux activités, page Profil et bilan de carrière."""

import io
from datetime import date

import pytest
from PIL import Image
from sqlalchemy import select

from jgarmintracker import db as dbm
from jgarmintracker import photos
from jgarmintracker.models import Activity, Friend, Profile
from jgarmintracker.stats import age_on, career, hr_zones, week_streaks
from jgarmintracker.web import create_app

from .conftest import TODAY, FakeSource


def image_bytes(w=800, h=500, fmt="PNG", color=(200, 60, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, fmt)
    return buf.getvalue()


def test_photo_processing():
    out = photos.process(image_bytes())
    img = Image.open(io.BytesIO(out))
    assert img.format == "JPEG" and img.size == (photos.SIZE, photos.SIZE)
    with pytest.raises(photos.PhotoError):
        photos.process(b"pas une image")
    with pytest.raises(photos.PhotoError):
        photos.process(b"")
    assert photos.initials("Marie", "Dupont") == "MD" and photos.initials("", "") == "?"
    assert photos.hue("Marie Dupont") == photos.hue("Marie Dupont")


def test_streaks_zones_age():
    days = [date(2025, 1, 6), date(2025, 1, 14), date(2025, 1, 21), date(2025, 2, 10), date(2025, 6, 9), date(2025, 6, 17)]
    assert week_streaks(days, TODAY) == (3, 2)  # 3 semaines en janvier ; en cours : S24 + S25
    assert week_streaks([date(2025, 6, 9)], TODAY) == (1, 1)  # semaine courante vide : on compte jusqu'à la précédente
    assert week_streaks([], TODAY) == (0, 0)
    zones, estimated = hr_zones(None, 40)
    assert estimated and zones[0] == ("Échauffement", 90, 108) and zones[-1][2] == 180
    assert hr_zones(190, None)[0][-1] == ("Maximum", 171, 190) and hr_zones(None, None) == ([], True)
    assert age_on(date(1980, 6, 19), TODAY) == 44 and age_on(date(1980, 6, 18), TODAY) == 45


def test_career(synced):
    car = career(synced, TODAY)
    assert car.totals.count == 32 and car.first.name == "Course du soir 1"
    assert car.families[0].family.name == "Course" and car.families[0].records.longest
    assert car.current_streak >= 2


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
    c = app.test_client()
    c.post("/sync")
    return c


def act_id(name):
    with dbm.new_session() as s:
        return s.scalar(select(Activity.id).where(Activity.name == name))


def test_friends_flow(client):
    assert "Aucun ami pour l'instant" in client.get("/friends").get_data(as_text=True)
    r = client.post("/friends/add", data={"first_name": "Léa", "last_name": "Martin", "note": "club du mardi",
                                          "photo": (io.BytesIO(image_bytes()), "lea.png")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "Léa Martin ajouté(e)" in r.get_data(as_text=True)
    client.post("/friends/add", data={"first_name": "Tom"})
    with dbm.new_session() as s:
        lea = s.scalar(select(Friend).where(Friend.first_name == "Léa"))
        tom = s.scalar(select(Friend).where(Friend.first_name == "Tom"))
        assert lea.has_photo and not tom.has_photo
        lea_id, tom_id = lea.id, tom.id
    photo = client.get(f"/friends/{lea_id}/photo.jpg")
    assert photo.status_code == 200 and photo.mimetype == "image/jpeg"
    assert client.get(f"/friends/{lea_id}/photo.jpg", headers={"If-None-Match": photo.headers["ETag"]}).status_code == 304
    assert client.get(f"/friends/{tom_id}/photo.jpg").status_code == 404
    # Avec qui : plusieurs personnes sur une sortie.
    run = act_id("Course du soir 24")
    html = client.get(f"/activities/{run}").get_data(as_text=True)
    assert 'id="friends"' in html and "Léa Martin" in html
    client.post(f"/activities/{run}/friends", data={"friend": [lea_id, tom_id]})
    client.post(f"/activities/{act_id('Vélo dimanche')}/friends", data={"friend": [lea_id]})
    with dbm.new_session() as s:
        assert {f.first_name for f in s.get(Activity, run).friends} == {"Léa", "Tom"}
    listing = client.get(f"/activities?friend={lea_id}").get_data(as_text=True)
    assert "Course du soir 24" in listing and "Vélo dimanche" in listing and "Course du soir 23" not in listing
    assert "Avec Léa Martin" in listing and f'/friends/{lea_id}/photo.jpg' in listing
    page = client.get(f"/friends/{lea_id}").get_data(as_text=True)
    assert "Sorties ensemble" in page and "73 km" in page  # 11 + 62 km
    assert "2 sortie(s) ensemble" in client.get("/friends").get_data(as_text=True)
    # Décocher tout le monde, puis supprimer un ami (les activités restent).
    client.post(f"/activities/{run}/friends", data={})
    client.post(f"/friends/{tom_id}/update", data={"first_name": "Thomas", "remove_photo": "on"})
    assert "Retirer Thomas" in client.get(f"/friends/{tom_id}?confirm=1").get_data(as_text=True)
    client.post(f"/friends/{lea_id}/delete")
    with dbm.new_session() as s:
        assert s.get(Friend, lea_id) is None and s.get(Activity, act_id("Vélo dimanche")).friends == []


def test_friend_nickname(client, tmp_path):
    client.post("/friends/add", data={"first_name": "Marie", "last_name": "Durand", "nickname": "Mimi"})
    with dbm.new_session() as s:
        fr = s.scalar(select(Friend).where(Friend.first_name == "Marie"))
        assert fr.name == "Mimi" and fr.full_name == "Marie Durand"
        fid = fr.id
    page = client.get(f"/friends/{fid}").get_data(as_text=True)
    assert "<h1>Mimi</h1>" in page and "Marie Durand" in page
    client.post(f"/activities/{act_id('Course du soir 24')}/friends", data={"friend": [fid]})
    listing = client.get(f"/activities?friend={fid}").get_data(as_text=True)
    assert "Avec Mimi" in listing and 'title="Mimi"' in listing
    client.post(f"/friends/{fid}/update", data={"first_name": "Marie", "last_name": "Durand", "nickname": ""})
    assert "<h1>Marie Durand</h1>" in client.get(f"/friends/{fid}").get_data(as_text=True)


def test_existing_friends_table_gets_nickname(tmp_path):
    import sqlite3

    path = tmp_path / "v090.db"
    dbm.init_db(path)
    con = sqlite3.connect(path)
    con.execute("ALTER TABLE friends DROP COLUMN nickname")
    con.execute("INSERT INTO friends (first_name, last_name, note, has_photo, created_at) VALUES ('Léo', '', '', 0, '2026-01-01')")
    con.commit()
    con.close()
    dbm.init_db(path)
    with dbm.new_session() as s:
        assert s.scalar(select(Friend)).name == "Léo"


def test_profile(client):
    html = client.get("/profile").get_data(as_text=True)
    assert "Bilan depuis 07/01/2025" in html and "Indique ta FC max" in html
    r = client.post("/profile", data={"first_name": "Jean", "last_name": "Dupont", "nickname": "Jeannot",
                                      "birth_date": "1980-03-01", "sex": "H", "height_cm": "180", "weight_kg": "75,5",
                                      "max_hr": "185", "rest_hr": "48", "city": "Mons", "club": "Les Foulées",
                                      "photo": (io.BytesIO(image_bytes(400, 900, "JPEG")), "moi.jpg")},
                    content_type="multipart/form-data", follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "Profil enregistré" in html and "45 ans" in html and "Zone 5" in html and "167 – 185 bpm" in html
    assert "23,3" in html  # IMC
    assert "Jeannot" in client.get("/").get_data(as_text=True)  # dans la navigation
    assert client.get("/profile/photo.jpg").status_code == 200
    r = client.post("/profile", data={"first_name": "Jean", "max_hr": "400"}, follow_redirects=True)
    assert "FC max (120 à 230)" in r.get_data(as_text=True)
    with dbm.new_session() as s:
        assert s.get(Profile, 1).max_hr == 185  # valeur hors limites ignorée
    r = client.post("/profile", data={"photo": (io.BytesIO(b"rien"), "x.jpg")}, content_type="multipart/form-data",
                    follow_redirects=True)
    assert "Fichier illisible" in r.get_data(as_text=True)
