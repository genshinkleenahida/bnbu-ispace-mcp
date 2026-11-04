"""BNBU single sign-on, then MIS (timetable, grades, teaching evaluation list) and the OA portal (leave)."""
import html
import os
import re
from html.parser import HTMLParser
from urllib.parse import quote, urljoin

import httpx

from . import sm2
from .client import ISpaceError, get_credentials

# SSO application id, then the display-name prefix used when the id is not in the list
APPS = {"mis": ("3bvkl8pks1ki04nirus0g", "mis_2006"), "oa": ("na3j8azrv30vamqac8yg", "portal")}
LEAVE_ID = "57"  # used if "Leave Application" is not in the service list


def _text(s) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", str(s or "")))).strip()


class _Tables(HTMLParser):
    """Every <table> as a list of rows; a row is a list of cell texts (<br> becomes a newline)."""

    def __init__(self, page):
        super().__init__(convert_charrefs=True)
        self.tables, self._stack, self._row, self._cell = [], [], None, None
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._stack.append([])
        elif tag == "tr" and self._stack:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            lines = (re.sub(r"[ \t\r\u3000\xa0]+", " ", x).strip() for x in "".join(self._cell).split("\n"))
            self._row.append((tag, "\n".join(x for x in lines if x)))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._stack:
            self._stack[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._stack:
            self.tables.append(self._stack.pop())

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _options(page: str, select_pattern: str) -> list[dict]:
    sel = re.search(select_pattern, page, re.S)
    return [{"id": i, "name": _text(n), "selected": "selected" in a}
            for i, a, n in re.findall(r'<option\s+value="([^"]*)"([^>]*)>([^<]*)</option>', sel.group(0) if sel else "")]


class Portal:
    def __init__(self) -> None:
        self.http = httpx.Client(timeout=60, follow_redirects=True, transport=httpx.HTTPTransport(retries=2))
        env = os.environ.get
        self.url = {"sso": env("ISPACE_SSO_URL", "https://sso.bnbu.edu.cn").rstrip("/"),
                    "mis": env("ISPACE_MIS_URL", "https://mis.bnbu.edu.cn").rstrip("/"),
                    "oa": env("ISPACE_OA_URL", "https://portal.bnbu.edu.cn").rstrip("/")}
        self.signed_in, self.ready = False, set()

    # ---- single sign-on (the password is SM2-encrypted exactly like the web form does) ----
    def _sso_login(self) -> None:
        user, pw = get_credentials()
        try:
            key = self.http.get(f"{self.url['sso']}/auth/flow/login/getSm2PubK").json()["data"]
            j = self.http.post(f"{self.url['sso']}/auth/pwd/tencent/login",
                               json={"userName": user, "password": sm2.encrypt(key, pw.encode())}).json()
        except (httpx.HTTPError, ValueError, KeyError) as e:
            raise ISpaceError(f"Could not reach BNBU single sign-on ({type(e).__name__}).") from None
        d = j.get("data") or {}
        if not d.get("success"):
            raise ISpaceError("BNBU single sign-on failed: " + (_text(d.get("message") or j.get("message")) or "refused"))
        if d.get("needVerifyCode"):
            raise ISpaceError("BNBU single sign-on wants a verification code. Sign in once in a browser, then retry.")
        self.signed_in = True

    def _launch(self, app: str) -> None:
        """Open the application through SSO so it sets its own session cookie."""
        key, prefix = APPS[app]
        sso = self.url["sso"]
        try:
            apps = self.http.get(f"{sso}/auth/account/app/list", headers={"Accept": "application/json"}).json()["data"]
        except (httpx.HTTPError, ValueError, KeyError) as e:
            raise ISpaceError(f"Could not read the SSO application list ({type(e).__name__}).") from None
        chosen = next((a for a in apps if a.get("url") == key), None) or next(
            (a for a in apps if str(a.get("displayName", "")).lower().startswith(prefix)), None)
        if not chosen:
            raise ISpaceError(f"This account cannot open {app.upper()} through single sign-on.")
        acct = (chosen.get("accountNameList") or [get_credentials()[0]])[0]
        if isinstance(acct, dict):
            acct = acct.get("name") or acct.get("accountName")
        url = f"{sso}/auth/sso/login/{chosen['url']}?accountName={quote(str(acct), safe='')}"
        for _ in range(12):  # follow the page's JavaScript redirects
            r = self.http.get(url)
            m = re.search(r"""onload=["']\s*redirect\(\s*'([^']+)'""", r.text) if r.status_code < 400 else None
            if r.status_code >= 400:
                raise ISpaceError(f"Single sign-on could not open {app.upper()} (HTTP {r.status_code}).")
            if not m:
                return
            url = urljoin(str(r.url), m.group(1))
        raise ISpaceError("Single sign-on redirected too many times.")

    def _ensure(self, app: str) -> None:
        if app not in self.ready:
            if not self.signed_in:
                self._sso_login()
            self._launch(app)
            self.ready.add(app)

    @staticmethod
    def _expired(app: str, r: httpx.Response) -> bool:
        if app == "mis":
            return r.status_code == 403 or "login_error" in str(r.url) or "Timeout, please" in r.text[:2000]
        try:
            j = r.json()
            return isinstance(j, dict) and j.get("errorCode") == "002"
        except ValueError:
            return False

    def _send(self, app: str, path: str, **kw) -> httpx.Response:
        """GET (or POST when data= is given) with one automatic re-login if the session has expired."""
        for retry in (True, False):
            self._ensure(app)
            try:
                r = self.http.request("POST" if "data" in kw else "GET", self.url[app] + path, **kw)
            except httpx.HTTPError as e:
                raise ISpaceError(f"{app.upper()} request failed ({type(e).__name__}).") from None
            if self._expired(app, r) and retry:
                self.signed_in = False
                self.ready.clear()
                continue
            if self._expired(app, r) or r.status_code >= 400:
                raise ISpaceError(f"{app.upper()} refused the request (HTTP {r.status_code}); the page may not be "
                                  "available for this account.")
            return r

    def mis_get(self, path: str, params=None) -> str:
        return self._send("mis", path, params=params).text

    def mis_post(self, path: str, params, data) -> None:
        self._send("mis", path, params=params, data=data)

    # ---- MIS ----
    def mis_timetable(self, semester_id: str = "") -> dict:
        page = self.mis_get("/mis/student/tts/timetable.do", {"semesterId": semester_id} if semester_id else None)
        semesters = _options(page, r'<select id="semesterList".*?</select>')
        courses = []
        for rows in _Tables(page).tables:
            hdr = next((r for r in rows if any(c[1] == "Course Code" for c in r)), None)
            for r in rows if hdr else []:
                if r is not hdr and len(r) == len(hdr):
                    row = dict(zip((c[1] for c in hdr), (c[1] for c in r)))
                    lines = lambda k: [x for x in row.get(k, "").split("\n") if x]
                    courses.append({"category": row.get("Course Category", ""), "code": row.get("Course Code", ""),
                                    "name": row.get("Name", ""), "teachers": row.get("Teachers", ""),
                                    "times": lines("Time"), "rooms": lines("Room"), "units": row.get("Units", ""),
                                    "remark": row.get("Remark", "")})
        return {"semester": next((s["name"] for s in semesters if s["selected"]), None),
                "semesters": semesters, "courses": courses}

    def mis_grades(self, academic_year_id: str = "") -> dict:
        page = self._send("mis", "/mis/student/ssm/gradepublish/webReport.do", **(
            {"data": {"id": academic_year_id, "button": "Go"}} if academic_year_id else {})).text
        years = _options(page, r'<select name="id" id="id">.*?</select>')
        semesters, cur = [], None
        for rows in _Tables(page).tables:
            for r in rows:
                cells = [c[1] for c in r]
                joined = " ".join(cells)
                if len(cells) == 1 and re.match(r"(Semester \d+ of [\d-]+|Summer[^\n]*)$", joined):
                    cur = {"semester": joined, "courses": [], "semester_gpa": None, "cumulative_gpa": None}
                    semesters.append(cur)
                elif cur and len(cells) == 8 and re.fullmatch(r"[A-Z]{2,5}", cells[0]):
                    cur["courses"].append({"code": cells[0] + cells[1], "title": cells[2], "units_attempted": cells[3],
                                           "units_gained": cells[4], "grade": cells[5], "grade_point": cells[6],
                                           "remarks": cells[7].strip()})
                elif cur:
                    for key, label in (("semester_gpa", "Semester"), ("cumulative_gpa", "Cumulative")):
                        m = re.search(label + r" Grade Point Average = ([\d.]+)", joined)
                        cur[key] = m.group(1) if m else cur[key]
        return {"academic_year": next((y["name"] for y in years if y["selected"]), None),
                "academic_years": years, "semesters": semesters}

    def mis_evaluations(self) -> list[dict]:
        """Course sections of every listed Teaching & Learning Evaluation. Empty when none is open."""
        out = []
        for sid, title in re.findall(r'<td id="([0-9a-f]{32})">(.*?)</td>', self.mis_get("/mis/student/te/home.do"), re.S):
            page = self.mis_get("/mis/student/te/section.do", {"evaluationId": sid})
            secs = [r for t in _Tables(page).tables for r in t if len(r) == 4 and r[0][0] == "th" and r[0][1].isdigit()]
            for r, (attrs, _) in zip(secs, re.findall(r"<button([^>]*)>([^<]*)</button>", page)):
                q = re.search(r"sectionId=([0-9a-f]{32})", attrs)
                out.append({"survey": _text(title), "course": r[1][1], "instructor": r[2][1],
                            "status": "pending" if q else "evaluated", "section_id": q.group(1) if q else None})
        return out

    # ---- OA portal (Weaver e-cology JSON) ----
    def _oa(self, path: str, data=None, params=None):
        try:
            j = self._send("oa", path, **({"data": data} if data is not None else {"params": params})).json()
        except ValueError:
            raise ISpaceError("Portal returned an unexpected response.") from None
        if isinstance(j, dict) and j.get("status") is False and j.get("msg"):
            raise ISpaceError("Portal: " + _text(j["msg"]))
        return j

    def oa_services(self) -> list[dict]:
        j = self._oa("/api/workflow/createreq/wfinfo", params={"offical": "0"})
        return [{"category": _text(t.get("typeName")), "id": w.get("id"), "name": _text(w.get("name"))}
                for t in j.get("datas", []) for w in t.get("wfbeans", [])]

    def _leave_id(self) -> str:
        return str(next((s["id"] for s in self.oa_services() if s["name"] == "Leave Application"), LEAVE_ID))

    def leave_list(self, limit: int = 20) -> list[dict]:
        limit = max(1, min(int(limit), 100))
        key = self._oa("/api/workflow/reqlist/splitPageKey", data={
            "viewScope": "mine", "actiontype": "splitpage", "pageSize": str(limit), "offical": "0", "menuIds": "-1",
            "workflowid": self._leave_id()}).get("sessionkey")
        if not key:
            raise ISpaceError("Portal did not return a list key.")
        j = self._oa("/api/ec/dev/table/datas", data={"dataKey": key, "current": "1", "pageSize": str(limit)})
        return [{"request_id": str(d.get("requestid")), "title": _text(d.get("requestnamespan") or d.get("requestname")),
                 "created": _text(d.get("createdate")), "current_node": _text(d.get("currentnodeidspan")),
                 "status": _text(d.get("statusspan") or d.get("status"))} for d in j.get("datas", [])]

    @staticmethod
    def _fields(j: dict) -> dict:
        return ((j.get("tableInfo") or {}).get("main") or {}).get("fieldinfomap") or {}

    def leave_detail(self, request_id: str) -> dict:
        rid = re.sub(r"\D", "", str(request_id))
        if not rid:
            raise ISpaceError("request_id must be a number from leave_list.")
        j = self._oa("/api/workflow/reqform/loadForm", data={"requestid": rid, "iscreate": "0"})
        infos, fields = self._fields(j), {}
        for k, cell in (j.get("maindata") or {}).items():
            info = infos.get(k.replace("field", ""), {})
            label, sp, val = _text(info.get("fieldlabel")), cell.get("specialobj"), cell.get("value")
            if not label or info.get("viewattr") == 0:
                continue
            if isinstance(sp, dict):  # attachments
                val = [f.get("filename") for f in sp.get("filedatas", []) if f.get("filename")]
            elif isinstance(sp, list) and sp:
                val = ", ".join(_text(x.get("name")) for x in sp)
            else:  # drop-down: show the choice's name
                names = {str(i.get("selectvalue")): i.get("selectname")
                         for i in (info.get("selectattr") or {}).get("selectitemlist") or []}
                val = _text(names.get(str(val), val))
            if val not in ("", [], None):
                fields[label] = val
        p = j.get("params") or {}
        return {"request_id": rid, "title": _text(p.get("requestname")), "current_node": _text(p.get("nodename")),
                "fields": fields}

    def leave_form(self) -> dict:
        """The fields of a blank Leave Application form. Nothing is created."""
        wf = self._leave_id()
        j = self._oa("/api/workflow/reqform/loadForm", data={"requestid": "-1", "workflowid": wf, "iscreate": "1"})
        out = []
        for info in self._fields(j).values():
            if _text(info.get("fieldlabel")) and info.get("fieldname") and info.get("viewattr") in (2, 3):
                row = {"label": _text(info["fieldlabel"]), "required": info["viewattr"] == 3}
                items = (info.get("selectattr") or {}).get("selectitemlist")
                if items:
                    row["options"] = [_text(i.get("selectname")) for i in items if not i.get("cancel")]
                out.append(row)
        return {"workflow_id": wf, "fields": sorted(out, key=lambda r: (not r["required"], r["label"]))}
