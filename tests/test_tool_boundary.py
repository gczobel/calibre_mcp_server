"""Tool-boundary tests: env var set before import, in-memory client.

These tests import the server module, because that import has the side effect of
reading ``CALIBRE_LIBRARY_PATH`` and initializing the database. The module is
cached process-wide, so whichever test imports it first fixes the library path
for the whole session; every boundary test therefore rebinds ``calibre_db`` to
its own fixture library instead of depending on import order.
"""

import asyncio

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from calibre_mcp_server.calibre_api import CalibreDB

EXPECTED_TOOLS = {
    "mark_book_read",
    "mark_book_unread",
    "set_book_rating",
    "find_books",
}


def test_tools_listed_and_failure_arrives_as_tool_error(library, monkeypatch):
    book_id = library.add_book("A Book")  # no read column in this library
    monkeypatch.setenv("CALIBRE_LIBRARY_PATH", str(library.path))

    # Env var must be set before the first import of the server module.
    import calibre_mcp_server.server as server

    monkeypatch.setattr(server, "calibre_db", CalibreDB(str(library.path)))

    async def run():
        async with Client(server.mcp) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools}
            assert EXPECTED_TOOLS <= names

            # A read-only tool still works.
            stats = await client.call_tool("get_library_stats", {})
            assert stats is not None

            # A write against a library with no read column is a tool error.
            with pytest.raises(ToolError, match="read"):
                await client.call_tool(
                    "mark_book_read", {"book_id": book_id}
                )

    asyncio.run(run())
