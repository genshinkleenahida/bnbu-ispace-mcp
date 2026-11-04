"""One local mock server standing in for iSpace (Moodle), BNBU SSO and MIS. No network, no real accounts."""
import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from portal_mcp import sm2

PW, TOKEN, NOW = "pw-secret-xyz", "tok_good_123456", int(time.time())
PRIV = secrets.randbelow(sm2.N - 1) + 1
PUB = sm2._mul(PRIV, sm2.G)
PUB_HEX = PUB[0].to_bytes(32, "big").hex() + PUB[1].to_bytes(32, "big").hex()
SEC_A, SEC_B = "a" * 32, "b" * 32
LOG = {"calls": [], "submitted": [], "saved": []}  # reset per test


def decrypt(h: str) -> str:
    raw = bytes.fromhex(h)[1:]
    c1, c3, c2 = (int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:64], "big")), raw[64:96], raw[96:]
    x, y = (v.to_bytes(32, "big") for v in sm2._mul(PRIV, c1))
    return bytes(a ^ b for a, b in zip(c2, sm2._kdf(x + y, len(c2)))).decode()


def moodle(fn: str, p: dict):
    ws = {
        "core_webservice_get_site_info": {"fullname": "Test Student", "userid": 7, "username": "u1", "sitename": "S",
                                          "functions": [{"name": "core_webservice_get_site_info"}]},
        "core_enrol_get_users_courses": [{"id": 11, "shortname": "C1", "fullname": "Course One", "progress": 1}],
        "core_course_get_contents": [{"id": 1, "name": "General", "summary": "", "modules": []}],
        "mod_assign_get_assignments": {"courses": [{"id": 11, "fullname": "Course One", "assignments": [
            {"id": 99, "name": "Essay", "duedate": 2_000_000_000, "intro": "", "introattachments": []}]}]},
        "mod_assign_get_submission_status": {"lastattempt": {"submission": {"status": "new", "plugins": []}}},
        "mod_forum_get_forums_by_courses": [{"id": 31, "course": 11, "name": "Announcements"}],
        "mod_forum_get_forum_discussions": {"discussions": [{"id": 501, "discussion": 41, "name": "Midterm notice",
            "created": NOW - 3600, "userfullname": "Dr. T", "numreplies": 0, "message": "<p>Midterm on <b>6 Nov</b>, 16:00</p>"}]},
        "mod_label_get_labels_by_courses": {"labels": [{"id": 71, "course": 11, "name": "Final", "visible": 1,
            "timemodified": NOW - 7200, "intro": "<p>期末考试在12月</p>"}]},
        "mod_page_get_pages_by_courses": {"pages": []},
        "core_message_get_messages": {"messages": [{"id": 9, "subject": "Hi", "fullmessage": "no keywords here",
            "timecreated": NOW - 500, "userfromfullname": "X"}] if p.get("type") == "notifications" and p.get("read") == "0" else []},
    }
    if fn in ("mod_assign_save_submission", "mod_assign_submit_for_grading"):
        LOG["saved"].append(fn)
        return []
    return ws.get(fn, {"exception": "x", "errorcode": "accessexception", "message": "no such fn"})


def question(sec):
    radios = lambda n, labs: "".join(f'<label><input type="radio" name="{n}" value="{n}{len(labs) - i}">{l}</label>'
                                     for i, l in enumerate(labs))
    return ('<div class="te_info_title_a">Course/Section : Compilers (Dr. X)</div>'
            '<div class="te_part_title">Teaching is good</div>' + radios("q1", ["Strongly Disagree", "Neutral", "Strongly Agree"]) +
            '<div class="te_part_title">Overall</div>' + radios("q2", ["Poor", "Good", "Very good"]) +
            '<div class="te_part_title">Comments (optional)</div><textarea name="txt"></textarea>')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        path, n = urlparse(self.path).path, int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        form = {k: v[0] for k, v in parse_qs(raw.decode(errors="ignore")).items()}
        if path == "/login/token.php":
            return self.reply({"token": TOKEN} if form.get("password") == PW else {"error": "Invalid login", "errorcode": "invalidlogin"})
        if path == "/webservice/rest/server.php":
            LOG["calls"].append(form.get("wsfunction"))
            if form.get("wstoken") != TOKEN:
                return self.reply({"exception": "x", "errorcode": "invalidtoken", "message": "bad token"})
            return self.reply(moodle(form["wsfunction"], form))
        if path == "/auth/pwd/tencent/login":
            ok = decrypt(json.loads(raw)["password"]) == PW
            return self.reply({"data": {"success": ok, "message": "" if ok else "bad password"}})
        if path == "/mis/student/te/submit.do":
            LOG["submitted"].append((parse_qs(urlparse(self.path).query)["sectionId"][0], form))
            return self.reply("ok", "text/html")
        self.send_error(404)

    def do_GET(self):
        u = urlparse(self.path)
        pages = {
            "/auth/flow/login/getSm2PubK": {"data": PUB_HEX},
            "/auth/account/app/list": {"data": [{"url": "3bvkl8pks1ki04nirus0g", "displayName": "mis_2006", "accountNameList": ["u1"]}]},
            "/mis/student/te/home.do": f'<table><tr><td id="{"5" * 32}">Teaching Evaluation 2026</td></tr></table>' if EVAL["open"] else "<p>none</p>",
            "/mis/student/te/section.do": (
                '<table><tr><th>1</th><td>Compilers (1003)</td><td>Dr. A</td><th><button onclick="location=\'question.do?sectionId=' + SEC_A +
                '\'">Evaluate</button></th></tr><tr><th>2</th><td>Done (1001)</td><td>Dr. B</td><th><button disabled="disabled">Evaluated</button></th></tr></table>'),
            "/mis/student/te/question.do": question(parse_qs(u.query).get("sectionId", [""])[0]),
        }
        if u.path.startswith("/auth/sso/login/"):
            return self.reply("<html>ok</html>", "text/html")
        self.reply(pages[u.path], "text/html" if u.path.startswith("/mis") else "application/json") if u.path in pages else self.send_error(404)


EVAL = {"open": True}


@pytest.fixture()
def site(tmp_path, monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}"
    for k in ("ISPACE_TOKEN", "ISPACE_ALLOW_WRITE"):
        monkeypatch.delenv(k, raising=False)
    for k in ("ISPACE_URL", "ISPACE_SSO_URL", "ISPACE_MIS_URL", "ISPACE_OA_URL"):
        monkeypatch.setenv(k, url)
    monkeypatch.setenv("ISPACE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("ISPACE_USERNAME", "u1")
    monkeypatch.setenv("ISPACE_PASSWORD", PW)
    LOG.update(calls=[], submitted=[], saved=[])
    EVAL["open"] = True
    from portal_mcp import tools
    tools._client = tools._portal = None
    yield url
    tools._client = tools._portal = None
    srv.shutdown()
    srv.server_close()
