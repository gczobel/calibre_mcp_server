"""Tool-boundary test: env var set before import, in-memory client.

This is the one test that imports the server module, because that import has
the side effect of reading ``CALIBRE_LIBRARY_PATH`` and initializing the
database. It verifies the new tools are listed and that a failing write
arrives as a tool error.
"""

import asyncio

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

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
