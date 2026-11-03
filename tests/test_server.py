import asyncio

import pytest

from ispace_mcp.server import build

READ = {"site_info", "list_courses", "course_contents", "list_assignments", "submission_status",
        "upcoming_deadlines", "download_file"}
WRITE = {"upload_and_save_submission", "submit_for_grading"}


def names():
    return {t.name for t in asyncio.run(build().list_tools())}


def test_write_tools_hidden_by_default(mock_site):
    assert names() == READ


def test_write_tools_with_flag(mock_site, monkeypatch):
    monkeypatch.setenv("ISPACE_ALLOW_WRITE", "1")
    assert names() == READ | WRITE


def test_tool_call_end_to_end(mock_site):
    res = asyncio.run(build().call_tool("list_courses", {}))
    assert "Course One" in str(res)
