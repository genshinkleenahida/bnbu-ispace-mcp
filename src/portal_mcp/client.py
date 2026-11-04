"""Moodle web-service client for iSpace, plus shared helpers. Never exposes the token or password."""
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

import httpx

TZ = timezone(timedelta(hours=8))  # BNBU is UTC+8 all year


class ISpaceError(Exception):
    """A clean, token-free error message."""


def base_url() -> str:
    return os.environ.get("ISPACE_URL", "https://ispace.bnbu.edu.cn").rstrip("/")


def write_allowed() -> bool:
    return os.environ.get("ISPACE_ALLOW_WRITE") == "1"


def config_dir() -> Path:
    if os.environ.get("ISPACE_CONFIG_DIR"):
        return Path(os.environ["ISPACE_CONFIG_DIR"]).expanduser()
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "portal-mcp"


def save_private(path: Path, obj) -> None:
    """Write JSON with mode 0600 (on Windows the file inherits your profile's permissions)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


KEYRING_SERVICE = "ispace-mcp"  # entries: "username" and "password"


def get_credentials() -> tuple[str, str]:
    """ISPACE_USERNAME / ISPACE_PASSWORD first, then the OS keychain (saved by `portal-mcp login`)."""
    u, p = os.environ.get("ISPACE_USERNAME"), os.environ.get("ISPACE_PASSWORD")
    if not (u and p):
        try:
            import keyring
            u, p = (keyring.get_password(KEYRING_SERVICE, k) for k in ("username", "password"))
        except Exception:  # no keychain backend (e.g. headless Linux), locked, ...
            u = p = None
    if not (u and p):
        raise ISpaceError("No credentials. Run `portal-mcp login`, or set ISPACE_USERNAME and ISPACE_PASSWORD.")
    return u, p


def redact(obj, token: str = ""):
    if isinstance(obj, str):
        s = re.sub(r"([?&;]token=)[^&\s\"'<>]+", r"\1REDACTED", obj)
        return s.replace(token, "REDACTED") if token else s
    if isinstance(obj, list):
        return [redact(x, token) for x in obj]
    if isinstance(obj, dict):
        return {k: redact(v, token) for k, v in obj.items()}
    return obj


def fmt_time(ts) -> str | None:
    return datetime.fromtimestamp(int(ts), TZ).strftime("%Y-%m-%d %H:%M (%a) UTC+8") if ts else None


def html_to_text(s) -> str:
    """HTML to readable plain text."""
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s or "")
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)</?(p|div|br|tr|h\d|ul|ol|table|blockquote)\b[^>]*>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\n\s*", "\n", re.sub(r"[^\S\n]+", " ", s)).strip()


def _flatten(params: dict, prefix: str = "") -> dict:
    """Moodle array encoding: name[0]=..., name[key]=..."""
    out = {}
    for k, v in params.items():
        key = f"{prefix}[{k}]" if prefix else k
        if isinstance(v, (list, tuple)):
            v = dict(enumerate(v))
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = str(int(v)) if isinstance(v, bool) else str(v)
    return out


class ISpace:
    def __init__(self) -> None:
        self.http = httpx.Client(timeout=60, follow_redirects=True)
        self._token = None
        self._uid = None

    def token(self) -> str:
        if not self._token:
            self._token = os.environ.get("ISPACE_TOKEN") or self._login()
        return self._token

    def _login(self) -> str:
        user, pw = get_credentials()
        try:
            d = self.http.post(f"{base_url()}/login/token.php",
                               data={"username": user, "password": pw, "service": "moodle_mobile_app"}).json()
        except (httpx.HTTPError, ValueError) as e:
            raise ISpaceError(f"Could not log in to iSpace ({type(e).__name__}).") from None
        if "token" not in d:
            raise ISpaceError("iSpace login failed: " + redact(str(d.get("error", "unknown error")), pw))
        return d["token"]

    def call(self, fn: str, **params):
        for retry in (True, False):
            tok = self.token()
            try:
                d = self.http.post(f"{base_url()}/webservice/rest/server.php", data={
                    **_flatten(params), "wstoken": tok, "wsfunction": fn, "moodlewsrestformat": "json"}).json()
            except (httpx.HTTPError, ValueError) as e:
                raise ISpaceError(f"{fn}: request failed ({type(e).__name__})") from None
            if isinstance(d, dict) and d.get("exception"):
                if retry and d.get("errorcode") == "invalidtoken" and not os.environ.get("ISPACE_TOKEN"):
                    self._token = None  # expired: log in again once
                    continue
                raise ISpaceError(f"{fn}: {redact(str(d.get('message')), tok)}")
            return redact(d, tok)

    def userid(self) -> int:
        self._uid = self._uid or int(self.call("core_webservice_get_site_info")["userid"])
        return self._uid

    def site_info(self) -> dict:
        d = self.call("core_webservice_get_site_info")
        return {k: d.get(k) for k in ("sitename", "fullname", "userid", "release")} | {
            "functions": sorted(f["name"] for f in d.get("functions", []))}

    def courses(self) -> list[dict]:
        return [{"id": c["id"], "shortname": c.get("shortname"), "fullname": c.get("fullname"),
                 "progress": c.get("progress")}
                for c in self.call("core_enrol_get_users_courses", userid=self.userid())]

    def course_contents(self, courseid: int) -> list[dict]:
        return [{"section": s.get("name"), "modules": [
            {"name": m.get("name"), "type": m.get("modname"), "files": [
                {"filename": f.get("filename"), "filesize": f.get("filesize"), "fileurl": f.get("fileurl")}
                for f in m.get("contents", []) if f.get("type") == "file"]}
            for m in s.get("modules", [])]} for s in self.call("core_course_get_contents", courseid=int(courseid))]

    def assignments(self, courseids=None) -> list[dict]:
        ids = courseids or [c["id"] for c in self.courses()]
        d = self.call("mod_assign_get_assignments", courseids=[int(x) for x in ids])
        return [{"assignid": a["id"], "course": c.get("fullname"), "name": a.get("name"),
                 "due": fmt_time(a.get("duedate")), "due_ts": a.get("duedate") or 0,
                 "intro": html_to_text(a.get("intro")),
                 "attachments": [{"filename": f.get("filename"), "fileurl": f.get("fileurl")}
                                 for f in a.get("introattachments", [])]}
                for c in d.get("courses", []) for a in c.get("assignments", [])]

    def submission_status(self, assignid: int) -> dict:
        d = self.call("mod_assign_get_submission_status", assignid=int(assignid))
        last = d.get("lastattempt") or {}
        sub = last.get("submission") or {}
        files = [{"filename": f.get("filename"), "filesize": f.get("filesize")}
                 for p in sub.get("plugins") or [] for fa in p.get("fileareas") or [] for f in fa.get("files") or []]
        return {"assignid": int(assignid), "status": sub.get("status"), "modified": fmt_time(sub.get("timemodified")),
                "graded_status": last.get("gradingstatus"), "can_edit": last.get("canedit"),
                "locked": last.get("locked"), "files": files,
                "grade": ((d.get("feedback") or {}).get("grade") or {}).get("grade")}

    def upcoming_deadlines(self, days: float = 14, include_overdue: bool = False) -> list[dict]:
        now = time.time()
        rows = []
        for a in self.assignments():
            due = a["due_ts"]
            if due and (now <= due <= now + days * 86400 or (include_overdue and now - 30 * 86400 <= due < now)):
                left = int(due - now)
                rows.append({"due": a["due"], "due_ts": due, "course": a["course"], "name": a["name"],
                             "assignid": a["assignid"],
                             "in": f"{left // 86400}d {left % 86400 // 3600}h" if left >= 0 else "OVERDUE"})
        return sorted(rows, key=lambda r: r["due_ts"])

    def download_file(self, fileurl: str, dest_dir: str = "") -> dict:
        u, b = urlparse(fileurl), urlparse(base_url())
        if u.scheme not in ("http", "https") or u.netloc.lower() != b.netloc.lower():
            raise ISpaceError(f"Refusing to download: URL host must be {b.netloc}")
        q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k.lower() != "token"]
        url = urlunparse(u._replace(query=urlencode(q + [("token", self.token())])))
        dest = Path(dest_dir).expanduser() if dest_dir else Path.home() / "Downloads" / "ispace"
        dest.mkdir(parents=True, exist_ok=True)
        name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", unquote(Path(u.path).name)).strip(" .") or "download"
        target, i = dest / name, 1
        while target.exists():  # never overwrite
            target = dest / f"{Path(name).stem} ({i}){Path(name).suffix}"
            i += 1
        try:
            with self.http.stream("GET", url) as r:
                if r.status_code != 200 or "json" in r.headers.get("content-type", ""):  # Moodle errors come as JSON
                    raise ISpaceError(f"Download refused by the server (HTTP {r.status_code}).")
                with open(target, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
        except httpx.HTTPError as e:
            target.unlink(missing_ok=True)
            raise ISpaceError(f"Download failed ({type(e).__name__}).") from None
        return {"path": str(target), "bytes": target.stat().st_size}

    def upload_and_save_submission(self, assignid: int, file_path: str) -> dict:
        p = Path(file_path).expanduser()
        try:
            with open(p, "rb") as fh:
                d = self.http.post(f"{base_url()}/webservice/upload.php", files={"file_1": (p.name, fh)},
                                   data={"token": self.token(), "filearea": "draft", "itemid": "0"}).json()
            itemid = d[0]["itemid"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            raise ISpaceError("Upload failed.") from None
        warn = self.call("mod_assign_save_submission", assignmentid=int(assignid),
                         plugindata={"files_filemanager": itemid})
        if warn:
            raise ISpaceError(f"save_submission returned warnings: {json.dumps(warn)[:300]}")
        return {"saved": True, "assignid": int(assignid), "file": p.name,
                "note": "Saved as a draft; not yet submitted for grading."}

    def submit_for_grading(self, assignid: int) -> dict:
        warn = self.call("mod_assign_submit_for_grading", assignmentid=int(assignid), acceptsubmissionstatement=1)
        if warn:
            raise ISpaceError(f"submit_for_grading returned warnings: {json.dumps(warn)[:300]}")
        return {"submitted": True, "assignid": int(assignid)}
