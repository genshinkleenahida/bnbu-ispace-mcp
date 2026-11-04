"""Every tool, written once: the MCP server registers these functions and the CLI turns them into commands.
Write tools exist only with ISPACE_ALLOW_WRITE=1 and do nothing until called with confirm=true."""
from pathlib import Path

from . import evaluation, notices, textinfo
from .client import ISpace, ISpaceError, write_allowed
from .portal import Portal

_client = _portal = None


def client() -> ISpace:
    global _client
    _client = _client or ISpace()
    return _client


def portal() -> Portal:
    global _portal
    _portal = _portal or Portal()
    return _portal


# ---- iSpace ----
def site_info() -> dict:
    """Site info, the logged-in user, and the web-service functions the token may call."""
    return client().site_info()


def list_courses() -> list[dict]:
    """Enrolled iSpace courses."""
    return client().courses()


def course_contents(courseid: int) -> list[dict]:
    """Sections, activities and files of a course (file URLs go to download_file)."""
    return client().course_contents(courseid)


def list_assignments(courseids: list[int] | None = None) -> list[dict]:
    """Assignments with due dates (UTC+8); all enrolled courses by default."""
    return client().assignments(courseids)


def submission_status(assignid: int) -> dict:
    """Submission and grading status of one assignment."""
    return client().submission_status(assignid)


def upcoming_deadlines(days: int = 14, include_overdue: bool = False) -> list[dict]:
    """Assignments due within `days` days, soonest first."""
    return client().upcoming_deadlines(days, include_overdue)


def download_file(fileurl: str, dest_dir: str = "") -> dict:
    """Download an iSpace file URL (iSpace host only) to dest_dir (default ~/Downloads/ispace)."""
    return client().download_file(fileurl, dest_dir)


def announcements(courseids: list[int] | None = None, per_forum: int = 20, max_chars: int = 2000) -> list[dict]:
    """Announcements and forum posts as plain text, newest first (max_chars per post, 0 = no limit)."""
    return textinfo.announcements(client(), courseids, per_forum, max_chars)


def course_text(courseids: list[int] | None = None, max_chars: int = 2000) -> list[dict]:
    """Text on course pages: section summaries, labels, pages, activity descriptions (exam time/scope often live here)."""
    return textinfo.course_text(client(), courseids, max_chars)


def notifications(limit: int = 20, kind: str = "notifications") -> list[dict]:
    """iSpace notifications (kind='notifications') or direct messages (kind='conversations'). Marks nothing as read."""
    return textinfo.notifications(client(), limit, kind)


def search_text(keywords: list[str] | None = None, courseids: list[int] | None = None, messages: bool = True) -> list[dict]:
    """Search announcements, course text and messages; no keywords = exam-related words (English and Chinese)."""
    return textinfo.search_text(client(), keywords, courseids, messages)


def new_notices(mark_seen: bool = True) -> dict:
    """Notices not shown before (first run: last 7 days). mark_seen keeps them from showing again."""
    return notices.new_notices(client(), mark_seen)


def mark_notices_seen() -> dict:
    """Treat all current notices as seen."""
    return notices.mark_notices_seen(client())


# ---- MIS and portal ----
def mis_timetable(semester_id: str = "") -> dict:
    """MIS class timetable (current semester unless a semester id is given)."""
    return portal().mis_timetable(semester_id)


def mis_grades(academic_year_id: str = "") -> dict:
    """MIS grades and GPA (current academic year unless an id is given)."""
    return portal().mis_grades(academic_year_id)


def mis_evaluations() -> list[dict]:
    """Teaching & Learning Evaluation sections and their status. An empty list means none is listed right now."""
    return portal().mis_evaluations()


def oa_services() -> list[dict]:
    """Applications in the BNBU portal Services Center."""
    return portal().oa_services()


def leave_list(limit: int = 20) -> list[dict]:
    """Your Leave Application requests, newest first."""
    return portal().leave_list(limit)


def leave_detail(request_id: str) -> dict:
    """One of your leave requests (id from leave_list)."""
    return portal().leave_detail(request_id)


def leave_form() -> dict:
    """Fields of a blank leave form (read-only; leave requests are never submitted)."""
    return portal().leave_form()


# ---- write tools ----
def _need_write() -> None:
    if not write_allowed():
        raise ISpaceError("Write operations are disabled; set ISPACE_ALLOW_WRITE=1 to enable them.")


def upload_and_save_submission(assignid: int, file_path: str, confirm: bool = False) -> dict:
    """WRITE: save a local file as the submission draft. Dry-run unless confirm=true; get the user's explicit OK first."""
    _need_write()
    p = Path(file_path).expanduser()
    if not p.is_file():
        raise ISpaceError(f"File not found: {p}")
    if not confirm:
        return {"dry_run": True, "would_do": f"Upload {p.name} as the draft for assignment {assignid}.",
                "status": client().submission_status(assignid)}
    return client().upload_and_save_submission(assignid, str(p))


def submit_for_grading(assignid: int, confirm: bool = False) -> dict:
    """WRITE: finalize an assignment (usually irreversible). Dry-run unless confirm=true; get the user's explicit OK first."""
    _need_write()
    if not confirm:
        return {"dry_run": True, "would_do": f"Submit assignment {assignid} for grading.",
                "status": client().submission_status(assignid)}
    return client().submit_for_grading(assignid)


def _evaluate(course: str | None, comment: str, confirm: bool) -> dict:
    _need_write()
    secs = portal().mis_evaluations()
    if course:
        secs = [s for s in secs if course == s["section_id"] or course.lower() in f"{s['course']} {s['instructor']}".lower()]
        if not secs:
            raise ISpaceError(f"No evaluation matches '{course}'. See mis_evaluations.")
    pending = [s for s in secs if s["status"] == "pending"]
    if course and len(pending) != 1:
        raise ISpaceError("Already evaluated (it cannot be refilled)." if not pending else
                          "More than one match: " + "; ".join(f"{s['course']} ({s['instructor']})" for s in pending))
    plans = [(s, evaluation.build_plan(evaluation.parse_form(portal().mis_get(
        "/mis/student/te/question.do", {"sectionId": s["section_id"]})), comment)) for s in pending]
    if not confirm:
        return {"dry_run": True, "would_do": "Submit these answers. MIS cannot refill an evaluation. Nothing was sent; "
                "get the user's explicit OK, then call again with confirm=true.",
                "plans": [{"course": s["course"], "instructor": s["instructor"], **{
                    k: p[k] for k in ("answers", "comment", "problems")}} for s, p in plans]}
    results = []
    for s, p in plans:
        if not p["problems"]:
            portal().mis_post("/mis/student/te/submit.do", {"sectionId": s["section_id"]}, p["payload"])
        results.append({"course": s["course"], "submitted": not p["problems"], "problems": p["problems"]})
    return {"dry_run": False, "results": results,
            "still_pending": sum(s["status"] == "pending" for s in portal().mis_evaluations())}


def mis_evaluate(course: str, comment: str = "", confirm: bool = False) -> dict:
    """WRITE: fill in the MIS evaluation of ONE course (name, instructor or section id) with the highest option for every
    rating question. Dry-run unless confirm=true; show the dry-run to the user and get their explicit OK first."""
    return _evaluate(course, comment, confirm)


def mis_evaluate_all(comment: str = "", confirm: bool = False) -> dict:
    """WRITE: like mis_evaluate for ALL pending evaluations. Dry-run unless confirm=true."""
    return _evaluate(None, comment, confirm)


READ = [site_info, list_courses, course_contents, list_assignments, submission_status, upcoming_deadlines,
        download_file, announcements, course_text, notifications, search_text, new_notices, mark_notices_seen,
        mis_timetable, mis_grades, mis_evaluations, oa_services, leave_list, leave_detail, leave_form]
WRITE = [upload_and_save_submission, submit_for_grading, mis_evaluate, mis_evaluate_all]
