"""ispace-mcp CLI: `serve` (default MCP stdio server), `login`, and JSON-printing subcommands."""
from __future__ import annotations

import argparse
import getpass
import json
import sys

from . import __version__, ops
from .client import ISpaceError, credentials_file, delete_credentials, store_credentials, token_file


def _print(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ispace-mcp",
        description="BNBU iSpace (Moodle) MCP server and CLI. Credentials: env ISPACE_USERNAME/ISPACE_PASSWORD, "
                    "ISPACE_TOKEN, or OS keychain (`ispace-mcp login`). Output is JSON. Write commands need ISPACE_ALLOW_WRITE=1.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")
    sub.add_parser("serve", help="run the MCP server over stdio (default when no command is given)")
    lg = sub.add_parser("login", help="prompt for username/password and store them in the OS keychain")
    lg.add_argument("--show-password", action="store_true", help="echo the password while typing (default: hidden)")
    lg.add_argument("--file", action="store_true", dest="use_file",
                    help="store in a 0600 credentials file instead of the keychain (for systems without a keychain)")
    sub.add_parser("logout", help="remove stored credentials and cached token")
    sub.add_parser("whoami", help="alias of site-info").set_defaults(fn=lambda a: ops.site_info())
    sub.add_parser("site-info", help="site and user info").set_defaults(fn=lambda a: ops.site_info())
    sub.add_parser("courses", help="list enrolled courses").set_defaults(fn=lambda a: ops.list_courses())
    c = sub.add_parser("contents", help="course sections, activities, files")
    c.add_argument("courseid", type=int)
    c.set_defaults(fn=lambda a: ops.course_contents(a.courseid))
    c = sub.add_parser("assignments", help="list assignments (all enrolled courses by default)")
    c.add_argument("courseids", type=int, nargs="*")
    c.set_defaults(fn=lambda a: ops.list_assignments(a.courseids or None))
    c = sub.add_parser("status", help="submission status of an assignment")
    c.add_argument("assignid", type=int)
    c.set_defaults(fn=lambda a: ops.submission_status(a.assignid))
    c = sub.add_parser("deadlines", help="upcoming deadlines, soonest first (ISPACE_TZ, default Asia/Shanghai)")
    c.add_argument("--days", type=int, default=14)
    c.add_argument("--include-overdue", action="store_true", help="also show items overdue within 30 days")
    c.set_defaults(fn=lambda a: ops.upcoming_deadlines(a.days, a.include_overdue))
    c = sub.add_parser("download", help="download an iSpace file URL (iSpace host only)")
    c.add_argument("fileurl")
    c.add_argument("--dest", default=None, help="destination directory (default ~/Downloads/ispace)")
    c.set_defaults(fn=lambda a: ops.download_file(a.fileurl, a.dest))
    c = sub.add_parser("upload", help="[WRITE] upload a file as the submission draft (dry-run unless --confirm)")
    c.add_argument("assignid", type=int)
    c.add_argument("file")
    c.add_argument("--confirm", action="store_true", help="really do it (only with the user's explicit OK)")
    c.set_defaults(fn=lambda a: ops.upload_and_save_submission(a.assignid, a.file, a.confirm))
    c = sub.add_parser("submit", help="[WRITE] submit for grading (dry-run unless --confirm)")
    c.add_argument("assignid", type=int)
    c.add_argument("--confirm", action="store_true", help="really do it (only with the user's explicit OK)")
    c.set_defaults(fn=lambda a: ops.submit_for_grading(a.assignid, a.confirm))
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    cmd = args.cmd or "serve"
    try:
        if cmd == "serve":
            from .server import run
            run()
        elif cmd == "login":
            user = input("iSpace username: ").strip()
            pw = input("iSpace password: ") if args.show_password else getpass.getpass("iSpace password (hidden): ")
            if not user or not pw:
                raise ISpaceError("Username and password are required.")
            where = store_credentials(user, pw, args.use_file)
            sys.stderr.write(f"Stored in {'OS keychain' if where == 'keyring' else credentials_file()}. Verifying...\n")
            try:
                _print({"ok": True, "user": ops.site_info().get("fullname")})
            except ISpaceError:
                sys.stderr.write("Credentials were saved but login failed; run `ispace-mcp login` again to fix them.\n")
                raise
        elif cmd == "logout":
            delete_credentials()
            _print({"ok": True, "token_file_removed": str(token_file())})
        else:
            _print(args.fn(args))
    except ISpaceError as e:
        sys.stderr.write(f"error: {e}\n")
        sys.exit(1)
    except EOFError:
        sys.stderr.write("error: no input available (is stdin closed?)\n")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
