"""``set_book_rating`` at the tool boundary.

``tests/test_writes.py`` covers what clearing writes at the ``CalibreDB`` seam.
This covers what a caller is allowed to ask for, because the tool's field
constraint decides whether ``stars=0`` reaches that seam at all.
"""

import asyncio
import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from calibre_mcp_server.calibre_api import Book, CalibreDB


def _call_tool(server, name, args):
    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool(name, args)

    return asyncio.run(run())


def _payload(result):
    return json.loads(result.content[0].text)


def test_zero_stars_clears_an_existing_rating(library, monkeypatch):
    book_id = library.add_book("A Book")
    library.set_rating(book_id, 4)
    monkeypatch.setenv("CALIBRE_LIBRARY_PATH", str(library.path))

    import calibre_mcp_server.server as server

    monkeypatch.setattr(server, "calibre_db", CalibreDB(str(library.path)))

    result = _call_tool(
        server, "set_book_rating", {"book_id": book_id, "stars": 0}
    )

    assert _payload(result) == {"book_id": book_id, "rating": None}


def test_boolean_stars_are_rejected_and_change_nothing(library, monkeypatch):
    """``false`` must not read as ``0``: that would clear a rating by accident."""
    book_id = library.add_book("A Book")
    library.set_rating(book_id, 4)
    monkeypatch.setenv("CALIBRE_LIBRARY_PATH", str(library.path))

    import calibre_mcp_server.server as server

    monkeypatch.setattr(server, "calibre_db", CalibreDB(str(library.path)))

    with pytest.raises(ToolError):
        _call_tool(
            server, "set_book_rating", {"book_id": book_id, "stars": False}
        )

    assert Book(book_id, str(library.path)).rating == 4


def test_boundary_sets_one_to_five_and_refuses_the_rest(library, monkeypatch):
    """The field constraint is the artefact that changed, so pin its range."""
    book_id = library.add_book("A Book")
    monkeypatch.setenv("CALIBRE_LIBRARY_PATH", str(library.path))

    import calibre_mcp_server.server as server

    monkeypatch.setattr(server, "calibre_db", CalibreDB(str(library.path)))

    for stars in range(1, 6):
        result = _call_tool(
            server, "set_book_rating", {"book_id": book_id, "stars": stars}
        )
        assert _payload(result) == {"book_id": book_id, "rating": stars}

    for refused in (6, -1, 2.5, "4", None):
        with pytest.raises(ToolError):
            _call_tool(
                server,
                "set_book_rating",
                {"book_id": book_id, "stars": refused},
            )
