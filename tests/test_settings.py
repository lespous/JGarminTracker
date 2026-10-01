"""0.4.0 : GPX, synchro depuis la barre de navigation, Paramètres (disposition, palettes, mode, synchro)."""

import json
import re
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from jgarmintracker import db as dbm
from jgarmintracker import settings, themes, tracks
from jgarmintracker.models import Activity
from jgarmintracker.web import create_app

from .conftest import TODAY, FakeSource

LABS_JSON = json.dumps([
    {"id": "ocean-1a2b", "name": "Océan", "light": {"bg": "#f0f6fa", "surface": "#e2edf4", "tile": "#ffffff",
     "fg": "#0e1a22", "muted": "#4a5d6a", "line": "#cfdde7", "accent": "#0b6e99", "accent_fg": "#ffffff"},
     "dark": {"bg": "#0a1218", "surface": "#13202a", "tile": "#0f1a22", "fg": "#e3edf3", "muted": "#93a8b6",
              "line": "#1f2f3b", "accent": "#4fb3e0", "accent_fg": "#0a1218"}},
    {"id": "vieux", "name": "Ancienne", "light": {"bg": "#ffffff", "fg": "#000000", "accent": "#123456"},
     "dark": {"bg": "#000000", "fg": "#ffffff", "accent": "#abcdef"}},
])


# ---------------------------------------------------------------- thèmes et palettes
def test_labs_palettes_are_complete():
    assert len(themes.PALETTES) == 9 and themes.DEFAULT_PALETTE in themes.PALETTES
    for name, p in themes.PALETTES.items():
        assert themes.normalize(p, strict=True) == {m: p[m] for m in ("light", "dark")}, name
        assert not themes.contrast_warnings(p), name


def test_theme_css_modes():
    pal = themes.PALETTES["Cobalt"]
    system = themes.theme_css(pal, "system")
    assert "#1d4ed8" in system and "prefers-color-scheme: dark" in system and "#6f9bff" in system
    assert "#6f9bff" not in themes.theme_css(pal, "light")
    dark = themes.theme_css(pal, "dark")
    assert "#1d4ed8" not in dark and "color-scheme:dark" in dark


def test_contrast():
    assert themes.contrast("#000000", "#ffffff") == 21.0
    bad = {"light": {**themes.PALETTES["Sarcelle"]["light"], "fg": "#eeeeee"}, "dark": themes.PALETTES["Sarcelle"]["dark"]}
    assert any("texte sur le fond" in w for w in themes.contrast_warnings(bad))


def test_parse_labs_import():
    pals = themes.parse_import(LABS_JSON)
    assert [p["name"] for p in pals] == ["Océan", "Ancienne"]
    assert pals[1]["light"]["tile"] == "#ffffff"  # couleur absente : déduite du fond, comme Labs
    assert themes.parse_import(json.dumps({"name": "Seule", "light": {}, "dark": {}}))[0]["name"] == "Seule"
    for bad in ("pas du json", "[]", json.dumps([{"light": {}}]), json.dumps([{"name": "X", "light": {"bg": "rouge"}}])):
        with pytest.raises(themes.PaletteError):
            themes.parse_import(bad)


def test_old_right_column_setting_becomes_left(session):
    settings.put(session, "layout", "col_right")
    assert settings.get(session, "layout") == "col_left"
    settings.put(session, "layout", "n'importe quoi")
    assert settings.get(session, "layout") == "header"


def test_custom_palettes_crud(session):
    done, skipped = settings.import_palettes(session, LABS_JSON)
    assert done == ["Océan", "Ancienne"] and not skipped
    settings.import_palettes(session, LABS_JSON)  # réimport : mise à jour, pas de doublon
    assert len(settings.get(session, "palettes")) == 2
    _, skipped = settings.import_palettes(session, json.dumps({"name": "Cobalt", "light": {}, "dark": {}}))
    assert skipped == ["Cobalt"]
    pid = settings.get(session, "palettes")[0]["id"]
    settings.put(session, "palette", "Océan")
    settings.save_palette(session, "Océan profond", settings.all_palettes(session)["Océan"], pid)
    assert settings.get(session, "palette") == "Océan profond"  # renommage suivi
    with pytest.raises(themes.PaletteError):
        settings.save_palette(session, "Ancienne", themes.PALETTES["Cobalt"])  # homonyme
    assert settings.delete_palette(session, pid) == "Océan profond"
    assert settings.get(session, "palette") == themes.DEFAULT_PALETTE


# ---------------------------------------------------------------- GPX
def test_gpx_document():
    gpx = tracks.to_gpx([(0.1, 0.2), (0.12345, 0.2)], "Sortie <test> & co", "Vélo › Route")
    assert '<trkpt lat="0.12345" lon="0.20000"/>' in gpx and "Sortie &lt;test&gt; &amp; co" in gpx
    assert "<time>" not in gpx and "hr" not in gpx.lower().replace("trk", "")
    assert tracks.gpx_filename(date(2026, 9, 29), 'A/B: "c"?') == "2026-09-29 A B c.gpx"


# ---------------------------------------------------------------- interface
@pytest.fixture
def app(tmp_path, monkeypatch):
    class FrozenDate(date):
        @classmethod
        def today(cls):
            return TODAY

    monkeypatch.setattr("jgarmintracker.web.date", FrozenDate)
    monkeypatch.setattr("jgarmintracker.sync.date", FrozenDate)
    app = create_app(tmp_path / "web.db")
    app.config.update(TESTING=True, SYNC_INLINE=True, SYNC_SOURCE=FakeSource)
    return app


@pytest.fixture
def client(app):
    c = app.test_client()
    c.post("/sync")
    return c


def act_id(name):
    with dbm.new_session() as s:
        return s.scalar(select(Activity.id).where(Activity.name == name))


def test_gpx_download(client):
    r = client.get(f"/activities/{act_id('Course du soir 1')}.gpx")
    assert r.status_code == 200 and r.mimetype == "application/gpx+xml"
    assert "attachment" in r.headers["Content-Disposition"] and ".gpx" in r.headers["Content-Disposition"]
    assert r.get_data(as_text=True).count("<trkpt") == 61
    assert client.get(f"/activities/{act_id('Renfo maison')}.gpx").status_code == 404
    assert "Télécharger le GPX" in client.get(f"/activities/{act_id('Course du soir 1')}").get_data(as_text=True)
    assert client.get("/activities").get_data(as_text=True).count('class="gpx-btn"') == 25


def test_appearance_applies_to_every_page(client):
    html = client.get("/").get_data(as_text=True)
    assert 'data-mode="system"' in html and "layout-header" in html and "#2a6b62" in html
    client.post("/settings/appearance", data={"layout": "col_left", "mode": "dark", "palette": "Forêt"})
    html = client.get("/activities").get_data(as_text=True)
    assert 'data-mode="dark"' in html and "layout-col_left" in html and "#5cc98f" in html
    client.post("/settings/mode/toggle", data={"shown": "dark"})
    assert 'data-mode="light"' in client.get("/").get_data(as_text=True)
    client.post("/settings/appearance", data={"layout": "pirate", "palette": "Inconnue"})  # valeurs ignorées
    html = client.get("/").get_data(as_text=True)
    assert "layout-col_left" in html and "#1f7a4d" in html


def test_palette_editor_and_import(client):
    assert client.get("/settings").status_code == 200
    assert client.get("/settings/palettes/new?base=Cobalt").status_code == 200
    data = {f"{m}_{k}": c for m in ("light", "dark") for k, c in themes.PALETTES["Cobalt"][m].items()}
    r = client.post("/settings/palettes/save", data={**data, "name": "Ma palette", "activate": "on"}, follow_redirects=True)
    assert "Palette « Ma palette » enregistrée" in r.get_data(as_text=True)
    with dbm.new_session() as s:
        pid = settings.get(s, "palettes")[0]["id"]
        assert settings.get(s, "palette") == "Ma palette"
    assert client.get(f"/settings/palettes/{pid}").status_code == 200
    assert "Supprimer la palette" in client.get(f"/settings?confirm={pid}").get_data(as_text=True)
    client.post(f"/settings/palettes/{pid}/delete")
    r = client.post("/settings/palettes/import", data={"json": LABS_JSON}, follow_redirects=True)
    assert "2 palette(s) importée(s)" in r.get_data(as_text=True) and "Océan" in r.get_data(as_text=True)
    r = client.post("/settings/palettes/import", data={"json": "{oups"}, follow_redirects=True)
    assert "Import impossible" in r.get_data(as_text=True)


def test_sync_settings_and_explicit_button(client, app):
    html = client.get("/sync").get_data(as_text=True)
    assert "Synchroniser depuis le" in html and "16/06/2025" in html  # santé : TODAY − 2 jours
    r = client.post("/settings/sync", data={"history_months": "6", "resync_days": "7"}, follow_redirects=True)
    assert "Réglages de synchro enregistrés" in r.get_data(as_text=True)
    assert "Relire les 6 derniers mois" in client.get("/sync").get_data(as_text=True)
    asked = []

    class Spy(FakeSource):
        def daily_summary(self, day):
            asked.append(day)
            return super().daily_summary(day)

    app.config["SYNC_SOURCE"] = Spy
    r = client.post("/sync", data={"next": "/health?days=90"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/health?days=90")
    assert asked[0] == TODAY - timedelta(days=6)  # 7 jours re-synchronisés
    r = client.post("/settings/sync", data={"history_months": "0", "resync_days": "3"}, follow_redirects=True)
    assert "entre 1 et 120" in r.get_data(as_text=True)
    assert client.post("/sync", data={"next": "//ailleurs.example"}).headers["Location"].endswith("/sync")


def test_nav_chip_and_settings_link(client):
    html = client.get("/progress").get_data(as_text=True)
    chip = re.search(r'<form class="sync-chip".*?</form>', html, re.S).group(0)
    assert 'name="next" value="/progress"' in chip and "Synchroniser" in chip
    assert 'href="/settings"' in html and 'id="mode-toggle"' in html
    assert client.get("/sync/chip").status_code == 200
