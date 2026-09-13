"""``set_book_rating`` at the tool boundary.

``tests/test_writes.py`` covers what clearing writes at the ``CalibreDB`` seam.
This covers what a caller is allowed to ask for, because the tool's field
constraint decides whether ``stars=0`` reaches that seam at all.
"""

import pytest
from fastmcp.exceptions import ToolError

from calibre_mcp_server.calibre_api import Book


def test_zero_stars_clears_an_existing_rating(library, call_tool, parse_payload):
    book_id = library.add_book("A Book")
    library.set_rating(book_id, 4)

    result = call_tool("set_book_rating", {"book_id": book_id, "stars": 0})

    assert parse_payload(result) == {"book_id": book_id, "rating": None}


def test_boolean_stars_are_rejected_and_change_nothing(library, call_tool):
    """``false`` must not read as ``0``: that would clear a rating by accident."""
    book_id = library.add_book("A Book")
    library.set_rating(book_id, 4)

    with pytest.raises(ToolError):
        call_tool("set_book_rating", {"book_id": book_id, "stars": False})

    assert Book(book_id, str(library.path)).rating == 4


def test_boundary_sets_one_to_five_and_refuses_the_rest(
    library, call_tool, parse_payload
):
    """The field constraint is the artefact that changed, so pin its range."""
    book_id = library.add_book("A Book")

    for stars in range(1, 6):
        result = call_tool(
            "set_book_rating", {"book_id": book_id, "stars": stars}
        )
        assert parse_payload(result) == {"book_id": book_id, "rating": stars}

    for refused in (6, -1, 2.5, "4", None):
        with pytest.raises(ToolError):
            call_tool(
                "set_book_rating", {"book_id": book_id, "stars": refused}
            )
