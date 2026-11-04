import json

import pytest

from portal_mcp import cli, client, evaluation, notices, sm2, tools
from portal_mcp.client import ISpaceError
from portal_mcp.server import build
from conftest import EVAL, LOG, NOW, PUB_HEX, PW, SEC_A, TOKEN, decrypt, question


def test_sm2_roundtrip_and_sm3_vector():
    assert sm2.sm3(b"abc").hex() == "66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0"
    assert decrypt(sm2.encrypt(PUB_HEX, "pässword".encode())) == "pässword"


def test_html_to_text_and_time():
    assert client.html_to_text("<p>Hi&nbsp;<b>there</b></p><script>x()</script><ul><li>a</li><li>b</li></ul>").replace("-", "").split() == ["Hi", "there", "a", "b"]
    assert client.fmt_time(0) is None and client.fmt_time(NOW).endswith("UTC+8")


def test_courses_assignments_and_token_never_leaks(site):
    assert tools.list_courses()[0]["fullname"] == "Course One"
    assert tools.list_assignments()[0]["name"] == "Essay"
    with pytest.raises(ISpaceError) as e:
        tools.client().call("no_such_function")
    assert TOKEN not in str(e.value) and PW not in str(e.value)


def test_bad_password_message_has_no_secret(site, monkeypatch):
    monkeypatch.setenv("ISPACE_PASSWORD", "wrong-pw-123")
    with pytest.raises(ISpaceError) as e:
        tools.list_courses()
    assert "wrong-pw-123" not in str(e.value)


def test_search_text_finds_exam_notices_in_english_and_chinese(site):
    hits = tools.search_text()
    assert {h["source"] for h in hits} == {"announcement", "label"}
    assert any("16:00" in s for h in hits for s in h["snippets"])
    assert tools.search_text(keywords=["nomatch"]) == []


def test_new_notices_first_run_then_nothing_new(site):
    first = tools.new_notices(mark_seen=False)
    assert first["first_run"] and len(first["notices"]) == 3  # announcement, label, notification
    tools.new_notices()
    again = tools.new_notices()
    assert not again["first_run"] and again["notices"] == []


def test_watch_once_pushes_one_summary(site):
    pushed, out = [], []
    lines = notices.watch(tools.client(), once=True, out=out.append, push=lambda t, b: pushed.append(b))
    assert len(lines) == 3 and len(pushed) == 1
    assert notices.watch(tools.client(), once=True, out=out.append, push=lambda t, b: pushed.append(b)) == []


def test_notify_never_raises(monkeypatch):
    monkeypatch.setattr(notices.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    assert notices.notify("t", "b") is False


def test_write_tools_hidden_and_gated(site, monkeypatch, tmp_path):
    names = lambda: {t.name for t in build()._tool_manager.list_tools()}
    assert "submit_for_grading" not in names() and "mis_evaluate" not in names() and "list_courses" in names()
    with pytest.raises(ISpaceError):
        tools.submit_for_grading(99, confirm=True)
    monkeypatch.setenv("ISPACE_ALLOW_WRITE", "1")
    assert "submit_for_grading" in names()
    assert tools.submit_for_grading(99)["dry_run"] and LOG["saved"] == []
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert tools.upload_and_save_submission(99, str(f))["dry_run"] and LOG["saved"] == []


def test_mis_evaluations_list_and_closed_is_empty(site):
    ev = tools.mis_evaluations()
    assert [(e["course"], e["status"]) for e in ev] == [("Compilers (1003)", "pending"), ("Done (1001)", "evaluated")]
    EVAL["open"] = False
    assert tools.mis_evaluations() == []


def test_evaluation_picks_best_by_label_not_by_position():
    form = evaluation.parse_form(question(SEC_A))
    plan = evaluation.build_plan(form)
    assert list(plan["answers"].values()) == ["Strongly Agree", "Very good"] and not plan["problems"]
    odd = {"questions": [{"name": "q", "text": "How?", "options": [{"value": "1", "label": "Never"}]}], "texts": []}
    assert evaluation.build_plan(odd)["problems"] and evaluation.build_plan({"questions": [], "texts": []})["problems"]


def test_evaluate_dry_run_then_confirm(site, monkeypatch):
    with pytest.raises(ISpaceError):
        tools.mis_evaluate_all(confirm=True)  # gate: ISPACE_ALLOW_WRITE not set
    monkeypatch.setenv("ISPACE_ALLOW_WRITE", "1")
    dry = tools.mis_evaluate_all()
    assert dry["dry_run"] and len(dry["plans"]) == 1 and LOG["submitted"] == []
    res = tools.mis_evaluate("Compilers", confirm=True)
    assert res["results"][0]["submitted"]
    sec, form = LOG["submitted"][0]
    assert sec == SEC_A and form["q1"] == "q11" and form["Submit"] == "submit"


def test_cli_commands_follow_tools(site, capsys):  # noqa
    cli.main(["search-text", "--keywords", "Midterm"])
    assert json.loads(capsys.readouterr().out)[0]["snippets"]
    cli.main(["mis-evaluations"])
    assert len(json.loads(capsys.readouterr().out)) == 2
    with pytest.raises(SystemExit) as e:
        cli.main(["submit-for-grading", "99", "--confirm"])
    assert "ISPACE_ALLOW_WRITE" in str(e.value.code)


def test_credentials_env_first_then_keychain_login_logout(site, monkeypatch, capsys):
    import keyring
    from keyring.backend import KeyringBackend

    class Mem(KeyringBackend):
        priority = 1
        store: dict = {}
        get_password = lambda self, s, k: self.store.get((s, k))
        set_password = lambda self, s, k, v: self.store.__setitem__((s, k), v)
        delete_password = lambda self, s, k: self.store.pop((s, k))

    keyring.set_keyring(Mem())
    monkeypatch.delenv("ISPACE_USERNAME")
    monkeypatch.delenv("ISPACE_PASSWORD")
    with pytest.raises(ISpaceError):
        client.get_credentials()
    monkeypatch.setattr("builtins.input", lambda *_: "u1")
    monkeypatch.setattr("getpass.getpass", lambda *_: PW)
    cli.main(["login"])
    assert Mem.store == {("ispace-mcp", "username"): "u1", ("ispace-mcp", "password"): PW}
    assert PW not in capsys.readouterr().out and client.get_credentials() == ("u1", PW)
    monkeypatch.setenv("ISPACE_USERNAME", "env-user")
    monkeypatch.setenv("ISPACE_PASSWORD", "env-pw")
    assert client.get_credentials() == ("env-user", "env-pw")
    cli.main(["logout"])
    assert Mem.store == {}
