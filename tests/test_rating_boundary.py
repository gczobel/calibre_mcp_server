"""``set_book_rating`` at the tool boundary.

``tests/test_writes.py`` covers what clearing writes at the ``CalibreDB`` seam.
This covers what a caller is allowed to ask for, because the tool's field
constraint decides whether ``stars=0`` reaches that seam at all.
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
