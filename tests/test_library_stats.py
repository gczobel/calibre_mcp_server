"""``get_library_stats``: the counts it reports, and the keys they hide behind.

The tool's debug line read ``stats['total_books']``, a key ``get_database_info``
has never returned, so it logged "Library contains 0 books" while returning
the real count microseconds later.
"""

import asyncio
import json

from fastmcp import Client

from calibre_mcp_server.calibre_api import CalibreDB


def test_book_count_is_reported_under_books_count(library):
    """The name the tool's log line reads; a rename here breaks it silently."""
    for i in range(3):
        library.add_book(f"Book {i}")

    info = CalibreDB(str(library.path)).get_database_info()

    assert info["books_count"] == 3


def test_every_count_the_result_advertises_is_present(library):
    library.add_book("A Book")

    info = CalibreDB(str(library.path)).get_database_info()

    for key in (
        "books_count",
        "authors_count",
        "series_count",
        "publishers_count",
        "tags_count",
        "languages_count",
    ):
        assert key in info, key


def test_the_debug_line_reports_the_count_the_result_carries(
    library, bound_server
):
    """The bug itself: the log line must not contradict the result."""
    for i in range(3):
        library.add_book(f"Book {i}")

    seen = []

    async def handler(message):
        seen.append(message)

    async def run():
        async with Client(bound_server.mcp, message_handler=handler) as client:
            return await client.call_tool("get_library_stats", {})

    result = asyncio.run(run())

    logged = " ".join(json.dumps(str(getattr(m, "root", m))) for m in seen)
    assert "contains 3 books" in logged, logged
    assert json.loads(result.content[0].text)["books_count"] == 3

