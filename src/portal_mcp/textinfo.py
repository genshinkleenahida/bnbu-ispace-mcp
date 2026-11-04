"""Plain-text information on iSpace: announcements, course page text, notifications, keyword search. Read-only."""
import re

from .client import ISpace, ISpaceError, fmt_time, html_to_text

# Default search: exam times / scope, in English and Chinese.
EXAM = (r"\bexam|\bmid-?terms?\b|\bfinals?\b|\bquiz|\btests?\b|\bassessment|"
        r"考试|考場|考场|期中|期末|测验|測驗|小测|开卷|闭卷|考核|补考|重考")


def _names(c: ISpace, courseids) -> dict:
    names = {x["id"]: x["fullname"] for x in c.courses()}
    return {int(i): names.get(int(i), str(i)) for i in courseids} if courseids else names


def announcements(c: ISpace, courseids=None, per_forum: int = 20, max_chars: int = 2000) -> list[dict]:
    """Forum posts (announcements included) of the courses, newest first, as plain text."""
    names, posts = _names(c, courseids), []
    for f in c.call("mod_forum_get_forums_by_courses", courseids=list(names)):
        try:
            for d in c.call("mod_forum_get_forum_discussions", forumid=f["id"], perpage=per_forum)["discussions"]:
                raw = (c.call("mod_forum_get_discussion_posts", discussionid=d["discussion"])["posts"] if d.get("numreplies")
                       else [{"id": d["id"], "subject": d["name"], "message": d["message"], "timecreated": d["created"],
                              "author": {"fullname": d.get("userfullname")}}])
                for p in raw:
                    ts = p.get("timecreated") or 0
                    posts.append({"id": p["id"], "discussion": d["discussion"], "course": names.get(f["course"]),
                                  "forum": f.get("name"), "title": html_to_text(p.get("subject")),
                                  "author": (p.get("author") or {}).get("fullname"), "date": fmt_time(ts), "ts": ts,
                                  "text": html_to_text(p.get("message"))[:max_chars or None]})
        except ISpaceError:
            continue  # a forum this account cannot read
    return sorted(posts, key=lambda x: x["ts"], reverse=True)


def course_text(c: ISpace, courseids=None, max_chars: int = 2000) -> list[dict]:
    """Text on course pages: section summaries, labels, pages and activity descriptions."""
    names, items = _names(c, courseids), []

    def add(cid, kind, name, raw, ts=0, ref=None):
        text = html_to_text(raw)
        if text:
            items.append({"id": ref, "course": names.get(int(cid)), "kind": kind, "name": html_to_text(name),
                          "date": fmt_time(ts), "ts": ts or 0, "text": text[:max_chars or None]})

    for cid in names:
        try:
            for s in c.call("core_course_get_contents", courseid=cid):
                add(cid, "section", s.get("name"), s.get("summary"), ref=s["id"])
                for m in s.get("modules", []):
                    if m.get("modname") not in ("label", "page"):  # those are read in full below
                        add(cid, m["modname"], m["name"], m.get("description"), ref=m["id"])
        except ISpaceError:
            pass
    for fn, key, kind in (("mod_label_get_labels_by_courses", "labels", "label"),
                          ("mod_page_get_pages_by_courses", "pages", "page")):
        try:
            for x in c.call(fn, courseids=list(names)).get(key, []):
                if x.get("visible", 1):
                    add(x["course"], kind, x["name"], (x.get("intro") or "") + "\n" + (x.get("content") or ""),
                        x.get("timemodified"), x["id"])
        except ISpaceError:
            pass
    return items


def notifications(c: ISpace, limit: int = 20, kind: str = "notifications", max_chars: int = 2000) -> list[dict]:
    """Notifications (kind='notifications') or direct messages (kind='conversations'), newest first.
    Nothing is marked as read."""
    out = []
    for read in (0, 1):
        for m in c.call("core_message_get_messages", useridto=c.userid(), useridfrom=0, type=kind, read=read,
                        newestfirst=1, limitnum=limit)["messages"]:
            ts = m.get("timecreated") or 0
            out.append({"id": m["id"], "title": html_to_text(m.get("subject")), "from": m.get("userfromfullname"),
                        "date": fmt_time(ts), "ts": ts, "read": bool(read),
                        "text": html_to_text(m.get("fullmessagehtml") or m.get("fullmessage"))[:max_chars or None]})
    return sorted(out, key=lambda x: x["ts"], reverse=True)[:limit]


def search_text(c: ISpace, keywords=None, courseids=None, messages: bool = True) -> list[dict]:
    """Search announcements, course text and (optionally) notifications/messages. No keywords = exam words."""
    pat = re.compile("|".join(map(re.escape, keywords)) if keywords else EXAM, re.I)
    rows = [("announcement", x["title"], x) for x in announcements(c, courseids, max_chars=0)]
    rows += [(x["kind"], x["name"], x) for x in course_text(c, courseids, max_chars=0)]
    for kind, label in (("notifications", "notification"), ("conversations", "message")):
        rows += [(label, x["title"], x) for x in notifications(c, 50, kind, 0)] if messages else []
    out = []
    for source, title, x in rows:
        flat, hits, end = re.sub(r"\s+", " ", title + "\n" + x["text"]), [], 0
        for m in pat.finditer(flat):
            if m.start() >= end and len(hits) < 3:
                end = m.end() + 90
                hits.append(flat[max(0, m.start() - 90):end])
        if hits:
            out.append({"source": source, "course": x.get("course"), "title": title, "date": x["date"], "ts": x["ts"],
                        "snippets": hits})
    return sorted(out, key=lambda x: x["ts"], reverse=True)
