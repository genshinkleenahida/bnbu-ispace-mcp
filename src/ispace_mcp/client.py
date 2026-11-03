"""Thin Moodle web-service client. Never exposes the token or password."""
from __future__ import annotations

import json
import os
import re
import stat
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse, urlencode, parse_qsl, urlunparse

import httpx

DEFAULT_TZ = "Asia/Shanghai"  # BNBU is UTC+8 year-round


def tz_name() -> str:
    return os.environ.get("ISPACE_TZ") or DEFAULT_TZ


def _tz():
    """Configured timezone (ISPACE_TZ, default Asia/Shanghai); falls back to fixed UTC+8 if unknown."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz_name())
    except Exception:
        from datetime import timezone

        return timezone(timedelta(hours=8), "UTC+08:00")


KEYRING_SERVICE = "ispace-mcp"
DEFAULT_URL = "https://ispace.bnbu.edu.cn"
SERVICE = "moodle_mobile_app"
_TOKEN_RE = re.compile(r"([?&;]token=)[^&\s\"'<>]+", re.I)


class ISpaceError(Exception):
    """Clean, token-free error."""


def base_url() -> str:
    return os.environ.get("ISPACE_URL", DEFAULT_URL).rstrip("/")


def config_dir() -> Path:
    """Per-OS config dir: ~/.config/ispace-mcp (Linux), ~/Library/Application Support/ispace-mcp (macOS),
    %LOCALAPPDATA%\\ispace-mcp (Windows). Override with ISPACE_CONFIG_DIR."""
    p = os.environ.get("ISPACE_CONFIG_DIR")
    if p:
        return Path(p).expanduser()
    from platformdirs import user_config_dir

    return Path(user_config_dir("ispace-mcp", appauthor=False))


def token_file() -> Path:
    p = os.environ.get("ISPACE_TOKEN_FILE")
    return Path(p).expanduser() if p else config_dir() / "token"


def credentials_file() -> Path:
    return config_dir() / "credentials.json"


def write_allowed() -> bool:
    return os.environ.get("ISPACE_ALLOW_WRITE") == "1"


# ---------- credentials ----------
def env_token() -> str | None:
    """Optional pre-generated web service token (ISPACE_TOKEN); used as-is, never cached or refetched."""
    return os.environ.get("ISPACE_TOKEN") or None


def _read_cred_file() -> tuple[str | None, str | None]:
    try:
        d = json.loads(credentials_file().read_text("utf-8"))
        return d.get("username"), d.get("password")
    except Exception:
        return None, None


def _write_private(path: Path, payload: dict) -> None:
    """Write JSON atomically with mode 0600 (POSIX). On Windows the file inherits your profile ACLs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    os.replace(tmp, path)


def keyring_available() -> bool:
    """True if a usable OS keyring backend exists (False on headless Linux without Secret Service, etc.)."""
    try:
        import keyring
        from keyring.backends import fail

        kr = keyring.get_keyring()
        return not isinstance(kr, fail.Keyring) and getattr(kr, "priority", 1) > 0
    except Exception:
        return False


def get_credentials() -> tuple[str, str]:
    """Order: env vars -> OS keyring -> opt-in 0600 credentials file. Never fails on a missing keyring."""
    u, p = os.environ.get("ISPACE_USERNAME"), os.environ.get("ISPACE_PASSWORD")
    if u and p:
        return u, p
    try:
        import keyring

        u = u or keyring.get_password(KEYRING_SERVICE, "username")
        p = p or keyring.get_password(KEYRING_SERVICE, "password")
    except Exception:  # no backend, locked keyring, D-Bus missing, ...
        pass
    if not (u and p):
        fu, fp = _read_cred_file()
        u, p = u or fu, p or fp
    if not (u and p):
        raise ISpaceError(
            "No credentials. Set ISPACE_USERNAME/ISPACE_PASSWORD (or ISPACE_TOKEN), or run `ispace-mcp login` "
            "to store them in the OS keychain (or `ispace-mcp login --file` where no keychain exists)."
        )
    return u, p


def store_credentials(username: str, password: str, use_file: bool = False) -> str:
    """Store credentials; returns where ('keyring' or 'file'). Without a keyring, raises unless use_file."""
    if not use_file:
        try:
            import keyring

            keyring.set_password(KEYRING_SERVICE, "username", username)
            keyring.set_password(KEYRING_SERVICE, "password", password)
            clear_token_cache()
            return "keyring"
        except Exception as e:
            raise ISpaceError(
                f"No usable OS keychain here ({type(e).__name__}). Options: set ISPACE_USERNAME/ISPACE_PASSWORD "
                "in the environment, or re-run `ispace-mcp login --file` to store them in a 0600 file "
                f"({credentials_file()})."
            ) from None
    _write_private(credentials_file(), {"username": username, "password": password})
    clear_token_cache()
    return "file"


def delete_credentials() -> None:
    try:
        import keyring

        for k in ("username", "password"):
            try:
                keyring.delete_password(KEYRING_SERVICE, k)
            except Exception:
                pass
    except Exception:
        pass
    try:
        credentials_file().unlink()
    except FileNotFoundError:
        pass
    clear_token_cache()


# ---------- token cache ----------
def clear_token_cache() -> None:
    try:
        token_file().unlink()
    except FileNotFoundError:
        pass


def _read_cached(username: str) -> str | None:
    try:
        d = json.loads(token_file().read_text("utf-8"))
        if d.get("username") == username and d.get("url") == base_url() and d.get("token"):
            return d["token"]
    except Exception:
        pass
    return None


def _write_cached(username: str, token: str) -> None:
    _write_private(token_file(), {"username": username, "url": base_url(), "token": token})


# ---------- redaction ----------
def redact_str(s: str, token: str | None = None) -> str:
    s = _TOKEN_RE.sub(r"\1REDACTED", s)
    if token:
        s = s.replace(token, "REDACTED")
    return s


def redact(obj: Any, token: str | None = None) -> Any:
    if isinstance(obj, str):
        return redact_str(obj, token)
    if isinstance(obj, list):
        return [redact(x, token) for x in obj]
    if isinstance(obj, dict):
        return {k: redact(v, token) for k, v in obj.items()}
    return obj


def fmt_time(ts: int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), _tz()).strftime("%Y-%m-%d %H:%M (%a) ") + (tz_name() if hasattr(_tz(), "key") else "UTC+08:00")


# ---------- client ----------
class ISpace:
    def __init__(self) -> None:
        self.http = httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0), follow_redirects=True,
                                 headers={"User-Agent": "ispace-mcp/0.1 (+https://github.com/genshinkleenahida/bnbu-ispace-mcp)"})
        self._token: str | None = None
        self._user: str | None = None

    # -- token --
    def _fetch_token(self) -> str:
        user, pw = get_credentials()
        try:
            r = self.http.post(f"{base_url()}/login/token.php",
                               data={"username": user, "password": pw, "service": SERVICE})
            d = r.json()
        except httpx.HTTPError as e:
            raise ISpaceError(f"Network error requesting token: {type(e).__name__}") from None
        except ValueError:
            raise ISpaceError(f"Unexpected non-JSON response from the token endpoint (HTTP {r.status_code}). "
                              f"Check that {base_url()} is the right site.") from None
        if not isinstance(d, dict) or "token" not in d:
            msg = (d.get("error") or d.get("message") or "unknown error") if isinstance(d, dict) else "unknown error"
            code = d.get("errorcode", "") if isinstance(d, dict) else ""
            raise ISpaceError(_hint(f"Login failed: {redact_str(str(msg), pw)}" + (f" [{code}]" if code else ""),
                                    code, str(msg)))
        _write_cached(user, d["token"])
        self._user = user
        return d["token"]

    def token(self) -> str:
        if self._token:
            return self._token
        if env_token():
            self._token = env_token()
            return self._token  # type: ignore[return-value]
        user, _ = get_credentials()
        self._user = user
        self._token = _read_cached(user) or self._fetch_token()
        return self._token

    def _renew(self) -> str:
        if env_token():
            raise ISpaceError("ISPACE_TOKEN was rejected by the server (invalidtoken). Generate a new token.")
        clear_token_cache()
        self._token = None
        return self.token()

    def _safe(self, e: Exception) -> ISpaceError:
        return ISpaceError(f"Network error: {type(e).__name__}")

    # -- REST --
    def call(self, fn: str, **params: Any) -> Any:
        data = _flatten(params)
        for attempt in (0, 1):
            tok = self.token()
            try:
                r = self.http.post(f"{base_url()}/webservice/rest/server.php",
                                   data={**data, "wstoken": tok, "wsfunction": fn, "moodlewsrestformat": "json"})
                d = r.json()
            except httpx.HTTPError as e:
                raise self._safe(e) from None
            except ValueError:
                raise ISpaceError(f"{fn}: non-JSON response (HTTP {r.status_code})") from None
            if isinstance(d, dict) and d.get("exception"):
                if d.get("errorcode") == "invalidtoken" and attempt == 0:
                    self._renew()
                    continue
                msg = redact_str(str(d.get("message", d["exception"])), tok)
                code = str(d.get("errorcode", ""))
                raise ISpaceError(_hint(f"{fn}: {msg} [{code}]", code, msg))
            return redact(d, tok)
        raise ISpaceError(f"{fn}: failed")  # pragma: no cover

    # -- high level --
    def site_info(self) -> dict:
        d = self.call("core_webservice_get_site_info")
        return {k: d.get(k) for k in ("sitename", "username", "fullname", "userid", "release", "lang",
                                       "siteurl", "usercanmanageownfiles")} | {
            "functions": sorted(f["name"] for f in d.get("functions", []))}

    def userid(self) -> int:
        return int(self.call("core_webservice_get_site_info")["userid"])

    def courses(self) -> list[dict]:
        out = []
        for c in self.call("core_enrol_get_users_courses", userid=self.userid()):
            out.append({"id": c["id"], "shortname": c.get("shortname"), "fullname": c.get("fullname"),
                        "progress": c.get("progress"), "completed": c.get("completed"),
                        "start": fmt_time(c.get("startdate")), "end": fmt_time(c.get("enddate")),
                        "last_access": fmt_time(c.get("lastaccess"))})
        return out

    def course_contents(self, courseid: int) -> list[dict]:
        out = []
        for s in self.call("core_course_get_contents", courseid=int(courseid)):
            mods = []
            for m in s.get("modules", []):
                mods.append({
                    "id": m.get("id"), "instance": m.get("instance"), "name": m.get("name"),
                    "modname": m.get("modname"), "url": m.get("url"), "visible": m.get("visible"),
                    "description": m.get("description"),
                    "files": [{"filename": f.get("filename"), "filesize": f.get("filesize"),
                               "mimetype": f.get("mimetype"), "modified": fmt_time(f.get("timemodified")),
                               "fileurl": f.get("fileurl")}
                              for f in m.get("contents", []) if f.get("type") == "file"],
                })
            out.append({"id": s.get("id"), "name": s.get("name"), "summary": s.get("summary"), "modules": mods})
        return out

    def assignments(self, courseids: list[int] | None = None) -> list[dict]:
        if not courseids:
            courseids = [c["id"] for c in self.courses()]
        d = self.call("mod_assign_get_assignments", courseids=[int(x) for x in courseids])
        out = []
        for c in d.get("courses", []):
            for a in c.get("assignments", []):
                out.append({
                    "assignid": a["id"], "cmid": a.get("cmid"), "course_id": c["id"],
                    "course": c.get("fullname"), "name": a.get("name"),
                    "due": fmt_time(a.get("duedate")), "due_ts": a.get("duedate") or 0,
                    "cutoff": fmt_time(a.get("cutoffdate")), "allow_submissions_from": fmt_time(a.get("allowsubmissionsfromdate")),
                    "grade_max": a.get("grade"), "intro": a.get("intro"),
                    "attachments": [{"filename": f.get("filename"), "filesize": f.get("filesize"),
                                     "fileurl": f.get("fileurl")} for f in a.get("introattachments", [])],
                })
        return out

    def submission_status(self, assignid: int) -> dict:
        d = self.call("mod_assign_get_submission_status", assignid=int(assignid))
        ls = d.get("lastattempt", {}) or {}
        sub = ls.get("submission", {}) or {}
        files = []
        for p in sub.get("plugins", []) or []:
            for fa in p.get("fileareas", []) or []:
                for f in fa.get("files", []) or []:
                    files.append({"filename": f.get("filename"), "filesize": f.get("filesize"),
                                  "fileurl": f.get("fileurl")})
        fb = d.get("feedback", {}) or {}
        return {
            "assignid": int(assignid),
            "status": sub.get("status"), "attempt": sub.get("attemptnumber"),
            "modified": fmt_time(sub.get("timemodified")),
            "graded_status": ls.get("gradingstatus"),
            "can_edit": ls.get("canedit"), "can_submit": ls.get("cansubmit"), "locked": ls.get("locked"),
            "submission_statement_required": ls.get("submissionstatementrequired") if "submissionstatementrequired" in ls else None,
            "files": files,
            "grade": (fb.get("grade") or {}).get("grade") if fb else None,
            "feedback_raw_keys": sorted(fb.keys()) if fb else [],
        }

    def upcoming_deadlines(self, days: int = 14, include_overdue: bool = False) -> list[dict]:
        now = int(time.time())
        end = now + int(days) * 86400
        rows = []
        for a in self.assignments():
            due = a["due_ts"]
            if not due:
                continue
            if (include_overdue and due < now and due >= now - 30 * 86400) or now <= due <= end:
                left = due - now
                rows.append({"due": a["due"], "due_ts": due,
                             "in": (f"{left // 86400}d {left % 86400 // 3600}h" if left >= 0 else "OVERDUE"),
                             "course": a["course"], "name": a["name"], "assignid": a["assignid"]})
        rows.sort(key=lambda r: r["due_ts"])
        return rows

    # -- files --
    def _authorized_url(self, fileurl: str) -> str:
        u = urlparse(fileurl)
        b = urlparse(base_url())
        if u.scheme not in ("http", "https") or u.netloc.lower() != b.netloc.lower():
            raise ISpaceError(f"Refusing to download: URL host must be {b.netloc}")
        q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k.lower() != "token"]
        q.append(("token", self.token()))
        return urlunparse(u._replace(query=urlencode(q)))

    def download_file(self, fileurl: str, dest_dir: str | None = None) -> dict:
        dest = Path(dest_dir).expanduser() if dest_dir else Path.home() / "Downloads" / "ispace"
        dest.mkdir(parents=True, exist_ok=True)
        name = unquote(Path(urlparse(fileurl).path).name) or "download"
        name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .") or "download"
        target = dest / name
        if target.exists():  # don't overwrite silently
            stem, suf, i = target.stem, target.suffix, 1
            while target.exists():
                target = dest / f"{stem} ({i}){suf}"
                i += 1
        tok = self.token()
        part = target.with_name(target.name + ".part")
        try:
            with self.http.stream("GET", self._authorized_url(fileurl)) as r:
                if r.status_code != 200:
                    raise ISpaceError(f"Download failed: HTTP {r.status_code}")
                ctype = r.headers.get("content-type", "")
                size = 0
                with open(part, "wb") as fh:
                    for chunk in r.iter_bytes(65536):
                        fh.write(chunk)
                        size += len(chunk)
            if "json" in ctype and size < 4096:
                body = part.read_text("utf-8", "replace")
                if "invalidtoken" in body or '"exception"' in body:
                    raise ISpaceError("Download refused by server (token/permission problem): "
                                      + redact_str(body[:200], tok))
            os.replace(part, target)
        except httpx.HTTPError as e:
            raise self._safe(e) from None
        finally:
            if part.exists():
                part.unlink()
        return {"path": str(target), "bytes": size}

    # -- writes (gated; callers must check gate) --
    def upload_and_save_submission(self, assignid: int, file_path: str) -> dict:
        p = Path(file_path).expanduser()
        tok = self.token()
        try:
            with open(p, "rb") as fh:
                r = self.http.post(f"{base_url()}/webservice/upload.php",
                                   data={"token": tok, "filearea": "draft", "itemid": "0"},
                                   files={"file_1": (p.name, fh)})
            d = r.json()
        except httpx.HTTPError as e:
            raise self._safe(e) from None
        except ValueError:
            raise ISpaceError(f"upload.php: non-JSON response (HTTP {r.status_code})") from None
        if isinstance(d, dict) and (d.get("error") or d.get("exception")):
            raise ISpaceError("Upload failed: " + redact_str(str(d.get("error") or d.get("message")), tok))
        if not isinstance(d, list) or not d or "itemid" not in d[0]:
            raise ISpaceError("Upload failed: unexpected response from upload.php")
        itemid = d[0]["itemid"]
        res = self.call("mod_assign_save_submission", assignmentid=int(assignid),
                        **{"plugindata": {"files_filemanager": itemid}})
        warnings = res if isinstance(res, list) else []
        if warnings:
            raise ISpaceError(f"save_submission returned warnings: {json.dumps(warnings)[:500]}")
        return {"saved": True, "assignid": int(assignid), "file": p.name, "draft_itemid": itemid,
                "note": "Saved as draft; NOT yet submitted for grading (if the assignment requires a button press)."}

    def submit_for_grading(self, assignid: int) -> dict:
        res = self.call("mod_assign_submit_for_grading", assignmentid=int(assignid), acceptsubmissionstatement=1)
        warnings = res if isinstance(res, list) else []
        if warnings:
            raise ISpaceError(f"submit_for_grading returned warnings: {json.dumps(warnings)[:500]}")
        return {"submitted": True, "assignid": int(assignid)}


def _hint(text: str, code: str, msg: str = "") -> str:
    """Append a plain-language hint for common Moodle failure modes."""
    low = f"{code} {msg}".lower()
    if code in ("servicenotavailable", "webservicesnotenabled", "enablewsdescription") or \
            "web service" in low and "not" in low and "enabled" in low:
        return text + (" -- Web services or the mobile service appear to be disabled on this site; "
                       "ask the site admin to enable them.")
    if code == "accessexception" and "service" in low:
        return text + " -- The site does not allow this web service function for your account."
    if code in ("invalidlogin", "invalidtoken") or "invalid login" in low:
        return text + " -- Check your iSpace username/password (or token)."
    return text


def _flatten(params: dict, prefix: str = "") -> dict[str, str]:
    """Moodle array encoding: name[0]=..., name[key]=..."""
    out: dict[str, str] = {}
    for k, v in params.items():
        key = f"{prefix}[{k}]" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        elif isinstance(v, (list, tuple)):
            out.update(_flatten({str(i): x for i, x in enumerate(v)}, key))
        elif isinstance(v, bool):
            out[key] = "1" if v else "0"
        else:
            out[key] = str(v)
    return out
