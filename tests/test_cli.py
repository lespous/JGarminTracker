from datetime import date

import pytest
from typer.testing import CliRunner

from jgarmintracker import __version__
from jgarmintracker import cli
from jgarmintracker import db as dbm
from jgarmintracker.cli import app
from jgarmintracker.sync import sync

from .conftest import TODAY, FakeSource

runner = CliRunner()


@pytest.fixture
def dbfile(tmp_path, monkeypatch):
    class FrozenDate(date):
        @classmethod
        def today(cls):
            return TODAY

    monkeypatch.setattr("jgarmintracker.cli.date", FrozenDate)
    monkeypatch.setattr(cli.console, "width", 220)  # tableaux Rich sur une ligne
    path = tmp_path / "cli.db"
    dbm.init_db(path)
    with dbm.new_session() as s:
        sync(s, FakeSource(), today=TODAY, history_days=60)
    return str(path)


def run(dbfile, *args):
    result = runner.invoke(app, ["--db", dbfile, *args])
    assert result.exit_code == 0, result.output
    return result.output


def test_version():
    assert __version__ in runner.invoke(app, ["--version"]).output


def test_read_commands(dbfile):
    assert "Course du soir" in run(dbfile, "activities", "--sport", "Course", "--since", "2025-05-01")
    assert "Piscine midi" in run(dbfile, "activities", "-q", "piscine")
    assert "bpm" in run(dbfile, "health", "--days", "14")
    out = run(dbfile, "week")
    assert "16/06/2025" in out and "Course" in out
    assert "Trail" in run(dbfile, "week", "--sport", "Trail")
    assert "Home trainer" in run(dbfile, "sports")
    assert "changé de sport" in run(dbfile, "reclassify")


def test_unknown_sport_is_reported(dbfile):
    result = runner.invoke(app, ["--db", dbfile, "activities", "--sport", "Curling"])
    assert result.exit_code == 1 and "introuvable" in result.output


def test_sync_without_tokens_says_login(dbfile):
    result = runner.invoke(app, ["--db", dbfile, "sync"])
    assert result.exit_code == 1 and "jgarmin login" in result.output


def test_serve_refuses_a_port_already_answering(dbfile):
    import socket

    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert cli.port_in_use("127.0.0.1", port)
        result = runner.invoke(app, ["--db", dbfile, "serve", "--port", str(port)])
    assert result.exit_code == 1 and "déjà utilisé" in result.output


def test_logout_without_tokens(dbfile):
    assert "Aucun jeton" in run(dbfile, "logout")
