"""Operations shared by the MCP server and the CLI (including write gating)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .client import ISpace, ISpaceError, write_allowed

_client: ISpace | None = None


def client() -> ISpace:
    global _client
    if _client is None:
        _client = ISpace()
    return _client


def _strip(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "due_ts"} for r in rows]


def site_info() -> dict:
    return client().site_info()


def list_courses() -> list[dict]:
    return client().courses()


def course_contents(courseid: int) -> list[dict]:
    return client().course_contents(courseid)


def list_assignments(courseids: list[int] | None = None) -> list[dict]:
    return _strip(client().assignments(courseids))


def submission_status(assignid: int) -> dict:
    return client().submission_status(assignid)


def upcoming_deadlines(days: int = 14, include_overdue: bool = False) -> list[dict]:
    return _strip(client().upcoming_deadlines(days, include_overdue))


def download_file(fileurl: str, dest_dir: str | None = None) -> dict:
    return client().download_file(fileurl, dest_dir)


def _require_write() -> None:
    if not write_allowed():
        raise ISpaceError("Write operations are disabled. The user must set ISPACE_ALLOW_WRITE=1 in the "
                          "environment of this server/CLI to enable them.")


def upload_and_save_submission(assignid: int, file_path: str, confirm: bool = False) -> dict[str, Any]:
    _require_write()
    p = Path(file_path).expanduser()
    if not p.is_file():
        raise ISpaceError(f"File not found: {p}")
    if not confirm:
        info: dict[str, Any] = {"dry_run": True, "would_do": (
            f"Upload '{p.name}' ({p.stat().st_size} bytes) to Moodle draft area and save it as the submission "
            f"for assignment {int(assignid)} (replacing the current draft file set). Nothing was changed. "
            "Get the user's explicit OK for this specific file and assignment, then call again with confirm=true.")}
        try:
            info["current_status"] = client().submission_status(assignid)
        except ISpaceError as e:
            info["current_status_error"] = str(e)
        return info
    return client().upload_and_save_submission(assignid, str(p))


def submit_for_grading(assignid: int, confirm: bool = False) -> dict[str, Any]:
    _require_write()
    if not confirm:
        info: dict[str, Any] = {"dry_run": True, "would_do": (
            f"Finalize assignment {int(assignid)} by submitting it for grading (accepting the submission "
            "statement). This is usually irreversible for the student. Nothing was changed. Get the user's "
            "explicit OK for this specific assignment, then call again with confirm=true.")}
        try:
            info["current_status"] = client().submission_status(assignid)
        except ISpaceError as e:
            info["current_status_error"] = str(e)
        return info
    return client().submit_for_grading(assignid)
