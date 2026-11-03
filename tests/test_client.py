import json
import os
import stat
import sys

import pytest

from ispace_mcp import client as C
from ispace_mcp import ops
from ispace_mcp.client import ISpaceError, redact, redact_str

from conftest import ASSIGN_DUE, GOOD_TOKEN, STATE

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")


def test_reads(mock_site):
    assert ops.site_info()["fullname"] == "Test Student"
    assert ops.list_courses()[0]["id"] == 11
    a = ops.list_assignments()
    assert a[0]["assignid"] == 99 and "due_ts" not in a[0]
    contents = ops.course_contents(11)
    assert contents[0]["modules"][0]["files"][0]["filename"] == "slides.txt"
    assert ops.submission_status(99)["status"] == "new"


def test_timezone_default_and_override(mock_site, monkeypatch):
    assert ops.list_assignments()[0]["due"].endswith("Asia/Shanghai")
    monkeypatch.setenv("ISPACE_TZ", "UTC")
    assert ops.list_assignments()[0]["due"].endswith(" UTC")
    assert "2033-05-18 03:33" in ops.list_assignments()[0]["due"]


def test_default_url(monkeypatch):
    monkeypatch.delenv("ISPACE_URL", raising=False)
    assert C.base_url() == "https://ispace.bnbu.edu.cn"


def test_token_cached_and_private(mock_site):
    ops.list_courses()
    ops.list_courses()
    assert STATE.token_requests == 1
    f = C.token_file()
    assert json.loads(f.read_text())["token"] == GOOD_TOKEN
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(f).st_mode) == 0o600


def test_refetch_on_invalidtoken(mock_site):
    ops.list_courses()
    STATE.reject_next_token_use = True
    ops.list_courses()
    assert STATE.token_requests == 2


def test_bad_password_message_has_no_secret(mock_site, monkeypatch):
    monkeypatch.setenv("ISPACE_PASSWORD", "wrong-password-123")
    with pytest.raises(ISpaceError) as e:
        ops.site_info()
    assert "Login failed" in str(e.value) and "wrong-password-123" not in str(e.value)


@pytest.mark.parametrize("mode", ["ws", "service"])
def test_disabled_services_message(mock_site, mode):
    STATE.disabled = mode
    with pytest.raises(ISpaceError) as e:
        ops.site_info()
    assert "disabled" in str(e.value)


def test_env_token_used_directly(mock_site, monkeypatch):
    monkeypatch.setenv("ISPACE_TOKEN", GOOD_TOKEN)
    monkeypatch.delenv("ISPACE_USERNAME")
    monkeypatch.delenv("ISPACE_PASSWORD")
    assert ops.list_courses()[0]["id"] == 11
    assert STATE.token_requests == 0
    assert not C.token_file().exists()


def test_env_token_rejected_is_clear_error(mock_site, monkeypatch):
    monkeypatch.setenv("ISPACE_TOKEN", "bad-token")
    with pytest.raises(ISpaceError) as e:
        ops.list_courses()
    assert "ISPACE_TOKEN" in str(e.value) and "bad-token" not in str(e.value)
    assert STATE.token_requests == 0


def test_redaction():
    assert "abc123" not in redact_str("https://x/pluginfile.php/1/a.pdf?token=abc123&forcedownload=1")
    assert redact({"u": ["https://x/?token=SECRET"]}, "SECRET") == {"u": ["https://x/?token=REDACTED"]}
    assert redact_str("tok SECRET end", "SECRET") == "tok REDACTED end"


def test_download_ok_and_host_restriction(mock_site, tmp_path):
    url = ops.course_contents(11)[0]["modules"][0]["files"][0]["fileurl"]
    r = ops.download_file(url, str(tmp_path / "dl"))
    assert open(r["path"], "rb").read() == b"hello"
    r2 = ops.download_file(url, str(tmp_path / "dl"))  # never overwrites
    assert r2["path"] != r["path"]
    with pytest.raises(ISpaceError, match="host must be"):
        ops.download_file("https://evil.example.com/pluginfile.php/1/x.pdf", str(tmp_path / "dl"))


def test_write_gating_ops(mock_site, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    with pytest.raises(ISpaceError, match="disabled"):
        ops.upload_and_save_submission(99, str(f), True)
    with pytest.raises(ISpaceError, match="disabled"):
        ops.submit_for_grading(99, True)


def test_write_dry_run_and_confirm(mock_site, tmp_path, monkeypatch):
    monkeypatch.setenv("ISPACE_ALLOW_WRITE", "1")
    f = tmp_path / "a.txt"
    f.write_text("x")
    d = ops.upload_and_save_submission(99, str(f))
    assert d["dry_run"] is True and STATE.uploaded == []
    d = ops.submit_for_grading(99)
    assert d["dry_run"] is True and STATE.submitted == []
    assert ops.upload_and_save_submission(99, str(f), True)["saved"] is True
    assert ops.submit_for_grading(99, True)["submitted"] is True
    assert len(STATE.submitted) == 1


def test_flatten():
    assert C._flatten({"courseids": [1, 2], "plugindata": {"files_filemanager": 5}, "b": True}) == {
        "courseids[0]": "1", "courseids[1]": "2", "plugindata[files_filemanager]": "5", "b": "1"}
