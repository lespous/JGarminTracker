"""0.20.0 : conditions de distance et de dénivelé dans les règles de sport."""

from types import SimpleNamespace

from sqlalchemy import select

from jgarmintracker import db as dbm
from jgarmintracker.classifier import CompiledRule, rule_text
from jgarmintracker.models import Activity, Sport, SportRule

from .test_friends import client  # noqa: F401  (fixture client réutilisée)


def rule(**kw):
    base = dict(id=1, field="type_key", match_type="contains", pattern="walk", priority=300, sport_id=1,
                min_km=None, min_elev=None, cond_all=False)
    return SimpleNamespace(**{**base, **kw})


def act(km, dplus, key="walking"):
    return SimpleNamespace(type_key=key, name="", distance_m=km * 1000 if km is not None else None, elevation_gain_m=dplus)


def test_conditions():
    any_ = CompiledRule(rule(min_km=12, min_elev=100))
    assert not any_.matches(act(8, 40))
    assert any_.matches(act(13, 40)) and any_.matches(act(5, 150)) and any_.matches(act(15, 300))
    assert not any_.matches(act(12, 100))  # strictement au-dessus
    assert not any_.matches(act(None, None))  # donnée absente
    assert not any_.matches(act(20, 300, key="running"))  # le motif reste obligatoire
    both = CompiledRule(rule(min_km=12, min_elev=100, cond_all=True))
    assert not both.matches(act(13, 40)) and both.matches(act(13, 150))
    assert CompiledRule(rule(min_km=12)).matches(act(12.5, None))
    assert CompiledRule(rule()).matches(act(1, 0))  # sans condition : comme avant
    assert rule_text(rule(min_km=12, min_elev=100)) == "Type Garmin contient « walk » si distance > 12 km ou D+ > 100 m"
    assert rule_text(rule(min_km=12.5, cond_all=True, min_elev=100)).endswith("distance > 12,5 km et D+ > 100 m")
    assert rule_text(rule()) == "Type Garmin contient « walk »"


def test_rule_form(client):  # noqa: F811
    with dbm.new_session() as s:
        hike = s.scalar(select(Sport).where(Sport.name == "Randonnée"))
        hike_id = hike.id
    form = {"field": "type_key", "match_type": "equals", "pattern": "running", "sport_id": hike_id, "priority": "300",
            "min_km": "12", "min_elev": "100", "cond_all": "any"}
    html = client.get("/sports/rules/test", query_string=form).get_data(as_text=True)
    assert "<th class=\"r\">D+</th>" in html
    # parmi les courses (« running »), seules celles au-dessus de 12 km ou 100 m de D+ correspondent
    with dbm.new_session() as s:
        runs = s.scalars(select(Activity).where(Activity.type_key == "running")).all()
        expected = sum(1 for a in runs if (a.distance_m or 0) > 12000 or (a.elevation_gain_m or 0) > 100)
    assert 0 < expected < len(runs) and f"<b>{expected}</b>" in html
    client.post("/sports/rules/save", data=form)
    with dbm.new_session() as s:
        r = s.scalar(select(SportRule).where(SportRule.min_km.is_not(None)))
        assert (r.min_km, r.min_elev, r.cond_all) == (12, 100, False)
        assert "si distance &gt; 12 km ou D+ &gt; 100 m" in client.get("/sports").get_data(as_text=True)
    bad = client.post("/sports/rules/save", data={**form, "min_km": "-3"}, follow_redirects=True)
    assert "plus grand que 0" in bad.get_data(as_text=True)
