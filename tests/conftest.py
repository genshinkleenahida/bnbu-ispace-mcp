"""Local mock Moodle server (token.php, REST, upload.php, pluginfile) for offline tests."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

GOOD_TOKEN = "tok_good_1234567890abcdef"
NOW = 1_800_000_000


class State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.password = "pw-secret-xyz"
        self.token_requests = 0
        self.rest_calls = []
        self.reject_next_token_use = False
        self.disabled = None  # None | "ws" | "service"
        self.uploaded = []
        self.submitted = []


STATE = State()
ASSIGN_DUE = 2_000_000_000


def _rest(fn, p):
    if fn == "core_webservice_get_site_info":
        return {"sitename": "Mock Moodle", "username": "u4000", "fullname": "Test Student", "userid": 7,
                "release": "4.1", "lang": "en", "siteurl": "x", "usercanmanageownfiles": True,
                "functions": [{"name": "core_webservice_get_site_info"}, {"name": "mod_assign_get_assignments"}]}
    if fn == "core_enrol_get_users_courses":
        return [{"id": 11, "shortname": "C1", "fullname": "Course One", "progress": 10, "completed": False,
                 "startdate": NOW, "enddate": 0, "lastaccess": NOW}]
    if fn == "core_course_get_contents":
        return [{"id": 1, "name": "General", "summary": "", "modules": [
            {"id": 5, "instance": 1, "name": "Slides", "modname": "resource", "url": "u", "visible": 1,
             "description": "", "contents": [{"type": "file", "filename": "slides.txt", "filesize": 5,
                                              "mimetype": "text/plain", "timemodified": NOW,
                                              "fileurl": "{base}/pluginfile.php/1/mod_resource/content/1/slides.txt"}]}]}]
    if fn == "mod_assign_get_assignments":
        return {"courses": [{"id": 11, "fullname": "Course One", "assignments": [
            {"id": 99, "cmid": 5, "name": "Essay", "duedate": ASSIGN_DUE, "cutoffdate": 0,
             "allowsubmissionsfromdate": 0, "grade": 100, "intro": "", "introattachments": []}]}]}
    if fn == "mod_assign_get_submission_status":
        return {"lastattempt": {"submission": {"status": "new", "attemptnumber": 0, "timemodified": 0,
                                                "plugins": []}, "canedit": True, "cansubmit": False,
                                "locked": False}}
    if fn == "mod_assign_save_submission":
        STATE.uploaded.append(p)
        return []
    if fn == "mod_assign_submit_for_grading":
        STATE.submitted.append(p)
        return []
    return {"exception": "webservice_access_exception", "errorcode": "accessexception", "message": "no such fn"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200, ctype="application/json", raw=None):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _form(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        if "multipart" in self.headers.get("Content-Type", ""):
            return {}, raw
        return {k: v[0] for k, v in parse_qs(raw.decode()).items()}, raw

    def do_POST(self):
        path = urlparse(self.path).path
        base = f"http://127.0.0.1:{self.server.server_port}"
        p, raw = self._form()
        if path == "/login/token.php":
            STATE.token_requests += 1
            if STATE.disabled == "ws":
                return self._send({"error": "Web services must be enabled in Advanced features.",
                                   "errorcode": "enablewsdescription"})
            if STATE.disabled == "service":
                return self._send({"error": "The requested service (moodle_mobile_app) is not available.",
                                   "errorcode": "servicenotavailable"})
            if p.get("password") != STATE.password:
                return self._send({"error": "Invalid login, please try again", "errorcode": "invalidlogin"})
            return self._send({"token": GOOD_TOKEN})
        if path == "/webservice/rest/server.php":
            STATE.rest_calls.append(p.get("wsfunction"))
            if p.get("wstoken") != GOOD_TOKEN or STATE.reject_next_token_use:
                STATE.reject_next_token_use = False
                return self._send({"exception": "moodle_exception", "errorcode": "invalidtoken",
                                   "message": "Invalid token - token not found"})
            res = _rest(p.get("wsfunction"), p)
            return self._send(json.loads(json.dumps(res).replace("{base}", base)))
        if path == "/webservice/upload.php":
            STATE.uploaded.append(("upload", len(raw)))
            return self._send([{"itemid": 4242, "filename": "a.txt"}])
        self._send({}, 404)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith("/pluginfile.php/"):
            if parse_qs(u.query).get("token", [None])[0] != GOOD_TOKEN:
                return self._send(None, ctype="application/json",
                                  raw=b'{"exception":"moodle_exception","errorcode":"invalidtoken"}')
            return self._send(None, ctype="text/plain", raw=b"hello")
        self._send({}, 404)


@pytest.fixture()
def mock_site(tmp_path, monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    STATE.reset()
    base = f"http://127.0.0.1:{srv.server_port}"
    for k in ("ISPACE_TOKEN", "ISPACE_ALLOW_WRITE", "ISPACE_TZ", "ISPACE_USERNAME", "ISPACE_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ISPACE_URL", base)
    monkeypatch.setenv("ISPACE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("ISPACE_TOKEN_FILE", str(tmp_path / "token"))
    monkeypatch.setenv("ISPACE_USERNAME", "u4000")
    monkeypatch.setenv("ISPACE_PASSWORD", STATE.password)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    import ispace_mcp.ops as ops
    ops._client = None
    yield base
    ops._client = None
    srv.shutdown()
    srv.server_close()
