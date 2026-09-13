"""``find_books`` at the tool boundary: what a caller actually receives.

The query layer returns a plain list, and ``tests/test_find_books.py`` covers it
there. This module covers the layer above it, because that is where the defect
in issue #19 lives: a zero-match query rendered an empty ``content`` array, so a
caller could not tell "nothing matched" from "the call failed".
"""

import asyncio
import json

from fastmcp import Client

from calibre_mcp_server.calibre_api import CalibreDB


def _call_tool(server, name, args):
    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool(name, args)

    return asyncio.run(run())


def _bind(server, library, monkeypatch):
    """Point the server at this test's fixture library.

    ``config`` validates at import time, so the caller sets the environment
    variable first; the module-level ``calibre_db`` is then replaced outright,
    which is what makes this test independent of import order.
    """
    monkeypatch.setattr(server, "calibre_db", CalibreDB(str(library.path)))


def test_zero_matches_still_returns_visible_content(library, monkeypatch):
    monkeypatch.setenv("CALIBRE_LIBRARY_PATH", str(library.path))

    # The env var must be set before the first import of the server module.
    import calibre_mcp_server.server as server

    _bind(server, library, monkeypatch)

    result = _call_tool(server, "find_books", {"author": "Nobody At All"})

    assert result.content, "a zero-match result must still render content"
    payload = json.loads(result.content[0].text)
    assert payload == {"count": 0, "books": []}


def test_matches_are_reported_with_a_count(library, monkeypatch):
    book_id = library.add_book("A Book")
    library.link_author(book_id, library.add_author("Jane Doe"))
    library.link_series(book_id, library.add_series("Series One"))

    monkeypatch.setenv("CALIBRE_LIBRARY_PATH", str(library.path))

    import calibre_mcp_server.server as server

    _bind(server, library, monkeypatch)

    result = _call_tool(server, "find_books", {})

    # Same book the CalibreDB seam returns in test_find_books; wrapping it must
    # not change the entries, only report them alongside a count.
    assert json.loads(result.content[0].text) == {
        "count": 1,
        "books": [{
            "id": book_id,
            "title": "A Book",
            "author": "Jane Doe",
            "series": "Series One",
            "rating": None,
            "read": None,
        }],
    }
