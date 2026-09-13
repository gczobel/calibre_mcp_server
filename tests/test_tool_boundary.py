"""Tool-boundary tests: the tool list, and a failing write as a tool error.

These tests drive the server module through an in-memory MCP client. That import
reads ``CALIBRE_LIBRARY_PATH``, and the module is cached process-wide, so
``bound_server`` in ``conftest`` owns the rule for binding it to a fixture
library — this module does not repeat it.

Listing the tools needs a session of its own: ``call_tool`` opens a fresh one per
call, and ``list_tools`` is not a tool call. The two tool calls below do not share
a session.
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


def test_tools_listed_and_failure_arrives_as_tool_error(
    library, bound_server, call_tool
):
    book_id = library.add_book("A Book")  # no read column in this library

    async def list_names():
        async with Client(bound_server.mcp) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    assert EXPECTED_TOOLS <= asyncio.run(list_names())

    # A read-only tool still works.
    assert call_tool("get_library_stats") is not None

    # A write against a library with no read column is a tool error.
    with pytest.raises(ToolError, match="read"):
        call_tool("mark_book_read", {"book_id": book_id})
