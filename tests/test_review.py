"""0.16.0 : bilan de l'année et son image à partager."""

import io
from datetime import date

from PIL import Image
from sqlalchemy import select

from jgarmintracker import review, review_card, themes
from jgarmintracker.models import Activity, Friend
from jgarmintracker.stats import activities_between

from .conftest import TODAY
from .test_friends import act_id, client  # noqa: F401  (fixture client réutilisée)


def test_review_partial_year(synced):
    s = synced
    lea = Friend(first_name="Léa")
    s.add(lea)
    bike = s.scalar(select(Activity).where(Activity.name == "Vélo dimanche"))
    bike.friends.append(lea)
    s.flush()
    assert review.years(s) == [2025]
    r = review.review(s, 2025, TODAY)
    acts = activities_between(s, date(2025, 1, 1), TODAY)
    assert r.partial and r.end == TODAY and r.totals.count == len(acts) == 32
    assert r.prev.count == 0 and r.prev_label == "2024 à la même date"
    assert r.projection.count == round(32 * 365 / ((TODAY - date(2025, 1, 1)).days + 1))
    assert r.families[0].family.name == "Course" and abs(sum(f.share for f in r.families) - 100) < 0.01
    assert len(r.months) == 12 and r.months[11]["future"] and r.best_month["count"] > 0
    assert r.longest.name == "Vélo dimanche" and r.active_days == len({a.day for a in acts})
    assert r.friends[0][0].name == "Léa" and r.friends[0][1] == 1
    # Calendrier : chaque jour de 2025 une fois, lundi en haut ; jours après TODAY marqués « à venir ».
    cells = [c for col in r.calendar for c in col if c]
    assert len(cells) == 365 and all(len(col) == 7 for col in r.calendar)
    assert r.calendar[0][2]["day"] == date(2025, 1, 1)  # mercredi
    assert all(c["future"] == (c["day"] > TODAY) for c in cells)
    assert {c["level"] for c in cells if c["load"]} <= {1, 2, 3, 4} and any(c["level"] == 4 for c in cells)
    assert r.weather["n"] > 0 and r.weather["coldest"].weather.temp_c <= r.weather["hottest"].weather.temp_c
    assert r.health["rhr"]


def test_review_card(synced):
    r = review.review(synced, 2025, TODAY)
    data = review_card.render(r, themes.PALETTES[themes.DEFAULT_PALETTE])
    img = Image.open(io.BytesIO(data))
    assert img.format == "PNG" and img.size == (1080, 1350)


def test_review_pages(client):  # noqa: F811
    html = client.get("/review").get_data(as_text=True)
    assert "Bilan 2025" in html and "Projection fin 2025" in html and "Chaque jour de l'année" in html
    assert ">Bilan<" in html and "/review/2025.png" in html and "Télécharger l'image" in html
    assert "Bilan 2025" in client.get("/review?year=1990").get_data(as_text=True)  # année sans sortie : la dernière
    png = client.get("/review/2025.png")
    assert png.mimetype == "image/png" and "attachment" not in png.headers.get("Content-Disposition", "")
    dl = client.get("/review/2025.png?download=1")
    assert 'filename="bilan-2025.png"' in dl.headers["Content-Disposition"]
