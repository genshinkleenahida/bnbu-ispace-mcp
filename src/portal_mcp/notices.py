"""New-notice reminders: a small local last-seen file (no secrets) so each notice is reported once, and `watch`."""
import json
import os
import subprocess
import sys
import time

from .client import ISpace, ISpaceError, config_dir, save_private
from .textinfo import announcements, course_text, notifications

FIRST_RUN_DAYS, KEEP_DAYS = 7, 120
_TOAST = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]"
          "|Out-Null;$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(1);"
          "$n=$t.GetElementsByTagName('text');$n.Item(0).AppendChild($t.CreateTextNode($env:T))|Out-Null;"
          "$n.Item(1).AppendChild($t.CreateTextNode($env:B))|Out-Null;[Windows.UI.Notifications."
          "ToastNotificationManager]::CreateToastNotifier('portal-mcp').Show([Windows.UI.Notifications.ToastNotification]::new($t))")


def _path():
    return config_dir() / "notice_state.json"


def _load():
    try:
        return json.loads(_path().read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _save(st: dict, now: float) -> None:
    for k in ("seen", "due"):
        st[k] = {a: b for a, b in st.get(k, {}).items() if b > now - KEEP_DAYS * 86400}
    save_private(_path(), st)


def collect(c: ISpace) -> list[dict]:
    """Everything currently visible, each with a stable key. Edited labels/pages count as new again."""
    items = [(f"post:{p['discussion']}:{p['id']}", "announcement", p) for p in announcements(c, max_chars=300)]
    items += [(f"{i['kind']}:{i['id']}:{i['ts']}", i["kind"], i) for i in course_text(c, max_chars=300)
              if i["kind"] in ("label", "page") and i["ts"]]
    for kind, tag in (("notifications", "notification"), ("conversations", "message")):
        try:
            items += [(f"{tag}:{n['id']}", tag, n) for n in notifications(c, 50, kind, 300)]
        except ISpaceError:
            pass
    return [{"key": k, "source": s, "course": x.get("course"), "title": x.get("title") or x.get("name"),
             "date": x["date"], "ts": x["ts"], "text": x["text"]} for k, s, x in items]


def new_notices(c: ISpace, mark_seen: bool = True, now: float = 0) -> dict:
    """Notices not shown before. The first run returns only the last 7 days and sets the baseline."""
    now = now or time.time()
    st = _load()
    first, st = st is None, st or {}
    seen, items = st.setdefault("seen", {}), collect(c)
    fresh = [i for i in items if i["key"] not in seen and (not first or i["ts"] >= now - FIRST_RUN_DAYS * 86400)]
    if mark_seen:
        for i in items:
            seen.setdefault(i["key"], now)
        _save(st, now)
    return {"first_run": first, "notices": sorted(fresh, key=lambda x: x["ts"], reverse=True)}


def mark_notices_seen(c: ISpace) -> dict:
    new_notices(c)  # marks everything currently visible as seen
    return {"ok": True}


def due_soon(c: ISpace, hours: float, now: float = 0) -> list[dict]:
    """Assignments due within `hours` that were not reminded about yet."""
    now = now or time.time()
    st = _load() or {}
    done, out = st.setdefault("due", {}), []
    for r in c.upcoming_deadlines(hours / 24 + 1):
        key = f"{r['assignid']}:{r['due_ts']}"
        if r["due_ts"] - now <= hours * 3600 and key not in done:
            done[key] = now
            out.append(r)
    if out:
        _save(st, now)
    return out


def notify(title: str, body: str) -> bool:
    """Desktop notification: PowerShell toast (Windows), osascript (macOS), notify-send (Linux). False if unavailable."""
    env = None
    if sys.platform == "win32":
        cmd, env = ["powershell", "-NoProfile", "-Command", _TOAST], {**os.environ, "T": title, "B": body}
    elif sys.platform == "darwin":
        cmd = ["osascript", "-e", "on run argv", "-e", "display notification (item 2 of argv) with title (item 1 of argv)",
               "-e", "end run", title, body]
    else:
        cmd = ["notify-send", "--", title, body]
    try:
        return subprocess.run(cmd, env=env, capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def watch(c: ISpace, interval: float = 30.0, deadlines: float = 0.0, once: bool = False,
          out=print, sleep=time.sleep, push=notify) -> list[str]:
    """Poll every `interval` minutes: print new notices (and assignments due within `deadlines` hours) and
    show a desktop notification. --once polls a single time."""
    while True:
        lines, heads = [], []
        try:
            for n in new_notices(c)["notices"]:
                lines.append(f"{n['date']} {n['source']} [{n['course'] or ''}]: {n['title']}")
                heads.append(n["title"])
            for r in due_soon(c, deadlines) if deadlines else []:
                lines.append(f"DUE {r['due']} ({r['in']}): {r['course']} / {r['name']}")
                heads.append("Due soon: " + r["name"])
        except ISpaceError as e:
            out(f"error: {e}")
        for ln in lines:
            out(ln)
        if lines:
            push("iSpace", f"{len(lines)} new: " + "; ".join(heads[:3]))
        if once:
            return lines
        sleep(max(interval, 1) * 60)
