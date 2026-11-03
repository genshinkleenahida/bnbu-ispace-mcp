import getpass
import json

import keyring
import pytest

from ispace_mcp import cli
from ispace_mcp import client as C

from conftest import STATE


def test_help(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "login" in out and "deadlines" in out


def test_login_help_has_flags(capsys):
    with pytest.raises(SystemExit):
        cli.main(["login", "--help"])
    out = capsys.readouterr().out
    assert "--show-password" in out and "--file" in out


def test_courses_json(mock_site, capsys):
    cli.main(["courses"])
    assert json.loads(capsys.readouterr().out)[0]["fullname"] == "Course One"


def test_error_exit_code(mock_site, monkeypatch, capsys):
    monkeypatch.setenv("ISPACE_PASSWORD", "nope")
    with pytest.raises(SystemExit) as e:
        cli.main(["courses"])
    assert e.value.code == 1
    assert "nope" not in capsys.readouterr().err


def test_login_hidden_by_default(mock_site, monkeypatch, capsys):
    monkeypatch.delenv("ISPACE_USERNAME")
    monkeypatch.delenv("ISPACE_PASSWORD")
    monkeypatch.setattr("builtins.input", lambda prompt="": "u4000" if "username" in prompt else pytest.fail("echoed"))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": STATE.password)
    cli.main(["login", "--file"])
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert C.credentials_file().exists()


def test_login_show_password_uses_input(mock_site, monkeypatch, capsys):
    monkeypatch.delenv("ISPACE_USERNAME")
    monkeypatch.delenv("ISPACE_PASSWORD")
    monkeypatch.setattr("builtins.input", lambda prompt="": "u4000" if "username" in prompt else STATE.password)
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": pytest.fail("hidden prompt used"))
    cli.main(["login", "--show-password", "--file"])
    assert json.loads(capsys.readouterr().out)["ok"] is True
