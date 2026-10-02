from __future__ import annotations

import json
import os
import threading
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from urllib.parse import quote, urlparse

from flask import Flask, Response, abort, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from .. import __version__, units
from .. import db as dbm
from ..classifier import (
    FIELDS,
    MATCH_TYPES,
    PRIORITY_MANUAL,
    Classifier,
    CompiledRule,
    fallback_sport,
    fold,
    learn_rule,
    reclassify,
    validate_rule,
)
from .. import checks, icons, photos, settings, themes, tracks, weight
from .. import gear as gear_mod
from .. import goals as goals_mod
from .. import maintenance
from ..models import (
    PACE_UNITS,
    Activity,
    ActivityTrack,
    DailyHealth,
    Friend,
    Gear,
    GearService,
    GearTask,
    Goal,
    Profile,
    Sport,
    SportFamily,
    SportRule,
    SyncRun,
    Tag,
    WeightEntry,
)
from ..stats import (
    HEALTH_PERIODS,
    PERIODS,
    age_on,
    career,
    friend_stats,
    hr_zones,
    SPLITS,
    activities_between,
    add_months,
    health_series,
    health_period_bounds,
    health_summary,
    pace_series,
    period_bounds,
    previous_period,
    records,
    totals,
    volume_series,
    week_compare,
    weekly_volume,
)
from ..stats import coverage, month_days
from ..sync import (
    Progress,
    last_run,
    missing_tracks,
    plan as sync_plan,
    sync as run_sync,
    sync_history,
)

SOURCES = {"rule": "règle", "manual": "manuel", "fallback": "par défaut"}
ORIGINS = {"seed": "départ", "learned": "apprise", "manual": "manuelle"}


def db():
    if "db" not in g:
        g.db = dbm.new_session()
    return g.db


def load_families(s):
    return s.scalars(
        select(SportFamily).options(selectinload(SportFamily.sports)).order_by(SportFamily.position)
    ).all()


def parse_date(raw: str | None) -> date | None:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date() if raw else None
    except ValueError:
        return None


def parse_float(raw: str | None) -> float | None:
    """Saisie d'un filtre (« 5 », « 5,5 ») ; une saisie invalide est ignorée plutôt que de casser la page."""
    try:
        text = "".join(ch for ch in (raw or "") if not ch.isspace())  # « 1 000 » affiché avec espace insécable
        return float(text.replace(",", ".")) if text else None
    except ValueError:
        return None


def resolve_selection(s, key: str | None) -> tuple[str, list[int] | None, str, str]:
    """« f3 » (famille) ou « s7 » (sport) -> (libellé, ids des sports, unité d'allure, clé normalisée)."""
    if key and key[:1] in ("f", "s") and key[1:].isdigit():
        if key[0] == "f" and (fam := s.get(SportFamily, int(key[1:]))):
            units_ = [sp.pace_unit for sp in fam.sports]
            unit = max(set(units_), key=units_.count) if units_ else "none"
            return fam.name, [sp.id for sp in fam.sports], unit, key
        if key[0] == "s" and (sp := s.get(Sport, int(key[1:]))):
            return sp.label, [sp.id], sp.pace_unit, key
    return "Tous les sports", None, "none", ""


def back(default: str = "activities"):
    return redirect(request.form.get("next") or request.referrer or url_for(default))


class SyncJob:
    """Synchro lancée depuis l'interface, dans un fil d'exécution à part pour ne pas bloquer la page."""

    def __init__(self):
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.progress: Progress | None = None
        self.started: datetime | None = None

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, make_source, full: bool = False, inline: bool = False, history: dict | None = None) -> bool:
        """history = {start, end, activities, health} : récupération d'une période passée (page Historique)."""
        with self.lock:
            if self.running:
                return False
            self.progress, self.started = Progress("connect"), datetime.now()
            self.thread = threading.Thread(target=self._run, args=(make_source, full, history), daemon=True)
            if inline:
                self._run(make_source, full, history)
                self.thread = None
            else:
                self.thread.start()
            return True

    def _run(self, make_source, full: bool, history: dict | None = None):
        from ..garmin import SyncError

        with dbm.new_session() as s:
            try:
                source = make_source()
            except SyncError as e:
                mode = "history" if history else "full" if full else "incremental"
                s.add(SyncRun(mode=mode, status="error", message=str(e), finished_at=datetime.now()))
                s.commit()
                return
            if history:
                sync_history(s, source, progress=self._on_progress, **history)
            else:
                run_sync(s, source, full=full, progress=self._on_progress, **sync_options(s))

    def _on_progress(self, p: Progress):
        self.progress = p


def sync_options(s) -> dict:
    """Jours re-synchronisés et historique, d'après la page Paramètres."""
    return {"days": settings.get(s, "resync_days"),
            "history_days": round(settings.get(s, "history_months") * 30.44)}


def garmin_source():
    from ..garmin import GarminSource

    return GarminSource.connect()


def create_app(db_path: str | Path | None = None, init: bool = True) -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("JGARMIN_SECRET") or os.urandom(16)
    app.config.setdefault("SYNC_SOURCE", garmin_source)
    app.config.setdefault("SYNC_INLINE", False)
    # CSS / JS revalidés à chaque chargement : une mise à jour de l'appli s'applique sans vider le cache.
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    if init:
        dbm.init_db(db_path)
    job = SyncJob()
    app.extensions["sync_job"] = job

    app.jinja_env.filters.update(
        km=units.km, hms=units.hms, hmm=units.hmm, pace=units.pace, bpm=units.bpm, day=units.day,
        number=units.number, meters=units.meters, weekday_day=units.weekday_day,
        pretty_json=lambda raw: json.dumps(json.loads(raw or "{}"), indent=2, ensure_ascii=False),
    )
    app.jinja_env.globals.update(
        VERSION=__version__, FIELDS=FIELDS, MATCH_TYPES=MATCH_TYPES, PACE_UNITS=PACE_UNITS, SOURCES=SOURCES,
        ORIGINS=ORIGINS, units_bpm=units.bpm, units_h=lambda h: units.hmm(h * 3600), units_int=units.number,
        units_hmm=units.hmm, units_m=units.meters, km_int=lambda m: units.km(m, 0), ICONS=icons.ICONS,
        initials=photos.initials, hue=photos.hue,
        GEAR_KINDS=gear_mod.KINDS, GEAR_ICONS=gear_mod.ICONS, gear_icon=gear_mod.icon_of,
        GOAL_METRICS=goals_mod.METRICS, GOAL_PERIODS=goals_mod.PERIODS, goal_fmt=goals_mod.fmt, goal_title=goals_mod.title,
        TASK_SUGGESTIONS=maintenance.SUGGESTIONS,
    )

    @app.teardown_appcontext
    def close_db(_exc):
        s = g.pop("db", None)
        if s is not None:
            s.close()

    @app.context_processor
    def inject_globals():
        def url_with(**changes):
            args = {**request.args.to_dict(), **changes}
            return url_for(request.endpoint, **(request.view_args or {}),
                           **{k: v for k, v in args.items() if v not in (None, "")})

        s = db()
        mode = settings.get(s, "mode")
        return {
            "url_with": url_with, "sync_running": job.running, "last_sync": last_run(s),
            "ui_layout": settings.get(s, "layout"), "ui_mode": mode if mode in settings.MODES else "system",
            "checks_count": checks.count_issues(s) if request.endpoint not in ("sync_chip", "static") else 0,
            "me": s.get(Profile, 1),
            "weight_due": weight.reminder(s, today()) if request.endpoint not in ("sync_chip", "static") else None,
            "maintenance_due": maintenance.due(s, today()) if request.endpoint not in ("sync_chip", "static") else [],
            "theme_css": themes.theme_css(settings.active_palette(s), mode),
        }

    def today() -> date:
        return date.today()

    # ---------------------------------------------------------------- tableau de bord
    @app.get("/")
    def dashboard():
        s = db()
        has_data = s.scalar(select(func.count(Activity.id))) or s.scalar(select(func.count()).select_from(DailyHealth))
        if not has_data:
            from ..garmin import has_tokens
            return render_template("empty.html", has_tokens=has_tokens())
        metric = "distance" if request.args.get("metric") == "distance" else "duration"
        t = today()
        return render_template(
            "dashboard.html", wc=week_compare(s, t), volume=weekly_volume(s, t, 12, metric), metric=metric,
            health=health_series(s, t, 30), hs=health_summary(s, t, 7), today=t, last_weight=weight.latest(s),
            goals=goals_mod.all_progress(s, t),
            recent=s.scalars(select(Activity).options(joinedload(Activity.sport).joinedload(Sport.family))
                             .where(Activity.excluded.is_(False)).order_by(Activity.start.desc()).limit(6)).all(),
        )

    # ---------------------------------------------------------------- activités
    @app.get("/activities")
    def activities():
        s = db()
        a = request.args
        date_from, date_to = parse_date(a.get("from")), parse_date(a.get("to"))
        label, sport_ids, _unit, sel = resolve_selection(s, a.get("sport"))
        stmt = select(Activity).options(
            joinedload(Activity.sport).joinedload(Sport.family), selectinload(Activity.tags),
            selectinload(Activity.track).defer(ActivityTrack.points_json),  # la mini-carte suffit ici
            selectinload(Activity.friends).defer(Friend.photo), selectinload(Activity.gear),
        )
        if date_from:
            stmt = stmt.where(Activity.start >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            stmt = stmt.where(Activity.start < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
        if sport_ids is not None:
            stmt = stmt.where(Activity.sport_id.in_(sport_ids))
        if (dmin := parse_float(a.get("dmin"))) is not None:
            stmt = stmt.where(Activity.distance_m >= dmin * 1000)
        if (dmax := parse_float(a.get("dmax"))) is not None:
            stmt = stmt.where(Activity.distance_m <= dmax * 1000)
        if (tmin := parse_float(a.get("tmin"))) is not None:
            stmt = stmt.where(Activity.duration_s >= tmin * 60)
        if (tmax := parse_float(a.get("tmax"))) is not None:
            stmt = stmt.where(Activity.duration_s <= tmax * 60)
        if tag_id := a.get("tag", type=int):
            stmt = stmt.where(Activity.tags.any(Tag.id == tag_id))
        if rid := a.get("rule", type=int):
            stmt = stmt.where(Activity.rule_id == rid)
        if a.get("type"):
            stmt = stmt.where(Activity.type_key == a.get("type"))
        if friend_id := a.get("friend", type=int):
            stmt = stmt.where(Activity.friends.any(Friend.id == friend_id))
        if gear_id := a.get("gear", type=int):
            stmt = stmt.where(Activity.gear.any(Gear.id == gear_id))
        if a.get("status") == "excluded":
            stmt = stmt.where(Activity.excluded.is_(True))
        elif a.get("status") == "kept":
            stmt = stmt.where(Activity.excluded.is_(False))
        rows = s.scalars(stmt.order_by(Activity.start.desc())).unique().all()
        session["activities_url"] = request.full_path.rstrip("?")  # pour « Retour » depuis une fiche
        if q := fold(a.get("q")):
            rows = [r for r in rows if q in fold(f"{r.name} {r.type_key}")]
        return render_template(
            "activities.html", rows=rows, families=load_families(s), sel=sel, sel_label=label,
            tags=s.scalars(select(Tag).order_by(Tag.name)).all(), filter_tag=s.get(Tag, tag_id) if tag_id else None,
            filter_rule=s.get(SportRule, rid) if rid else None, date_from=date_from, date_to=date_to,
            friends=s.scalars(select(Friend).order_by(Friend.first_name)).all(),
            filter_friend=s.get(Friend, friend_id) if friend_id else None,
            all_gear=s.scalars(select(Gear).order_by(Gear.kind, Gear.name)).all(),
            filter_gear=s.get(Gear, gear_id) if gear_id else None,
            total_dist=sum(r.distance_m or 0 for r in rows), total_dur=sum(r.duration_s or 0 for r in rows),
        )

    def detail_back_url(act_id: int) -> str:
        """Où renvoie « Retour » dans une fiche : la page d'où on l'a ouverte (retenue tant qu'on reste sur la fiche,
        même après des actions qui rechargent la page), sinon la dernière liste d'activités consultée."""
        ref = request.referrer or ""
        parsed = urlparse(ref)
        own_site = parsed.netloc == request.host
        same_activity = parsed.path.rstrip("/") == request.path.rstrip("/")
        if own_site and ref and not same_activity:
            session["detail_back"] = [act_id, parsed.path + (f"?{parsed.query}" if parsed.query else "")]
        saved = session.get("detail_back")
        if saved and saved[0] == act_id:
            return saved[1]
        return session.get("activities_url") or url_for("activities")

    def gear_choices(s, act: Activity) -> list:
        """Par type : (type, libellé, matériel proposé, matériel actuel). Proposé : en service le jour de la sortie,
        plus celui déjà posé. Types sans aucun matériel enregistré omis."""
        all_gear = s.scalars(select(Gear).order_by(Gear.name)).all()
        out = []
        for kind, (label, _icon, _color) in gear_mod.KINDS.items():
            current = next((g for g in act.gear if g.kind == kind), None)
            items = [g for g in all_gear if g.kind == kind and (g.in_service(act.day) or g is current)]
            if items:
                out.append((kind, label, items, current))
        return out

    @app.get("/activities/<int:act_id>")
    def activity_detail(act_id: int):
        s = db()
        act = s.get(Activity, act_id) or abort(404)
        back_url = detail_back_url(act_id)
        splits = [(label, meters, getattr(act, attr)) for label, meters, attr in SPLITS if getattr(act, attr)]
        points = tracks.loads(act.track.points_json) if act.track and act.track.n_points else []
        return render_template("activity.html", a=act, families=load_families(s), splits=splits, points=points,
                               all_friends=s.scalars(select(Friend).order_by(Friend.first_name)).all(),
                               gear_choices=gear_choices(s, act), back_url=back_url,
                               tags=s.scalars(select(Tag).order_by(Tag.name)).all())

    # ---------------------------------------------------------------- carte de tous les parcours
    @app.get("/map")
    def map_page():
        s = db()
        label, sport_ids, _unit, sel = resolve_selection(s, request.args.get("sport"))
        view = "heat" if request.args.get("view") == "heat" else "routes"
        months = request.args.get("months", type=int)
        months = months if months in (1, 3, 6, 12, 24, 0) else 0 if view == "heat" else 12  # chaleur : tout par défaut
        stmt = (select(Activity, ActivityTrack.points_json)
                .join(ActivityTrack, ActivityTrack.activity_id == Activity.id)
                .options(joinedload(Activity.sport).joinedload(Sport.family))
                .where(ActivityTrack.n_points > 1, Activity.excluded.is_(False)).order_by(Activity.start))
        if months:
            start = add_months(today().replace(day=1), -(months - 1))
            stmt = stmt.where(Activity.start >= datetime.combine(start, datetime.min.time()))
        if sport_ids is not None:
            stmt = stmt.where(Activity.sport_id.in_(sport_ids))
        rows = s.execute(stmt).all()
        routes = [{
            "id": a.id, "name": a.name, "date": units.day(a.start), "sport": a.sport.label if a.sport else "",
            "color": a.sport.color if a.sport else "#888888", "km": units.km(a.distance_m) if a.distance_m else "",
            "url": url_for("activity_detail", act_id=a.id), "points": tracks.thin(tracks.loads(pts), 300),
            "place": json.loads(a.raw_json or "{}").get("locationName") or "Lieu inconnu",
        } for a, pts in rows]
        legend = {}
        for a, _ in rows:
            if a.sport:
                legend.setdefault(a.sport.label, [a.sport.color, 0, a.sport.icon_name])[1] += 1
        places = Counter(r["place"] for r in routes).most_common()
        home, manual = settings.home(s)
        return render_template("map.html", routes=routes, legend=legend, families=load_families(s), sel=sel,
                               label=label, months=months, places=places, home=home, home_manual=manual, view=view,
                               total_km=sum(a.distance_m or 0 for a, _ in rows))

    @app.get("/activities/<int:act_id>/sport")
    def sport_form(act_id: int):
        s = db()
        act = s.get(Activity, act_id) or abort(404)
        sport = s.get(Sport, request.args.get("sport_id", type=int) or 0) or abort(400)
        same_type = [x for x in s.scalars(select(Activity).where(Activity.type_key == act.type_key,
                                                                 Activity.id != act.id)) if not x.sport_locked]
        same_name = [x for x in s.scalars(select(Activity).where(Activity.name == act.name,
                                                                 Activity.id != act.id)) if not x.sport_locked]
        return render_template(
            "_sport_pop.html", a=act, sport=sport, next=request.referrer,
            same_type=len(same_type), type_changing=sum(1 for x in same_type if x.sport_id != sport.id),
            same_name=len(same_name), name_changing=sum(1 for x in same_name if x.sport_id != sport.id),
        )

    @app.post("/activities/<int:act_id>/sport")
    def sport_save(act_id: int):
        s = db()
        act = s.get(Activity, act_id) or abort(404)
        sport = s.get(Sport, request.form.get("sport_id", type=int) or 0) or abort(400)
        act.sport_id, act.sport_locked, act.sport_source, act.rule_id = sport.id, True, "manual", None
        scope = request.form.get("scope", "one")
        if scope in ("type_key", "name") and getattr(act, scope):
            value = getattr(act, scope)
            learn_rule(s, scope, value, sport)
            n = reclassify(s)
            what = f"type Garmin « {value} »" if scope == "type_key" else f"nom « {value} »"
            flash(f"Règle apprise : {what} → {sport.label}. {n} autre(s) activité(s) reclassée(s).")
        else:
            flash(f"« {act.name} » du {units.day(act.start)} classée en {sport.label}.")
        s.commit()
        return back()

    @app.post("/activities/bulk/sport")
    def bulk_sport():
        s = db()
        ids = [int(i) for i in request.form.getlist("act") if i.isdigit()]
        sport = s.get(Sport, request.form.get("sport_id", type=int) or 0)
        if not ids or sport is None:
            flash("Coche au moins une activité et choisis un sport.", "error")
            return back()
        acts = s.scalars(select(Activity).where(Activity.id.in_(ids))).all()
        for act in acts:
            act.sport_id, act.sport_locked, act.sport_source, act.rule_id = sport.id, True, "manual", None
        message = f"{len(acts)} activité(s) classée(s) en {sport.label}."
        if request.form.get("learn") == "on":
            learned = {learn_rule(s, "type_key", act.type_key, sport).id for act in acts if act.type_key}
            n = reclassify(s)
            message += f" {len(learned)} règle(s) apprise(s) par type Garmin, {n} autre(s) activité(s) reclassée(s)."
        s.commit()
        flash(message)
        return back()

    # ---------------------------------------------------------------- amis et profil
    def photo_response(data: bytes | None):
        if not data:
            abort(404)
        tag = photos.etag(data)
        if request.if_none_match.contains(tag):
            return Response(status=304)
        resp = Response(data, mimetype="image/jpeg")
        resp.set_etag(tag)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    def read_photo(field: str = "photo") -> bytes | None:
        """Photo envoyée par le formulaire, recadrée et réduite ; None si aucun fichier. PhotoError si illisible."""
        up = request.files.get(field)
        if not up or not up.filename:
            return None
        return photos.process(up.read())

    def get_profile(s) -> Profile:
        prof = s.get(Profile, 1)
        if prof is None:
            prof = Profile(id=1)
            s.add(prof)
            s.flush()
        return prof

    @app.get("/friends")
    def friends_page():
        s = db()
        rows = []
        for fr in s.scalars(select(Friend).options(selectinload(Friend.activities)).order_by(Friend.first_name,
                                                                                               Friend.last_name)):
            rows.append((fr, friend_stats(fr)))
        rows.sort(key=lambda r: (-r[1].totals.count, r[0].first_name.lower()))
        return render_template("friends.html", rows=rows)

    @app.post("/friends/add")
    def friend_add():
        s = db()
        first = request.form.get("first_name", "").strip()[:80]
        if not first:
            flash("Indique au moins un prénom.", "error")
            return redirect(url_for("friends_page"))
        fr = Friend(first_name=first, last_name=request.form.get("last_name", "").strip()[:80],
                    nickname=request.form.get("nickname", "").strip()[:40], note=request.form.get("note", "").strip())
        try:
            data = read_photo()
        except photos.PhotoError as e:
            flash(str(e), "error")
            data = None
        if data:
            fr.photo, fr.has_photo = data, True
        s.add(fr)
        s.commit()
        flash(f"{fr.name} ajouté(e) à tes amis. Associe-lui des sorties depuis leur fiche.")
        return redirect(url_for("friend_detail", friend_id=fr.id))

    @app.get("/friends/<int:friend_id>")
    def friend_detail(friend_id: int):
        s = db()
        fr = s.get(Friend, friend_id) or abort(404)
        return render_template("friend.html", fr=fr, st=friend_stats(fr), confirm=request.args.get("confirm"))

    @app.post("/friends/<int:friend_id>/update")
    def friend_update(friend_id: int):
        s = db()
        fr = s.get(Friend, friend_id) or abort(404)
        first = request.form.get("first_name", "").strip()[:80]
        if first:
            fr.first_name = first
        fr.last_name = request.form.get("last_name", "").strip()[:80]
        fr.nickname = request.form.get("nickname", "").strip()[:40]
        fr.note = request.form.get("note", "").strip()
        if request.form.get("remove_photo") == "on":
            fr.photo, fr.has_photo = None, False
        try:
            data = read_photo()
        except photos.PhotoError as e:
            flash(str(e), "error")
            data = None
        if data:
            fr.photo, fr.has_photo = data, True
        s.commit()
        flash(f"Fiche de {fr.name} enregistrée.")
        return redirect(url_for("friend_detail", friend_id=fr.id))

    @app.post("/friends/<int:friend_id>/delete")
    def friend_delete(friend_id: int):
        s = db()
        fr = s.get(Friend, friend_id) or abort(404)
        name, n = fr.name, len(fr.activities)
        fr.activities.clear()
        s.delete(fr)
        s.commit()
        flash(f"{name} retiré(e) de tes amis ({n} sortie(s) détachée(s) ; les activités restent).")
        return redirect(url_for("friends_page"))

    @app.get("/friends/<int:friend_id>/photo.jpg")
    def friend_photo(friend_id: int):
        fr = db().get(Friend, friend_id) or abort(404)
        return photo_response(fr.photo)

    @app.post("/activities/<int:act_id>/friends")
    def activity_friends_save(act_id: int):
        """Avec qui : remplace la liste des amis de l'activité par ceux cochés."""
        s = db()
        act = s.get(Activity, act_id) or abort(404)
        ids = [int(i) for i in request.form.getlist("friend") if i.isdigit()]
        act.friends = s.scalars(select(Friend).where(Friend.id.in_(ids))).all() if ids else []
        s.commit()
        names = ", ".join(f.name for f in act.friends)
        flash(f"Sortie faite avec {names}." if names else "Sortie faite seul(e).")
        return redirect(url_for("activity_detail", act_id=act.id) + "#friends")

    @app.get("/profile")
    def profile_page():
        s = db()
        prof = get_profile(s)
        s.commit()
        t = today()
        age = age_on(prof.birth_date, t)
        zones, estimated = hr_zones(prof.max_hr, age)
        bmi = round(prof.weight_kg / (prof.height_cm / 100) ** 2, 1) if prof.weight_kg and prof.height_cm else None
        return render_template("profile.html", prof=prof, age=age, zones=zones, zones_estimated=estimated, bmi=bmi,
                               car=career(s, t), today=t)

    @app.post("/profile")
    def profile_save():
        s = db()
        prof = get_profile(s)
        f = request.form
        for key, size in (("first_name", 80), ("last_name", 80), ("nickname", 40), ("city", 80), ("club", 120)):
            setattr(prof, key, f.get(key, "").strip()[:size])
        prof.sex = f.get("sex") if f.get("sex") in ("F", "H") else ""
        prof.birth_date = parse_date(f.get("birth_date"))
        errors = []
        for key, lo, hi in (("height_cm", 100, 250), ("weight_kg", 25, 250), ("max_hr", 120, 230), ("rest_hr", 25, 120)):
            value = parse_float(f.get(key))
            if value is not None and not lo <= value <= hi:
                errors.append(key)
                continue
            setattr(prof, key, round(value) if value is not None and key.endswith("hr") else value)
        if f.get("remove_photo") == "on":
            prof.photo, prof.has_photo = None, False
        try:
            data = read_photo()
        except photos.PhotoError as e:
            flash(str(e), "error")
            data = None
        if data:
            prof.photo, prof.has_photo = data, True
        s.commit()
        if errors:
            labels = {"height_cm": "taille (100 à 250 cm)", "weight_kg": "poids (25 à 250 kg)",
                      "max_hr": "FC max (120 à 230)", "rest_hr": "FC de repos (25 à 120)"}
            flash("Valeur ignorée : " + ", ".join(labels[e] for e in errors) + ".", "error")
        flash("Profil enregistré.")
        return redirect(url_for("profile_page"))

    @app.get("/profile/photo.jpg")
    def profile_photo():
        prof = db().get(Profile, 1)
        return photo_response(prof.photo if prof else None)

    # ---------------------------------------------------------------- matériel
    def gear_from_form(g: Gear, f) -> list[str]:
        """Remplit g depuis le formulaire ; renvoie les champs ignorés (valeur hors limites)."""
        g.name = f.get("name", "").strip()[:80] or g.name
        g.kind = f.get("kind") if f.get("kind") in gear_mod.KINDS else g.kind or "bike"
        g.brand = f.get("brand", "").strip()[:120]
        g.icon = f.get("icon") if f.get("icon") in gear_mod.ICONS else None
        color = f.get("color", "")
        g.color = color if len(color) == 7 and color.startswith("#") else gear_mod.KINDS[g.kind][2]
        g.since, g.retired = parse_date(f.get("since")), parse_date(f.get("retired"))
        g.note = f.get("note", "").strip()
        ignored = []
        for key, lo, hi, label in (("max_km", 1, 100000, "kilométrage max"), ("price", 0, 100000, "prix")):
            value = parse_float(f.get(key))
            if value is not None and not lo <= value <= hi:
                ignored.append(label)
                value = getattr(g, key)
            setattr(g, key, value)
        if g.since and g.retired and g.retired < g.since:
            g.retired = None
            ignored.append("date de retrait (avant la mise en service)")
        if f.get("remove_photo") == "on":
            g.photo, g.has_photo = None, False
        try:
            data = read_photo()
        except photos.PhotoError as e:
            ignored.append(str(e))
            data = None
        if data:
            g.photo, g.has_photo = data, True
        return ignored

    def gear_rows(s) -> list:
        """(matériel, stats, usure, coût au km) ; en service d'abord, par type puis par nom."""
        rows = []
        for g in s.scalars(select(Gear).options(selectinload(Gear.activities), selectinload(Gear.default_sports))):
            st = friend_stats(g)
            rows.append((g, st, gear_mod.wear(g, st.totals.distance_m), gear_mod.cost_per_km(g, st.totals.distance_m)))
        kinds = list(gear_mod.KINDS)
        rows.sort(key=lambda r: (r[0].retired is not None, kinds.index(r[0].kind) if r[0].kind in kinds else 9,
                                 -(r[0].since or date.min).toordinal(), r[0].name.lower()))
        return rows

    def assign_args(s, src) -> dict:
        g = s.get(Gear, src.get("gear_id", type=int) or 0)
        sport_ids = [int(i) for i in src.getlist("sport") if i.isdigit()]
        return {"g": g, "sport_ids": sport_ids, "start": parse_date(src.get("from")), "end": parse_date(src.get("to")),
                "replace": src.get("replace") == "on", "make_default": src.get("make_default") == "on"}

    @app.get("/gear")
    def gear_page():
        s = db()
        rows = gear_rows(s)
        pre = s.get(Gear, request.args.get("assign", type=int) or 0) or next((r[0] for r in rows if not r[0].retired), None)
        tasks = {r[0].id: [st for st in maintenance.gear_status(s, r[0], today()) if st.due or st.soon] for r in rows}
        return render_template("gear.html", rows=rows, families=load_families(s), pre=pre, tasks=tasks,
                               pre_sports={sp.id for sp in pre.default_sports} if pre else set())

    @app.post("/gear/add")
    def gear_add():
        s = db()
        if not request.form.get("name", "").strip():
            flash("Donne un nom au matériel, par ex. « Vélo de route ».", "error")
            return redirect(url_for("gear_page"))
        g = Gear(name="", kind=request.form.get("kind") if request.form.get("kind") in gear_mod.KINDS else "bike")
        ignored = gear_from_form(g, request.form)
        s.add(g)
        s.commit()
        if ignored:
            flash("Ignoré : " + ", ".join(ignored) + ".", "error")
        flash(f"« {g.name} » ajouté. Affecte-le à tes sorties ci-dessous.")
        return redirect(url_for("gear_page", assign=g.id) + "#assign")

    @app.get("/gear/<int:gear_id>")
    def gear_detail(gear_id: int):
        s = db()
        g = s.get(Gear, gear_id) or abort(404)
        st = friend_stats(g)
        return render_template("gear_item.html", g=g, st=st, w=gear_mod.wear(g, st.totals.distance_m),
                               cost=gear_mod.cost_per_km(g, st.totals.distance_m), families=load_families(s),
                               defaults={sp.id for sp in g.default_sports}, confirm=request.args.get("confirm"),
                               tasks=maintenance.gear_status(s, g, today()), today=today(),
                               task_confirm=request.args.get("task_confirm", type=int))

    @app.post("/gear/<int:gear_id>/update")
    def gear_update(gear_id: int):
        s = db()
        g = s.get(Gear, gear_id) or abort(404)
        ignored = gear_from_form(g, request.form)
        ids = [int(i) for i in request.form.getlist("default_sport") if i.isdigit()]
        g.default_sports = []
        gear_mod.make_default(s, g, ids)
        s.commit()
        if ignored:
            flash("Ignoré : " + ", ".join(ignored) + ".", "error")
        flash(f"« {g.name} » enregistré.")
        return redirect(url_for("gear_detail", gear_id=g.id))

    @app.post("/gear/<int:gear_id>/delete")
    def gear_delete(gear_id: int):
        s = db()
        g = s.get(Gear, gear_id) or abort(404)
        name, n = g.name, len(g.activities)
        g.activities.clear()
        g.default_sports = []
        s.delete(g)
        s.commit()
        flash(f"« {name} » supprimé ({n} sortie(s) détachée(s) ; les activités restent).")
        return redirect(url_for("gear_page"))

    @app.get("/gear/<int:gear_id>/photo.jpg")
    def gear_photo(gear_id: int):
        g = db().get(Gear, gear_id) or abort(404)
        return photo_response(g.photo)

    @app.get("/gear/assign/preview")
    def gear_assign_preview():
        s = db()
        args = assign_args(s, request.args)
        acts = gear_mod.candidates(s, args["sport_ids"], args["start"], args["end"]) if args["g"] else []
        res = gear_mod.plan_assign(acts, args["g"], args["replace"]) if args["g"] else None
        return render_template("_gear_preview.html", acts=acts, res=res, **args)

    @app.post("/gear/assign")
    def gear_assign():
        s = db()
        args = assign_args(s, request.form)
        g = args["g"]
        if g is None or not args["sport_ids"]:
            flash("Choisis un matériel et au moins un sport.", "error")
            return redirect(url_for("gear_page") + "#assign")
        acts = gear_mod.candidates(s, args["sport_ids"], args["start"], args["end"])
        res = gear_mod.assign(acts, g, args["replace"])
        if args["make_default"]:
            gear_mod.make_default(s, g, args["sport_ids"])
        s.commit()
        msg = f"« {g.name} » affecté à {res.changed} sortie(s)"
        details = [f"{res.replaced} à la place d'un autre {gear_mod.kind_label(g.kind).lower()}" if res.replaced else "",
                   f"{res.kept} gardent leur matériel" if res.kept else "", f"{res.already} l'avaient déjà" if res.already else ""]
        msg += (" (" + ", ".join(d for d in details if d) + ")" if any(details) else "") + "."
        if args["make_default"]:
            msg += " Il sera aussi posé sur les prochaines sorties synchronisées de ces sports."
        flash(msg)
        return redirect(url_for("gear_detail", gear_id=g.id))

    @app.post("/activities/<int:act_id>/gear")
    def activity_gear_save(act_id: int):
        """Fiche d'une sortie : un choix par type (ou aucun)."""
        s = db()
        act = s.get(Activity, act_id) or abort(404)
        for kind in gear_mod.KINDS:
            raw = request.form.get(f"gear_{kind}")
            if raw is None:
                continue
            g = s.get(Gear, int(raw)) if raw.isdigit() else None
            gear_mod.set_kind(act, kind, g if g and g.kind == kind else None)
        s.commit()
        names = ", ".join(g.name for g in act.gear)
        flash(f"Matériel : {names}." if names else "Aucun matériel pour cette sortie.")
        return redirect(url_for("activity_detail", act_id=act.id) + "#gear")

    # ---------------------------------------------------------------- entretien du matériel
    @app.post("/gear/<int:gear_id>/tasks/add")
    def gear_task_add(gear_id: int):
        s = db()
        g = s.get(Gear, gear_id) or abort(404)
        name = request.form.get("name", "").strip()[:80]
        every_km = parse_float(request.form.get("every_km"))
        months = parse_float(request.form.get("every_months"))
        every_km = every_km if every_km and every_km > 0 else None
        months = round(months) if months and months >= 1 else None
        if not name or not (every_km or months):
            flash("Donne un nom à l'entretien et au moins un intervalle (km ou mois).", "error")
            return redirect(url_for("gear_detail", gear_id=g.id) + "#maintenance")
        g.tasks.append(GearTask(name=name, every_km=every_km, every_months=months))
        s.commit()
        flash(f"Entretien « {name} » ajouté à {g.name}.")
        return redirect(url_for("gear_detail", gear_id=g.id) + "#maintenance")

    @app.post("/gear/tasks/<int:task_id>/done")
    def gear_task_done(task_id: int):
        s = db()
        task = s.get(GearTask, task_id) or abort(404)
        day = parse_date(request.form.get("day")) or today()
        cost = parse_float(request.form.get("cost"))
        maintenance.mark_done(s, task, min(day, today()), cost if cost and cost > 0 else None,
                              request.form.get("note", "").strip())
        s.commit()
        flash(f"« {task.name} » de {task.gear.name} noté comme fait le {units.day(min(day, today()))}.")
        return redirect(request.form.get("next") or url_for("gear_detail", gear_id=task.gear_id) + "#maintenance")

    @app.post("/gear/tasks/<int:task_id>/delete")
    def gear_task_delete(task_id: int):
        s = db()
        task = s.get(GearTask, task_id) or abort(404)
        gear_id, name = task.gear_id, task.name
        maintenance.delete_task(s, task)
        s.commit()
        flash(f"Entretien « {name} » supprimé (le journal garde ceux déjà faits).")
        return redirect(url_for("gear_detail", gear_id=gear_id) + "#maintenance")

    @app.post("/gear/services/<int:service_id>/delete")
    def gear_service_delete(service_id: int):
        s = db()
        svc = s.get(GearService, service_id) or abort(404)
        gear_id = svc.gear_id
        s.delete(svc)
        s.commit()
        flash("Entretien retiré du journal.")
        return redirect(url_for("gear_detail", gear_id=gear_id) + "#maintenance")

    # ---------------------------------------------------------------- objectifs
    def goal_from_form(goal: Goal, f) -> bool:
        target = parse_float(f.get("target"))
        if f.get("metric") not in goals_mod.METRICS or f.get("period") not in goals_mod.PERIODS or not target or target <= 0:
            return False
        scope = f.get("scope", "")
        goal.metric, goal.period, goal.target = f.get("metric"), f.get("period"), target
        goal.scope = scope if scope[:1] in ("f", "s") and scope[1:].isdigit() else ""
        return True

    @app.post("/goals/add")
    def goal_add():
        s = db()
        goal = Goal(position=(s.scalar(select(func.max(Goal.position))) or 0) + 1)
        if not goal_from_form(goal, request.form):
            flash("Objectif incomplet : choisis la mesure, la période et une cible plus grande que 0.", "error")
        else:
            s.add(goal)
            s.commit()
            label, _ = goals_mod.scope_of(s, goal.scope)
            flash(f"Objectif ajouté : {goals_mod.title(goal, label)}.")
        return redirect((request.form.get("next") or url_for("progress")) + "#goals")

    @app.post("/goals/<int:goal_id>/update")
    def goal_update(goal_id: int):
        s = db()
        goal = s.get(Goal, goal_id) or abort(404)
        if goal_from_form(goal, request.form):
            s.commit()
            flash("Objectif modifié.")
        else:
            flash("Cible invalide : indique un nombre plus grand que 0.", "error")
        return redirect((request.form.get("next") or url_for("progress")) + "#goals")

    @app.post("/goals/<int:goal_id>/delete")
    def goal_delete(goal_id: int):
        s = db()
        goal = s.get(Goal, goal_id) or abort(404)
        s.delete(goal)
        s.commit()
        flash("Objectif supprimé.")
        return redirect((request.form.get("next") or url_for("progress")) + "#goals")

    # ---------------------------------------------------------------- vérifications et exclusions
    @app.post("/activities/bulk/exclude")
    def bulk_exclude():
        """Exclure (ou réintégrer) des activités des statistiques : montre prêtée, sport faux…"""
        s = db()
        ids = [int(i) for i in request.form.getlist("act") if i.isdigit()]
        if not ids:
            flash("Coche au moins une activité.", "error")
            return back()
        action = request.form.get("action", "exclude")
        reason = (request.form.get("reason") or "").strip()[:120] or None
        acts = s.scalars(select(Activity).where(Activity.id.in_(ids))).all()
        for act in acts:
            if action == "include":
                act.excluded, act.exclude_reason = False, None
            else:
                act.excluded, act.exclude_reason = True, reason or "Exclue à la main"
        s.commit()
        if action == "include":
            flash(f"{len(acts)} activité(s) réintégrée(s) dans les statistiques.")
        else:
            flash(f"{len(acts)} activité(s) exclue(s) des statistiques{f' ({reason})' if reason else ''}. "
                  "Elles restent dans la liste des activités.")
        return back()

    @app.post("/activities/<int:act_id>/review")
    def activity_review(act_id: int):
        """« C'est bien moi » : l'activité n'apparaît plus dans les vérifications."""
        s = db()
        act = s.get(Activity, act_id) or abort(404)
        act.review_ok = request.form.get("ok", "1") == "1"
        s.commit()
        flash(f"« {act.name} » du {units.day(act.start)} : "
              + ("vérifiée, plus d'alerte." if act.review_ok else "de nouveau vérifiée automatiquement."))
        return back("checks_page")

    @app.post("/activities/<int:act_id>/ignore-max")
    def activity_ignore_max(act_id: int):
        """Pointe de vitesse aberrante (saut de GPS) : ignorée dans les records et la colonne « Max »."""
        s = db()
        act = s.get(Activity, act_id) or abort(404)
        act.ignore_max_speed = request.form.get("ignore", "1") == "1"
        s.commit()
        flash(f"« {act.name} » du {units.day(act.start)} : pointe de vitesse "
              + ("ignorée." if act.ignore_max_speed else "de nouveau prise en compte."))
        return back("checks_page")

    @app.post("/activities/bulk/ignore-max")
    def bulk_ignore_max():
        s = db()
        ids = [int(i) for i in request.form.getlist("act") if i.isdigit()]
        acts = s.scalars(select(Activity).where(Activity.id.in_(ids))).all() if ids else []
        for act in acts:
            act.ignore_max_speed = True
        s.commit()
        if acts:
            flash(f"Pointe de vitesse ignorée pour {len(acts)} activité(s). Elles comptent toujours dans les statistiques.")
        else:
            flash("Coche au moins une activité.", "error")
        return back("checks_page")

    @app.get("/checks")
    def checks_page():
        s = db()
        found = checks.find_issues(s)
        excluded = s.scalars(select(Activity).options(joinedload(Activity.sport).joinedload(Sport.family))
                             .where(Activity.excluded.is_(True)).order_by(Activity.start.desc())).unique().all()
        ignored = s.scalars(select(Activity).options(joinedload(Activity.sport).joinedload(Sport.family))
                            .where(Activity.ignore_max_speed.is_(True)).order_by(Activity.start.desc())).unique().all()
        reviewed = s.scalar(select(func.count(Activity.id)).where(Activity.review_ok.is_(True)))
        return render_template("checks.html", found=found, excluded=excluded, ignored=ignored, reviewed=reviewed,
                               families=load_families(s), pct=settings.get(s, "unusual_pct"))

    @app.post("/settings/checks")
    def settings_checks():
        s = db()
        out, errors = {}, []
        for fam in load_families(s):
            unit = checks.family_unit(fam)
            if unit == "none":
                continue
            try:
                out[str(fam.id)] = {k: checks.from_display(request.form.get(f"{k}_{fam.id}"), unit) for k in ("avg", "max")}
            except ValueError:
                errors.append(fam.name)
        pct = request.form.get("unusual_pct", type=int)
        if errors or not pct or not 5 <= pct <= 200:
            flash("Valeurs illisibles"
                  + (f" pour : {', '.join(errors)}" if errors else "")
                  + ". Allure au format 2:30, vitesse en km/h, écart entre 5 et 200 %.", "error")
            return redirect(url_for("settings_page") + "#checks")
        settings.put(s, "check_limits", out)
        settings.put(s, "unusual_pct", pct)
        s.commit()
        flash("Limites des vérifications enregistrées.")
        return redirect(url_for("settings_page") + "#checks")

    @app.post("/activities/<int:act_id>/unlock")
    def unlock(act_id: int):
        s = db()
        act = s.get(Activity, act_id) or abort(404)
        act.sport_locked = False
        Classifier(s).apply(act)
        s.commit()
        flash(f"Correction retirée : « {act.name} » est de nouveau classée par les règles ({act.sport.label}).")
        return back()

    # ---------------------------------------------------------------- tags
    @app.post("/activities/bulk/tags")
    def bulk_tags():
        s = db()
        ids = [int(i) for i in request.form.getlist("act") if i.isdigit()]
        name = request.form.get("tag", "").strip()
        action = request.form.get("action", "add")
        if not ids or not name:
            flash("Coche au moins une activité et indique un tag.", "error")
            return back()
        tag = s.scalar(select(Tag).where(Tag.name == name))
        if tag is None and action == "remove":
            flash(f"Le tag « {name} » n'existe pas.", "error")
            return back()
        if tag is None:
            tag = Tag(name=name)
            s.add(tag)
        acts = s.scalars(select(Activity).options(selectinload(Activity.tags)).where(Activity.id.in_(ids))).all()
        changed = 0
        for act in acts:
            if action == "add" and tag not in act.tags:
                act.tags.append(tag)
                changed += 1
            elif action == "remove" and tag in act.tags:
                act.tags.remove(tag)
                changed += 1
        s.commit()
        flash(f"Tag « {tag.name} » {'ajouté à' if action == 'add' else 'retiré de'} {changed} activité(s).")
        return back()

    @app.post("/activities/<int:act_id>/tags/<int:tag_id>/remove")
    def tag_remove(act_id: int, tag_id: int):
        s = db()
        act = s.get(Activity, act_id) or abort(404)
        tag = s.get(Tag, tag_id) or abort(404)
        if tag in act.tags:
            act.tags.remove(tag)
            s.commit()
        return back()

    @app.get("/tags")
    def tags_page():
        s = db()
        rows = []
        for tag in s.scalars(select(Tag).options(selectinload(Tag.activities)).order_by(Tag.name)):
            acts = sorted(tag.activities, key=lambda a: a.start)
            rows.append(SimpleNamespace(
                tag=tag, count=len(acts), distance=sum(a.distance_m or 0 for a in acts),
                duration=sum(a.duration_s or 0 for a in acts), first=acts[0].start if acts else None,
                last=acts[-1].start if acts else None,
            ))
        return render_template("tags.html", rows=rows, confirm=request.args.get("confirm", type=int),
                               rename=request.args.get("rename", type=int))

    @app.post("/tags/<int:tag_id>/rename")
    def tag_rename(tag_id: int):
        s = db()
        tag = s.get(Tag, tag_id) or abort(404)
        name = request.form.get("name", "").strip()
        if not name or s.scalar(select(Tag).where(Tag.name == name, Tag.id != tag.id)):
            flash("Nom vide ou déjà utilisé par un autre tag.", "error")
        else:
            tag.name = name
            s.commit()
            flash(f"Tag renommé en « {name} ».")
        return redirect(url_for("tags_page"))

    @app.post("/tags/<int:tag_id>/delete")
    def tag_delete(tag_id: int):
        s = db()
        tag = s.get(Tag, tag_id) or abort(404)
        name, n = tag.name, len(tag.activities)
        tag.activities.clear()
        s.delete(tag)
        s.commit()
        flash(f"Tag « {name} » supprimé ({n} activité(s) détaguée(s)). Les activités elles-mêmes sont conservées.")
        return redirect(url_for("tags_page"))

    # ---------------------------------------------------------------- progression
    @app.get("/progress")
    def progress():
        s = db()
        families = load_families(s)
        key = request.args.get("sport") or (f"f{families[0].id}" if families else "")
        label, sport_ids, unit, sel = resolve_selection(s, key)
        a = request.args
        t = today()
        period = a.get("period") or (f"{a.get('months')}m" if a.get("months") else "12m")  # ancien lien ?months=6
        first_stmt = select(func.min(Activity.start))
        if sport_ids is not None:
            first_stmt = first_stmt.where(Activity.sport_id.in_(sport_ids))
        first = s.scalar(first_stmt)
        start, end, period = period_bounds(period, t, first.date() if first else None,
                                           parse_date(a.get("from")), parse_date(a.get("to")))
        acts = activities_between(s, start, end, sport_ids)
        prev_start, prev_end = previous_period(start, end)
        prev = totals(activities_between(s, prev_start, prev_end, sport_ids))
        pace = pace_series(acts, unit)
        trend = None
        if (change := pace["change"]) is not None and unit != "none":
            if unit == "kmh":
                trend = SimpleNamespace(faster=change > 0, text=f"{units.number(abs(change), 1)} km/h")
            else:
                suffix = " /km" if unit == "min_km" else " /100 m"
                trend = SimpleNamespace(faster=change < 0, text=units.mmss(abs(change)) + suffix)
        return render_template(
            "progress.html", families=families, sel=sel, label=label, unit=unit, acts=acts,
            volume=volume_series(acts, start, end), pace=pace, trend=trend, rec=records(acts, unit), tot=totals(acts),
            prev=prev, prev_start=prev_start, prev_end=prev_end, start=start, end=end, today=t,
            period=period, PERIODS=PERIODS, goals=goals_mod.all_progress(s, t),
            goal_edit=request.args.get("goal_edit", type=int), goal_confirm=request.args.get("goal_confirm", type=int),
        )

    # ---------------------------------------------------------------- santé
    @app.get("/health")
    def health():
        s = db()
        a = request.args
        t = today()
        key = a.get("period") or {"90": "90d", "365": "365d"}.get(a.get("days", ""), "30d")  # ancien lien ?days=
        first = s.scalar(select(func.min(DailyHealth.day)))
        start, end, key = health_period_bounds(key, t, first, parse_date(a.get("from")), parse_date(a.get("to")))
        days = (end - start).days + 1
        prof = s.get(Profile, 1)
        height = prof.height_cm if prof else None
        return render_template(
            "health.html", days=days, h=health_series(s, end, days), hs=health_summary(s, end, days),
            today=t, start=start, end=end, period=key, PERIODS=HEALTH_PERIODS,
            w=weight.series(s, start, end, height), ws=weight.summary(s, start, end, height), height=height,
            weights=s.scalars(select(WeightEntry).order_by(WeightEntry.day.desc()).limit(12)).all(),
            confirm_weight=a.get("confirm_weight"), bmi_label=weight.bmi_label,
        )

    # ---------------------------------------------------------------- poids
    @app.post("/weight/add")
    def weight_add():
        s = db()
        day = parse_date(request.form.get("day")) or today()
        kg = parse_float(request.form.get("weight_kg"))
        if day > today():
            flash("La date de pesée ne peut pas être dans le futur.", "error")
        elif kg is None:
            flash("Indique ton poids en kg, par exemple 74,5.", "error")
        else:
            try:
                entry = weight.add(s, day, kg)
            except ValueError as e:
                flash(str(e), "error")
            else:
                s.commit()
                flash(f"Pesée du {units.day(entry.day)} enregistrée : {units.number(entry.weight_kg, 1)} kg.")
        return back("health")

    @app.post("/weight/<day>/delete")
    def weight_delete(day: str):
        s = db()
        entry = s.get(WeightEntry, parse_date(day)) or abort(404)
        s.delete(entry)
        s.flush()
        weight.sync_profile(s)
        s.commit()
        flash(f"Pesée du {units.day(entry.day)} supprimée.")
        return redirect(url_for("health") + "#weight")

    @app.post("/settings/weight")
    def settings_weight():
        s = db()
        every = request.form.get("weight_reminder_days", type=int)
        goal = parse_float(request.form.get("weight_goal"))
        if every is None or not 0 <= every <= 90:
            flash("Rappel : un nombre de jours entre 0 (pas de rappel) et 90.", "error")
        elif goal is not None and not weight.MIN_KG <= goal <= weight.MAX_KG:
            flash(f"Objectif : entre {weight.MIN_KG} et {weight.MAX_KG} kg, ou vide.", "error")
        else:
            settings.put(s, "weight_reminder_days", every)
            settings.put(s, "weight_goal", round(goal, 1) if goal else None)
            s.commit()
            flash("Réglages du poids enregistrés.")
        return back("settings_page")

    # ---------------------------------------------------------------- sports et règles
    def rule_from_form(form):
        data = SimpleNamespace(
            field=form.get("field", "type_key"), match_type=form.get("match_type", "equals"),
            pattern=(form.get("pattern") or "").strip(), sport_id=form.get("sport_id", type=int),
            priority=form.get("priority", type=int) or PRIORITY_MANUAL,
            enabled=form.get("enabled", "on") == "on", id=None,
        )
        err = validate_rule(data.field, data.match_type, data.pattern)
        return data, [err] if err else []

    @app.get("/sports")
    def sports():
        s = db()
        a = request.args
        edit = s.get(SportRule, a.get("edit", type=int)) if a.get("edit") else None
        prefill, _ = rule_from_form(a)
        rules = s.scalars(select(SportRule).options(joinedload(SportRule.sport).joinedload(Sport.family))
                          .order_by(SportRule.priority.desc(), SportRule.pattern)).all()
        if q := fold(a.get("q")):
            rules = [r for r in rules if q in fold(f"{r.pattern} {r.sport.label}")]
        hits = dict(s.execute(select(Activity.rule_id, func.count()).group_by(Activity.rule_id)).all())
        counts = dict(s.execute(select(Activity.sport_id, func.count()).group_by(Activity.sport_id)).all())
        type_keys = s.execute(select(Activity.type_key, func.count()).group_by(Activity.type_key)
                              .order_by(func.count().desc())).all()
        return render_template("sports.html", families=load_families(s), rules=rules, hits=hits, counts=counts,
                               edit=edit, f=edit or prefill, type_keys=type_keys,
                               confirm=a.get("confirm", type=int), confirm_family=a.get("confirm_family", type=int))

    @app.get("/sports/rules/test")
    def rules_test():
        s = db()
        data, errors = rule_from_form(request.args)
        if errors:
            return render_template("_rule_test.html", errors=errors, matches=[], changing=0, locked=0, others=0)
        rule = CompiledRule(data)
        matches = [x for x in s.scalars(select(Activity).options(joinedload(Activity.sport).joinedload(Sport.family))
                                        .order_by(Activity.start.desc())) if rule.matches(x)]
        edit_id = request.args.get("id", type=int)
        changing = sum(1 for x in matches if x.sport_id != data.sport_id and not x.sport_locked)
        locked = sum(1 for x in matches if x.sport_locked)
        others = sum(1 for x in matches if x.rule_id and x.rule_id != edit_id and x.sport_id != data.sport_id)
        return render_template("_rule_test.html", errors=[], matches=matches, changing=changing, locked=locked,
                               others=others)

    @app.post("/sports/rules/save")
    def rules_save():
        s = db()
        data, errors = rule_from_form(request.form)
        if not s.get(Sport, data.sport_id or 0):
            errors.append("Choisis un sport.")
        rule_id = request.form.get("id", type=int)
        if errors:
            for e in errors:
                flash(e, "error")
            return redirect(url_for("sports", edit=rule_id) if rule_id else request.referrer or url_for("sports"))
        rule = s.get(SportRule, rule_id) if rule_id else None
        if rule is None:
            rule = SportRule(origin="manual")
            s.add(rule)
        for key in ("field", "match_type", "pattern", "sport_id", "priority", "enabled"):
            setattr(rule, key, getattr(data, key))
        n = reclassify(s)
        s.commit()
        flash(f"Règle #{rule.id} enregistrée. {n} activité(s) reclassée(s).")
        return redirect(url_for("sports") + "#rules")

    @app.post("/sports/rules/<int:rule_id>/toggle")
    def rules_toggle(rule_id: int):
        s = db()
        rule = s.get(SportRule, rule_id) or abort(404)
        rule.enabled = not rule.enabled
        n = reclassify(s)
        s.commit()
        flash(f"Règle #{rule.id} {'activée' if rule.enabled else 'désactivée'}. {n} activité(s) reclassée(s).")
        return redirect(url_for("sports") + "#rules")

    @app.post("/sports/rules/<int:rule_id>/delete")
    def rules_delete(rule_id: int):
        s = db()
        rule = s.get(SportRule, rule_id) or abort(404)
        for act in s.scalars(select(Activity).where(Activity.rule_id == rule_id)):
            act.rule_id = None
        s.delete(rule)
        n = reclassify(s)
        s.commit()
        flash(f"Règle #{rule_id} supprimée. {n} activité(s) reclassée(s).")
        return redirect(url_for("sports") + "#rules")

    @app.post("/sports/rules/reapply")
    def rules_reapply():
        s = db()
        n = reclassify(s)
        s.commit()
        flash(f"Règles réappliquées. {n} activité(s) ont changé de sport.")
        return back("sports")

    @app.post("/sports/add")
    def sport_add():
        s = db()
        name = request.form.get("name", "").strip()
        family = s.get(SportFamily, request.form.get("family_id", type=int) or 0)
        if new_family := request.form.get("new_family", "").strip():
            family = s.scalar(select(SportFamily).where(SportFamily.name == new_family))
            if family is None:
                pos = (s.scalar(select(func.max(SportFamily.position))) or 0) + 1
                family = SportFamily(name=new_family, position=pos)
                s.add(family)
                s.flush()
        if not name or family is None:
            flash("Indique un nom et une famille.", "error")
            return redirect(url_for("sports"))
        if s.scalar(select(Sport).where(Sport.family_id == family.id, Sport.name == name)):
            flash(f"« {name} » existe déjà dans {family.name}.", "error")
            return redirect(url_for("sports"))
        unit = request.form.get("pace_unit", "none")
        guessed = icons.guess_icon(name)
        s.add(Sport(family=family, name=name, color=request.form.get("color") or "#8A94A0",
                    pace_unit=unit if unit in PACE_UNITS else "none", position=99,
                    icon=guessed if guessed != family.icon else None))
        if not family.icon:
            family.icon = icons.guess_icon(family.name)
        s.commit()
        flash(f"Sport « {name} » ajouté dans {family.name}. Ajoute une règle pour y classer des activités.")
        return redirect(url_for("sports"))

    @app.post("/sports/<int:sport_id>/update")
    def sport_update(sport_id: int):
        s = db()
        sport = s.get(Sport, sport_id) or abort(404)
        name = request.form.get("name", "").strip() or sport.name
        family_id = request.form.get("family_id", type=int) or sport.family_id
        clash = s.scalar(select(Sport).where(Sport.family_id == family_id, Sport.name == name, Sport.id != sport.id))
        if clash:
            flash(f"Un autre sport s'appelle déjà « {name} » dans cette famille.", "error")
            return redirect(url_for("sports"))
        sport.name, sport.family_id = name, family_id
        color = request.form.get("color", "")
        if len(color) == 7 and color.startswith("#"):
            sport.color = color
        unit = request.form.get("pace_unit", sport.pace_unit)
        sport.pace_unit = unit if unit in PACE_UNITS else sport.pace_unit
        if "icon" in request.form:
            sport.icon = icons.valid(request.form["icon"])
        s.commit()
        flash(f"Sport « {sport.label} » mis à jour.")
        return redirect(url_for("sports") + f"#sport-{sport.id}")

    @app.post("/sports/<int:sport_id>/delete")
    def sport_delete(sport_id: int):
        s = db()
        sport = s.get(Sport, sport_id) or abort(404)
        if sport.fallback:
            flash("Le sport par défaut « Autre » ne peut pas être supprimé.", "error")
            return redirect(url_for("sports"))
        label = sport.label
        n_rules = remove_sport(s, sport)
        n = reclassify(s)
        s.commit()
        flash(f"Sport « {label} » supprimé avec {n_rules} règle(s). {n} activité(s) reclassée(s).")
        return redirect(url_for("sports"))

    def remove_sport(s, sport: Sport) -> int:
        """Supprime un sport et ses règles ; ses activités repassent par les règles restantes. Renvoie le nb de règles."""
        rules = s.scalars(select(SportRule).where(SportRule.sport_id == sport.id)).all()
        fallback = fallback_sport(s)
        for act in s.scalars(select(Activity).where(Activity.sport_id == sport.id)):
            act.sport_id, act.sport_locked, act.sport_source, act.rule_id = fallback.id, False, "fallback", None
        for act in s.scalars(select(Activity).where(Activity.rule_id.in_([r.id for r in rules]))):
            act.rule_id = None
        for r in rules:
            s.delete(r)
        s.delete(sport)
        s.flush()
        return len(rules)

    @app.post("/families/<int:family_id>/delete")
    def family_delete(family_id: int):
        s = db()
        family = s.get(SportFamily, family_id) or abort(404)
        if any(sp.fallback for sp in family.sports):
            flash(f"La famille « {family.name} » contient le sport par défaut « Autre » : elle ne peut pas être supprimée.",
                  "error")
            return redirect(url_for("sports"))
        name, sports_ = family.name, list(family.sports)
        n_rules = sum(remove_sport(s, sp) for sp in sports_)
        s.delete(family)
        n = reclassify(s)
        s.commit()
        flash(f"Famille « {name} » supprimée avec {len(sports_)} sport(s) et {n_rules} règle(s). "
              f"{n} activité(s) reclassée(s).")
        return redirect(url_for("sports"))

    def _swap(items: list, item, direction: str) -> bool:
        """Échange item avec son voisin (up | down) en renumérotant les positions. False s'il est déjà au bout."""
        i = items.index(item)
        j = i - 1 if direction == "up" else i + 1
        if not 0 <= j < len(items):
            return False
        items[i], items[j] = items[j], items[i]
        for pos, it in enumerate(items):
            it.position = pos
        return True

    @app.post("/families/<int:family_id>/move")
    def family_move(family_id: int):
        s = db()
        family = s.get(SportFamily, family_id) or abort(404)
        _swap(list(load_families(s)), family, request.args.get("dir", "up"))
        s.commit()
        return redirect(url_for("sports") + f"#family-{family.id}")

    @app.post("/sports/<int:sport_id>/move")
    def sport_move(sport_id: int):
        s = db()
        sport = s.get(Sport, sport_id) or abort(404)
        _swap(list(sport.family.sports), sport, request.args.get("dir", "up"))
        s.commit()
        return redirect(url_for("sports") + f"#sport-{sport.id}")

    @app.post("/sports/sort-by-usage")
    def sports_sort_by_usage():
        """Familles puis sports du plus pratiqué au moins pratiqué (« Autre » reste en dernier)."""
        s = db()
        counts = dict(s.execute(select(Activity.sport_id, func.count()).group_by(Activity.sport_id)).all())
        families = list(load_families(s))
        fam_count = {f.id: sum(counts.get(sp.id, 0) for sp in f.sports) for f in families}
        is_other = lambda f: any(sp.fallback for sp in f.sports)  # noqa: E731
        families.sort(key=lambda f: (is_other(f), -fam_count[f.id], f.position))
        for pos, f in enumerate(families):
            f.position = pos
            for spos, sp in enumerate(sorted(f.sports, key=lambda sp: (-counts.get(sp.id, 0), sp.position))):
                sp.position = spos
        s.commit()
        flash("Familles et sports triés du plus pratiqué au moins pratiqué. Cet ordre est repris dans toutes les listes.")
        return redirect(url_for("sports"))

    @app.post("/families/<int:family_id>/rename")
    def family_rename(family_id: int):
        s = db()
        family = s.get(SportFamily, family_id) or abort(404)
        name = request.form.get("name", "").strip()
        icon_changed = "icon" in request.form and icons.valid(request.form["icon"]) != family.icon
        if "icon" in request.form:
            family.icon = icons.valid(request.form["icon"])
        if not name or s.scalar(select(SportFamily).where(SportFamily.name == name, SportFamily.id != family.id)):
            flash("Nom vide ou déjà utilisé par une autre famille.", "error")
        elif name != family.name:
            family.name = name
            flash(f"Famille renommée en « {name} ».")
        elif icon_changed:
            flash(f"Icône de « {name} » mise à jour (reprise par ses sports qui n'ont pas la leur).")
        s.commit()
        return redirect(url_for("sports") + f"#family-{family.id}")

    # ---------------------------------------------------------------- synchronisation
    @app.get("/sync")
    def sync_page():
        from ..garmin import has_tokens, tokens_dir

        s = db()
        runs = s.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(20)).all()
        opts = sync_options(s)
        act_start, health_start = sync_plan(s, today(), False, **opts)
        return render_template(
            "sync.html", runs=runs, has_tokens=has_tokens(), tokens_dir=tokens_dir(), job=job,
            n_acts=s.scalar(select(func.count(Activity.id))),
            n_days=s.scalar(select(func.count()).select_from(DailyHealth)),
            last_ok=s.scalar(select(SyncRun).where(SyncRun.status == "ok").order_by(SyncRun.id.desc()).limit(1)),
            plan=SimpleNamespace(activities=act_start, health=health_start, tracks=len(missing_tracks(s)),
                                 days=opts["days"], months=settings.get(s, "history_months")),
        )

    @app.post("/sync")
    def sync_start():
        started = job.start(app.config["SYNC_SOURCE"], full=request.form.get("full") == "on",
                            inline=app.config["SYNC_INLINE"])
        if not started:
            flash("Une synchro est déjà en cours.", "error")
        nxt = request.form.get("next", "")
        if nxt.startswith("/") and not nxt.startswith("//"):  # depuis la barre de navigation : on reste sur la page
            if started:
                flash("Synchro lancée. L'indicateur de la barre de navigation montre son avancement.")
            return redirect(nxt)
        return redirect(url_for("sync_page"))

    @app.get("/sync/status")
    def sync_status():
        return render_template("_sync_status.html", job=job, run=last_run(db()))

    # ---------------------------------------------------------------- historique
    @app.get("/history")
    def history_page():
        s = db()
        cov = coverage(s)
        t = today()
        oldest = min((y for y, _ in cov), default=t.year)
        first_year = request.args.get("from_year", type=int) or oldest - 2
        first_year = max(2000, min(first_year, oldest))
        years = []
        for y in range(t.year, first_year - 1, -1):
            months = []
            for m in range(1, 13):
                c = cov.get((y, m), {"activities": 0, "tracks": 0, "days": 0})
                future = date(y, m, 1) > t
                total = 0 if future else (t.day if (y, m) == (t.year, t.month) else month_days(y, m))
                months.append({"m": m, "future": future, "total": total, **c,
                               "ratio": round(c["days"] / total, 2) if total else 0})
            years.append({"year": y, "months": months, "activities": sum(x["activities"] for x in months),
                          "days": sum(x["days"] for x in months)})
        js_cov = {f"{y}-{m:02d}": [c["days"], c["activities"], c["tracks"]] for (y, m), c in cov.items()}
        return render_template("history.html", years=years, first_year=first_year, job=job, today=t, cov=js_cov,
                               runs=s.scalars(select(SyncRun).where(SyncRun.mode == "history")
                                              .order_by(SyncRun.id.desc()).limit(10)).all())

    @app.post("/history")
    def history_start():
        f = request.form
        try:
            start = datetime.strptime(f.get("from", ""), "%Y-%m").date()
            end = add_months(datetime.strptime(f.get("to", ""), "%Y-%m").date(), 1) - timedelta(days=1)
        except ValueError:
            flash("Choisis un mois de début et un mois de fin.", "error")
            return redirect(url_for("history_page"))
        if start > end:
            start, end = end.replace(day=1), add_months(start, 1) - timedelta(days=1)
        end = min(end, today())
        acts, health_ = f.get("activities") == "on", f.get("health") == "on"
        if not (acts or health_):
            flash("Coche au moins « activités » ou « santé ».", "error")
            return redirect(url_for("history_page"))
        started = job.start(app.config["SYNC_SOURCE"], inline=app.config["SYNC_INLINE"], history={
            "start": start, "end": end, "activities": acts, "health": health_, "skip_existing": True})
        if started:
            flash(f"Récupération lancée : du {units.day(start)} au {units.day(end)}. Tu peux quitter la page.")
        else:
            flash("Une synchro est déjà en cours : attends qu'elle se termine.", "error")
        return redirect(url_for("history_page"))

    @app.get("/sync/chip")
    def sync_chip():
        return render_template("_sync_chip.html")

    # ---------------------------------------------------------------- GPX
    @app.get("/activities/<int:act_id>.gpx")
    def activity_gpx(act_id: int):
        s = db()
        act = s.get(Activity, act_id) or abort(404)
        if not act.track or act.track.n_points < 2:
            abort(404)
        body = tracks.to_gpx(tracks.loads(act.track.points_json), act.name or "Parcours",
                             act.sport.label if act.sport else "")
        filename = tracks.gpx_filename(act.start, act.name)
        return Response(body, mimetype="application/gpx+xml", headers={
            "Content-Disposition": f"attachment; filename=\"{filename.encode('ascii', 'replace').decode()}\"; "
                                   f"filename*=UTF-8''{quote(filename)}",
        })

    # ---------------------------------------------------------------- paramètres
    @app.get("/settings")
    def settings_page():
        s = db()
        home, manual = settings.home(s)
        lim = checks.limits(s)
        check_rows = []
        for fam in load_families(s):
            unit = checks.family_unit(fam)
            if unit != "none":
                check_rows.append(SimpleNamespace(
                    family=fam, unit=unit, avg=checks.to_display(lim[fam.id]["avg"], unit),
                    max=checks.to_display(lim[fam.id]["max"], unit)))
        return render_template(
            "settings.html", palettes=settings.all_palettes(s), current=settings.get(s, "palette"),
            layout=settings.get(s, "layout"), mode=settings.get(s, "mode"), LAYOUTS=settings.LAYOUTS,
            MODES=settings.MODES, history_months=settings.get(s, "history_months"),
            resync_days=settings.get(s, "resync_days"), auto_sync=settings.get(s, "auto_sync"),
            confirm=request.args.get("confirm"), home=home, home_manual=manual,
            check_rows=check_rows, unusual_pct=settings.get(s, "unusual_pct"),
            weight_reminder_days=settings.get(s, "weight_reminder_days"), weight_goal=settings.get(s, "weight_goal"),
        )

    @app.post("/settings/home")
    def settings_home():
        s = db()
        if request.form.get("reset"):
            settings.put(s, "home", None)
            flash("Domicile : retour au calcul automatique d'après tes départs.")
        else:
            lat, lon = parse_float(request.form.get("lat")), parse_float(request.form.get("lon"))
            if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                flash("Clique sur la carte pour choisir le point.", "error")
                return redirect(url_for("settings_page") + "#home")
            settings.put(s, "home", [round(lat, 5), round(lon, 5)])
            flash("Domicile enregistré.")
        s.commit()
        return redirect(url_for("settings_page") + "#home")

    @app.post("/settings/appearance")
    def settings_appearance():
        s = db()
        f = request.form
        if f.get("layout") in settings.LAYOUTS:
            settings.put(s, "layout", f["layout"])
        if f.get("mode") in settings.MODES:
            settings.put(s, "mode", f["mode"])
        if f.get("palette") in settings.all_palettes(s):
            settings.put(s, "palette", f["palette"])
        s.commit()
        flash("Apparence enregistrée.")
        return back("settings_page")

    @app.post("/settings/mode/toggle")
    def settings_mode_toggle():
        """Bouton soleil / lune : bascule entre clair et sombre (en partant du mode affiché)."""
        s = db()
        shown = request.form.get("shown")
        settings.put(s, "mode", "light" if shown == "dark" else "dark")
        s.commit()
        return back("dashboard")

    @app.post("/settings/sync")
    def settings_sync():
        s = db()
        f = request.form
        months, days = f.get("history_months", type=int), f.get("resync_days", type=int)
        if not months or not 1 <= months <= 120 or not days or not 1 <= days <= 60:
            flash("Historique entre 1 et 120 mois, re-synchronisation entre 1 et 60 jours.", "error")
            return redirect(url_for("settings_page") + "#sync")
        settings.put(s, "history_months", months)
        settings.put(s, "resync_days", days)
        settings.put(s, "auto_sync", f.get("auto_sync") == "on")
        s.commit()
        flash("Réglages de synchro enregistrés.")
        return redirect(url_for("settings_page") + "#sync")

    @app.get("/settings/palettes/new")
    @app.get("/settings/palettes/<pal_id>")
    def palette_form(pal_id: str | None = None):
        s = db()
        pals = settings.all_palettes(s)
        if pal_id:
            pal = next((dict(p, name=n) for n, p in pals.items() if p["id"] == pal_id), None) or abort(404)
        else:
            base = request.args.get("base") if request.args.get("base") in pals else settings.get(s, "palette")
            pal = dict(pals.get(base) or pals[themes.DEFAULT_PALETTE], name="", id=None, base=base)
        return render_template("palette.html", pal=pal, KEYS=themes.KEYS,
                               warnings=themes.contrast_warnings(themes.normalize(pal)))

    @app.post("/settings/palettes/save")
    def palette_save():
        s = db()
        f = request.form
        colors = {m: {k: f.get(f"{m}_{k}", "") for k in themes.KEYS} for m in ("light", "dark")}
        pal_id = f.get("id") or None
        try:
            pal_id = settings.save_palette(s, f.get("name", ""), colors, pal_id)
        except themes.PaletteError as e:
            flash(str(e), "error")
            return redirect(request.referrer or url_for("settings_page"))
        if f.get("activate") == "on":
            settings.put(s, "palette", f.get("name", "").strip()[:60])
        s.commit()
        pal = themes.normalize(colors)
        for w in themes.contrast_warnings(pal):
            flash(w, "error")
        flash(f"Palette « {f.get('name', '').strip()} » enregistrée.")
        return redirect(url_for("palette_form", pal_id=pal_id))

    @app.post("/settings/palettes/<pal_id>/delete")
    def palette_delete(pal_id: str):
        s = db()
        name = settings.delete_palette(s, pal_id)
        s.commit()
        if name:
            flash(f"Palette « {name} » supprimée.")
        else:
            flash("Palette introuvable.", "error")
        return redirect(url_for("settings_page") + "#palettes")

    @app.post("/settings/palettes/import")
    def palette_import():
        s = db()
        try:
            done, skipped = settings.import_palettes(s, request.form.get("json", ""))
        except themes.PaletteError as e:
            s.rollback()
            flash(f"Import impossible : {e}", "error")
            return redirect(url_for("settings_page") + "#import")
        s.commit()
        msg = f"{len(done)} palette(s) importée(s) : {', '.join(done)}." if done else "Aucune palette importée."
        if skipped:
            msg += f" Ignorée(s), car déjà fournie(s) : {', '.join(skipped)}."
        flash(msg)
        return redirect(url_for("settings_page") + "#palettes")

    return app
