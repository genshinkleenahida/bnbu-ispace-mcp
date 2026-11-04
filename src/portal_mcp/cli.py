"""portal-mcp: with no command it runs the MCP server; every tool is also a command that prints JSON
(e.g. `portal-mcp search-text --keywords exam`). Credentials: ISPACE_USERNAME/ISPACE_PASSWORD, else the OS keychain (`portal-mcp login`)."""
import argparse
import getpass
import inspect
import json
import sys

from . import notices, tools
from .client import KEYRING_SERVICE, ISpaceError


def watch(interval: float = 30.0, deadlines: float = 0.0, once: bool = False) -> None:
    """Poll every `interval` minutes for new notices, print them and show a desktop notification; --deadlines HOURS also reminds of due assignments."""
    notices.watch(tools.client(), interval, deadlines, once)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("portal-mcp", description=__doc__)
    sub = p.add_subparsers(dest="cmd")
    for name, text in (("serve", "run the MCP server (default)"), ("login", "save your iSpace username and password to the OS keychain"),
                       ("logout", "remove them from the OS keychain")):
        sub.add_parser(name, help=text)
    for fn in tools.READ + tools.WRITE + [watch]:
        sp = sub.add_parser(fn.__name__.replace("_", "-"), help=fn.__doc__.split("\n")[0])
        sp.set_defaults(fn=fn)
        for name, prm in inspect.signature(fn).parameters.items():
            kind, d = (int if "int" in str(prm.annotation) else str), prm.default
            flag = "--" + name.replace("_", "-")
            if d is inspect.Parameter.empty:
                sp.add_argument(name, type=kind)
            elif isinstance(d, bool):
                sp.add_argument("--no-" + flag[2:] if d else flag, dest=name, action="store_false" if d else "store_true")
            elif "list" in str(prm.annotation):
                sp.add_argument(flag, nargs="*", type=kind)
            else:
                sp.add_argument(flag, type=type(d), default=d)
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd in (None, "serve"):
            from .server import run
            run()
        elif args.cmd in ("login", "logout"):
            import keyring
            try:
                if args.cmd == "login":
                    user, pw = input("iSpace username: ").strip(), getpass.getpass("iSpace password (hidden): ")
                    keyring.set_password(KEYRING_SERVICE, "username", user)
                    keyring.set_password(KEYRING_SERVICE, "password", pw)
                    print(f"Saved to the OS keychain. Hello, {tools.site_info()['fullname']}.")
                else:
                    for k in ("username", "password"):
                        try:
                            keyring.delete_password(KEYRING_SERVICE, k)
                        except keyring.errors.PasswordDeleteError:
                            pass
            except keyring.errors.KeyringError as e:
                raise ISpaceError(f"No usable OS keychain ({type(e).__name__}); set ISPACE_USERNAME and ISPACE_PASSWORD instead.")
        else:
            res = args.fn(**{k: v for k, v in vars(args).items() if k not in ("cmd", "fn")})
            if res is not None:
                print(json.dumps(res, ensure_ascii=False, indent=2))
    except ISpaceError as e:
        sys.exit(f"error: {e}")
    except (EOFError, KeyboardInterrupt):
        sys.exit(130)


if __name__ == "__main__":
    main()
