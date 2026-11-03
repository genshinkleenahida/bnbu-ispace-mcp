"""FastMCP stdio server. Write tools are registered only when ISPACE_ALLOW_WRITE=1."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import ops
from .client import ISpaceError, write_allowed

WRITE_WARNING = (
    "WRITE ACTION. Before calling with confirm=true you MUST have the user's explicit OK for this specific "
    "file and assignment (named in the conversation). Without confirm=true it only returns a dry-run. "
    "Never write or answer homework on the user's behalf."
)


def _wrap(fn):
    """Turn ISpaceError into a clean tool error (message already token-free)."""
    import functools

    @functools.wraps(fn)
    def inner(*a, **k):
        try:
            return fn(*a, **k)
        except ISpaceError as e:
            raise ValueError(str(e)) from None
    return inner


def build() -> FastMCP:
    mcp = FastMCP("ispace")

    @mcp.tool()
    @_wrap
    def site_info() -> dict:
        """Moodle site info and the logged-in user (name, userid, available web-service functions)."""
        return ops.site_info()

    @mcp.tool()
    @_wrap
    def list_courses() -> list[dict]:
        """List the user's enrolled iSpace courses (id, name, progress)."""
        return ops.list_courses()

    @mcp.tool()
    @_wrap
    def course_contents(courseid: int) -> list[dict]:
        """Sections, activities and files of a course. File URLs are token-redacted; pass them to download_file."""
        return ops.course_contents(courseid)

    @mcp.tool()
    @_wrap
    def list_assignments(courseids: list[int] | None = None) -> list[dict]:
        """List assignments (due dates in the configured timezone, default Asia/Shanghai). Omit courseids to cover all enrolled courses."""
        return ops.list_assignments(courseids)

    @mcp.tool()
    @_wrap
    def submission_status(assignid: int) -> dict:
        """Submission/grading status of one assignment (use the assignid from list_assignments)."""
        return ops.submission_status(assignid)

    @mcp.tool()
    @_wrap
    def upcoming_deadlines(days: int = 14) -> list[dict]:
        """Assignments due within the next `days` days, soonest first, times in the configured timezone."""
        return ops.upcoming_deadlines(days)

    @mcp.tool()
    @_wrap
    def download_file(fileurl: str, dest_dir: str = "") -> dict:
        """Download an iSpace file (fileurl from course_contents / list_assignments) to dest_dir
        (default ~/Downloads/ispace). Returns the saved path. Only iSpace URLs are allowed."""
        return ops.download_file(fileurl, dest_dir or None)

    if write_allowed():
        @mcp.tool(description=(
            "Upload a local file to iSpace and save it as the submission draft for an assignment. "
            "Does NOT finalize (see submit_for_grading). " + WRITE_WARNING))
        @_wrap
        def upload_and_save_submission(assignid: int, file_path: str, confirm: bool = False) -> dict:
            return ops.upload_and_save_submission(assignid, file_path, confirm)

        @mcp.tool(description=(
            "Submit an assignment for grading (finalize; usually irreversible). " + WRITE_WARNING))
        @_wrap
        def submit_for_grading(assignid: int, confirm: bool = False) -> dict:
            return ops.submit_for_grading(assignid, confirm)

    return mcp


def run() -> None:
    build().run(transport="stdio")
