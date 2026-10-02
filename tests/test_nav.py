"""0.17.0 : menu en catégories avec icônes, pages regroupées en onglets."""

from jgarmintracker import db as dbm
from jgarmintracker import settings
from jgarmintracker.web import nav

from .test_friends import act_id, client  # noqa: F401  (fixture client réutilisée)


def test_owner_and_tabs():
    assert nav.owner("history_page") == "sync_page" and nav.owner("tags_page") == "sports"
    assert nav.owner("review_page") == "progress" and nav.owner("segment_detail") == "map_page"
    assert nav.owner("activity_detail") == "activities" and nav.owner("health") == "health"
    tabs, active = nav.tabs_for("route_detail")
    assert [t[0] for t in tabs] == ["map_page", "routes_page"] and active == "routes_page"
    assert nav.tabs_for("dashboard") is None
    entries = [ep for _t, _i, items in nav.NAV for ep, _l, _ic in items]
    assert len(entries) == 12 and "history_page" not in entries and "tags_page" not in entries


def test_menu_render(client):  # noqa: F811
    html = client.get("/history").get_data(as_text=True)
    assert html.count('class="nav-cat"') == 5  # Sorties, Analyse, Santé, Données, Réglages
    assert 'class="nav-link on" aria-current="page"' in html and "ph-arrows-clockwise" in html
    assert 'class="page-tabs"' in html and "Récupérer l&#39;historique</a>" in html
    assert html.count('class="nav-drop"') == 4  # en-tête : catégories à plusieurs pages
    assert "Tableau de bord" in html and 'href="/history" class="nav-link' not in html  # plus dans le menu
    html = client.get("/").get_data(as_text=True)
    assert 'aria-label="Alerte"' not in html and 'class="page-tabs"' not in html
    # Entretien dû : pastille sur Matériel, remontée sur la catégorie fermée « Sorties » de l'en-tête.
    from sqlalchemy import select

    from jgarmintracker.models import Activity, Gear

    client.post("/gear/add", data={"name": "Vélo", "kind": "bike", "since": "2025-01-01"})
    with dbm.new_session() as s:
        gid = s.scalar(select(Gear.id))
        sport_id = s.scalar(select(Activity.sport_id).where(Activity.name == "Course du soir 1"))
    client.post("/gear/assign", data={"gear_id": gid, "sport": sport_id, "replace": "on"})
    client.post(f"/gear/{gid}/tasks/add", data={"name": "Chaîne", "every_km": "10"})
    html = client.get("/").get_data(as_text=True)
    assert 'aria-label="Alerte"' in html and 'aria-label="Entretien à faire"' in html
    with dbm.new_session() as s:
        settings.put(s, "layout", "col_left")
        s.commit()
    assert "layout-col_left" in client.get(f"/activities/{act_id('Vélo dimanche')}").get_data(as_text=True)


def test_settings_tabs(client):  # noqa: F811
    html = client.get("/settings").get_data(as_text=True)  # onglet par défaut : Apparence
    assert "<h1>Apparence</h1>" in html and 'id="palettes"' in html and 'id="import"' in html and 'id="home"' not in html
    html = client.get("/settings?tab=activities").get_data(as_text=True)
    assert 'id="home"' in html and 'id="checks"' in html and 'id="palettes"' not in html
    assert 'id="weight"' in client.get("/settings?tab=health").get_data(as_text=True)
    assert 'id="sync"' in client.get("/settings?tab=sync").get_data(as_text=True)
    assert "<h1>Apparence</h1>" in client.get("/settings?tab=nimporte").get_data(as_text=True)
    # Les enregistrements reviennent sur le bon onglet, à la bonne section.
    r = client.post("/settings/sync", data={"history_months": "12", "resync_days": "3"})
    assert r.headers["Location"].endswith("/settings?tab=sync#sync")
    r = client.post("/settings/home", data={"reset": "1"})
    assert r.headers["Location"].endswith("/settings?tab=activities#home")
    assert "/settings?tab=health#weight" in client.get("/health").get_data(as_text=True)
