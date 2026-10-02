from __future__ import annotations

import getpass
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from . import __version__, settings, units
from . import db as dbm
from .classifier import reclassify as reclassify_all
from .models import Activity, DailyHealth, Sport, SportFamily
from .stats import week_compare

app = typer.Typer(help="JGarminTracker : activités et santé Garmin, en local.", no_args_is_help=True)
console = Console()


def _print_version(value: bool):
    if value:
        console.print(f"JGarminTracker {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    db: Annotated[Optional[Path], typer.Option("--db", help="Fichier SQLite (défaut : $JGARMIN_DB ou ./jgarmin.db)")] = None,
    version: Annotated[bool, typer.Option("--version", "-V", help="Afficher la version et quitter",
                                          callback=_print_version, is_eager=True)] = False,
):
    dbm.init_db(db)


def sport_ids_for(session, name: str | None) -> list[int] | None:
    """Nom de famille (« Course ») ou de sport (« Trail », « Vélo › Route ») -> ids de sports."""
    if not name:
        return None
    sports = session.scalars(select(Sport).options(joinedload(Sport.family))).all()
    wanted = name.casefold()
    ids = [s.id for s in sports if wanted in (s.family.name.casefold(), s.name.casefold(), s.label.casefold())]
    if not ids:
        console.print(f"[red]Sport ou famille « {name} » introuvable. Voir `jgarmin sports`.[/red]")
        raise typer.Exit(1)
    return ids


@app.command()
def login(email: Annotated[Optional[str], typer.Option(help="E-mail Garmin (défaut : $GARMIN_EMAIL)")] = None):
    """Se connecter à Garmin Connect. Le mot de passe n'est jamais enregistré, seulement les jetons de session."""
    from .garmin import SyncError, login as garmin_login, tokens_dir

    email = email or os.environ.get("GARMIN_EMAIL") or typer.prompt("E-mail Garmin")
    password = getpass.getpass("Mot de passe Garmin (non affiché, jamais enregistré) : ")

    def ask_mfa() -> str:
        return typer.prompt("Code de vérification reçu (MFA)").strip()

    try:
        with console.status("Connexion à Garmin Connect…"):
            name = garmin_login(email, password, ask_mfa)
    except SyncError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    finally:
        password = None  # noqa: F841
    console.print(f"[green]Connecté{f' : {name}' if name else ''}.[/green] Jetons enregistrés dans {tokens_dir()}")
    console.print("Lance maintenant `jgarmin sync` (le premier lancement récupère 12 mois, compte quelques minutes).")


@app.command()
def logout():
    """Supprimer les jetons de session enregistrés sur ce PC."""
    from .garmin import logout as garmin_logout

    console.print("Jetons supprimés." if garmin_logout() else "Aucun jeton enregistré.")


@app.command()
def sync(
    days: Annotated[Optional[int], typer.Option(help="Re-synchroniser au moins les N derniers jours (défaut : Paramètres, 3)")] = None,
    full: Annotated[bool, typer.Option("--full", help="Relire tout l'historique (--months)")] = False,
    months: Annotated[Optional[int], typer.Option(help="Historique du premier lancement ou de --full, en mois (défaut : Paramètres, 12)")] = None,
):
    """Récupérer les nouvelles activités et les données santé. Incrémental par défaut."""
    from .garmin import GarminSource, SyncError
    from .sync import sync as run_sync

    try:
        with console.status("Reprise de la session Garmin…"):
            source = GarminSource.connect()
    except SyncError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    columns = (TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), TimeRemainingColumn())
    with Progress(*columns, console=console) as bar, dbm.new_session() as s:
        tasks: dict[str, int] = {}

        def on_progress(p):
            label = {"activities": "Activités", "health": "Santé (jour par jour)", "tracks": "Tracés GPS", "weather": "Météo des sorties"}.get(p.step)
            if not label:
                return
            if p.step not in tasks:
                tasks[p.step] = bar.add_task(label, total=p.total or None)
            desc = f"{label} · {units.day(p.day)}" if p.day else label
            bar.update(tasks[p.step], completed=p.done, total=p.total or None, description=desc)

        days = days or settings.get(s, "resync_days")
        months = months or settings.get(s, "history_months")
        run = run_sync(s, source, full=full, days=days, history_days=round(months * 30.44), progress=on_progress)
    summary = (f"{run.activities_added} activité(s) ajoutée(s), {run.activities_updated} mise(s) à jour ; "
               f"{run.days_added} jour(s) ajouté(s), {run.days_updated} mis à jour ; {run.tracks_added} tracé(s) GPS.")
    if run.status == "ok":
        console.print(f"[green]Synchro terminée.[/green] {summary}")
    else:
        console.print(f"[red]{run.message}[/red]\nDéjà enregistré : {summary}")
        raise typer.Exit(1)


@app.command()
def history(
    from_month: Annotated[datetime, typer.Option("--from", formats=["%Y-%m"], help="Premier mois, AAAA-MM")],
    to_month: Annotated[Optional[datetime], typer.Option("--to", formats=["%Y-%m"], help="Dernier mois (défaut : mois courant)")] = None,
    health_data: Annotated[bool, typer.Option("--health/--no-health", help="Santé jour par jour")] = True,
    activities_data: Annotated[bool, typer.Option("--activities/--no-activities", help="Activités et tracés")] = True,
):
    """Récupérer une période passée (plus ancienne que la première synchro). Les jours déjà en base sont sautés."""
    from .garmin import GarminSource, SyncError
    from .stats import add_months
    from .sync import estimate_seconds, sync_history

    start = from_month.date().replace(day=1)
    end = min(add_months((to_month or datetime.now()).date().replace(day=1), 1) - timedelta(days=1), date.today())
    if start > end:
        console.print("[red]Le premier mois doit précéder le dernier.[/red]")
        raise typer.Exit(1)
    console.print(f"Période : {units.day(start)} → {units.day(end)} · durée estimée jusqu'à "
                  f"{units.hmm(estimate_seconds((end - start).days + 1 if health_data else 0))} (moins si des jours sont déjà en base)")
    try:
        with console.status("Reprise de la session Garmin…"):
            source = GarminSource.connect()
    except SyncError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    columns = (TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), TimeRemainingColumn())
    with Progress(*columns, console=console) as bar, dbm.new_session() as s:
        tasks: dict[str, int] = {}

        def on_progress(p):
            label = {"activities": "Activités", "health": "Santé (jour par jour)", "tracks": "Tracés GPS", "weather": "Météo des sorties"}.get(p.step)
            if not label:
                return
            if p.step not in tasks:
                tasks[p.step] = bar.add_task(label, total=p.total or None)
            bar.update(tasks[p.step], completed=p.done, total=p.total or None,
                       description=f"{label} · {units.day(p.day)}" if p.day else label)

        run = sync_history(s, source, start, end, activities=activities_data, health=health_data, progress=on_progress)
    summary = (f"{run.activities_added} activité(s), {run.days_added} jour(s) de santé, "
               f"{run.tracks_added} tracé(s) ajoutés.")
    if run.status == "ok":
        console.print(f"[green]Historique récupéré.[/green] {summary}")
    else:
        console.print(f"[red]{run.message}[/red]\nDéjà enregistré : {summary}")
        raise typer.Exit(1)


@app.command()
def activities(
    sport: Annotated[Optional[str], typer.Option(help="Famille ou sport, ex. Course, Trail")] = None,
    since: Annotated[Optional[datetime], typer.Option(formats=["%Y-%m-%d"], help="Depuis AAAA-MM-JJ")] = None,
    search: Annotated[Optional[str], typer.Option("--search", "-q", help="Texte dans le nom")] = None,
    limit: Annotated[int, typer.Option(help="Nombre de lignes")] = 30,
):
    """Lister les activités, plus récentes d'abord."""
    with dbm.new_session() as s:
        stmt = select(Activity).options(joinedload(Activity.sport).joinedload(Sport.family))
        if (ids := sport_ids_for(s, sport)) is not None:
            stmt = stmt.where(Activity.sport_id.in_(ids))
        if since:
            stmt = stmt.where(Activity.start >= since)
        if search:
            stmt = stmt.where(Activity.name.ilike(f"%{search}%"))
        rows = s.scalars(stmt.order_by(Activity.start.desc()).limit(limit)).all()
        table = Table("Date", "Sport", "Nom", "Distance", "Durée", "Allure", "FC moy.", "D+")
        for a in rows:
            unit = a.sport.pace_unit if a.sport else "none"
            table.add_row(f"{a.start:%d/%m/%Y %H:%M}", a.sport.label if a.sport else "—", a.name,
                          units.km(a.distance_m) if a.distance_m else "—", units.hms(a.duration_s),
                          units.pace(a.avg_speed, unit), units.bpm(a.avg_hr),
                          units.meters(a.elevation_gain_m) if a.elevation_gain_m else "—")
    console.print(table if rows else "Aucune activité. Lance d'abord `jgarmin sync`.")


@app.command()
def health(days: Annotated[int, typer.Option(help="Nombre de jours")] = 14):
    """FC au repos, sommeil, Body Battery, pas et stress par jour."""
    with dbm.new_session() as s:
        start = date.today() - timedelta(days=days - 1)
        rows = s.scalars(select(DailyHealth).where(DailyHealth.day >= start).order_by(DailyHealth.day.desc())).all()
    table = Table("Jour", "FC repos", "Sommeil", "Profond", "Paradoxal", "Score", "Body Battery", "Pas", "Stress")
    for r in rows:
        bb = f"{r.bb_min}–{r.bb_max}" if r.bb_max is not None else "—"
        table.add_row(units.weekday_day(r.day), units.bpm(r.resting_hr), units.hmm(r.sleep_s), units.hmm(r.deep_s),
                      units.hmm(r.rem_s), str(r.sleep_score or "—"), bb, units.number(r.steps),
                      str(r.stress_avg) if r.stress_avg is not None else "—")
    console.print(table if rows else "Aucune donnée santé. Lance d'abord `jgarmin sync`.")


@app.command()
def week(sport: Annotated[Optional[str], typer.Option(help="Famille ou sport")] = None):
    """Semaine en cours comparée à la précédente."""
    with dbm.new_session() as s:
        wc = week_compare(s, date.today(), sport_ids_for(s, sport))
    scope = f" · {sport}" if sport else ""
    console.print(f"[bold]Semaine du {units.day(wc.monday)}{scope}[/bold] (en cours) vs semaine précédente")
    table = Table("Famille", "Activités", "Distance", "Durée", "Préc. activités", "Préc. distance", "Préc. durée")
    for f in wc.families:
        table.add_row(f.family.name, str(f.current.count), units.km(f.current.distance_m), units.hmm(f.current.duration_s),
                      str(f.previous.count), units.km(f.previous.distance_m), units.hmm(f.previous.duration_s))
    table.add_row("[bold]Total[/bold]", str(wc.current.count), units.km(wc.current.distance_m),
                  units.hmm(wc.current.duration_s), str(wc.previous.count), units.km(wc.previous.distance_m),
                  units.hmm(wc.previous.duration_s))
    console.print(table)


@app.command()
def sports():
    """Sports et familles, avec le nombre d'activités."""
    with dbm.new_session() as s:
        counts = dict(s.execute(select(Activity.sport_id, func.count()).group_by(Activity.sport_id)).all())
        table = Table("Famille", "Sport", "Unité", "Couleur", "Activités")
        for f in s.scalars(select(SportFamily).order_by(SportFamily.position)):
            for sp in f.sports:
                table.add_row(f.name, sp.name, sp.pace_unit, f"[{sp.color}]■[/] {sp.color}", str(counts.get(sp.id, 0)))
    console.print(table)


@app.command()
def reclassify():
    """Réappliquer les règles à toutes les activités non verrouillées."""
    with dbm.new_session() as s:
        n = reclassify_all(s)
        s.commit()
    console.print(f"{n} activité(s) ont changé de sport.")


DEFAULT_PORT = 5003  # 5002 est pris par l'agent Cisco Secure Client sur ce PC


def port_in_use(host: str, port: int) -> bool:
    """Vrai si un programme répond déjà sur ce port. Windows laisse parfois deux serveurs ouvrir le même
    port : le second démarre sans erreur mais ne reçoit jamais les requêtes."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = DEFAULT_PORT,
    debug: Annotated[bool, typer.Option()] = False,
):
    """Lancer l'interface web sur http://127.0.0.1:5003."""
    from .web import create_app

    if port_in_use(host, port):
        console.print(f"[red]Le port {port} est déjà utilisé par un autre programme (ou JGarminTracker tourne déjà).[/red]\n"
                      f"Choisis-en un autre : jgarmin serve --port {port + 1}")
        raise typer.Exit(1)
    console.print(f"JGarminTracker {__version__} : http://{host}:{port}")
    web = create_app(init=False)
    with dbm.new_session() as s:
        auto = settings.get(s, "auto_sync")
    if auto:
        from .garmin import has_tokens
        from .web import garmin_source

        if has_tokens():
            web.extensions["sync_job"].start(garmin_source)
            console.print("Synchro au lancement : en cours en arrière-plan (voir la page Synchronisation).")
        else:
            console.print("[yellow]Synchro au lancement ignorée : pas de session Garmin (lance `jgarmin login`).[/yellow]")
    web.run(host=host, port=port, debug=debug)
