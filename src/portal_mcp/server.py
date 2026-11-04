"""FastMCP stdio server. Write tools are registered only when ISPACE_ALLOW_WRITE=1."""
from mcp.server.fastmcp import FastMCP

from . import tools
from .client import write_allowed


def build() -> FastMCP:
    mcp = FastMCP("ispace")
    for fn in tools.READ + (tools.WRITE if write_allowed() else []):
        mcp.tool()(fn)
    return mcp


def run() -> None:
    build().run(transport="stdio")
