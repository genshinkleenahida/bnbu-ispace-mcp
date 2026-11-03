"""Credential storage, including the no-keyring fallback (headless Linux, WSL, containers)."""
import json
import os
import stat
import sys

import keyring
import pytest
from keyring.backends import fail

from ispace_mcp import client as C
from ispace_mcp import ops
from ispace_mcp.client import ISpaceError

from conftest import STATE


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        self.d = {}

    def get_password(self, s, u):
        return self.d.get((s, u))

    def set_password(self, s, u, p):
        self.d[(s, u)] = p

    def delete_password(self, s, u):
        self.d.pop((s, u), None)


@pytest.fixture()
def no_env_creds(mock_site, monkeypatch):
    monkeypatch.delenv("ISPACE_USERNAME")
    monkeypatch.delenv("ISPACE_PASSWORD")


@pytest.fixture()
def no_keyring(monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())
    for name in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(keyring, name, getattr(fail.Keyring(), name))


@pytest.fixture()
def mem_keyring(monkeypatch):
    kr = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: kr)
    monkeypatch.setattr(keyring, "get_password", kr.get_password)
    monkeypatch.setattr(keyring, "set_password", kr.set_password)
    monkeypatch.setattr(keyring, "delete_password", kr.delete_password)
    return kr


def test_keyring_roundtrip(no_env_creds, mem_keyring):
    assert C.keyring_available()
    assert C.store_credentials("u4000", STATE.password) == "keyring"
    assert ops.site_info()["userid"] == 7


def test_no_keyring_detected(no_keyring):
    assert not C.keyring_available()


def test_no_keyring_no_creds_is_clear_error(no_env_creds, no_keyring):
    with pytest.raises(ISpaceError, match="No credentials"):
        C.get_credentials()


def test_no_keyring_login_explains_options(no_env_creds, no_keyring):
    with pytest.raises(ISpaceError) as e:
        C.store_credentials("u4000", "pw")
    assert "--file" in str(e.value) and "ISPACE_PASSWORD" in str(e.value)
    assert not C.credentials_file().exists()


def test_no_keyring_env_vars_still_work(mock_site, no_keyring):
    assert ops.list_courses()[0]["id"] == 11


def test_no_keyring_file_fallback(no_env_creds, no_keyring):
    assert C.store_credentials("u4000", STATE.password, use_file=True) == "file"
    f = C.credentials_file()
    assert json.loads(f.read_text())["username"] == "u4000"
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
    assert ops.site_info()["userid"] == 7
    C.delete_credentials()
    assert not f.exists()


def test_env_overrides_file(mock_site, no_keyring, monkeypatch):
    C.store_credentials("someone-else", "other", use_file=True)
    assert C.get_credentials() == ("u4000", STATE.password)
