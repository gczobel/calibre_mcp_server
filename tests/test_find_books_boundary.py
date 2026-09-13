"""``find_books`` at the tool boundary: what a caller actually receives.

The query layer returns a plain list, and ``tests/test_find_books.py`` covers it
there. This module covers the layer above it, because that is where the defect
in issue #19 lives: a zero-match query rendered an empty ``content`` array, so a
caller could not tell "nothing matched" from "the call failed".
"""


def test_zero_matches_still_returns_visible_content(call_tool, parse_payload):
    result = call_tool("find_books", {"author": "Nobody At All"})

    assert result.content, "a zero-match result must still render content"
    assert parse_payload(result) == {"count": 0, "books": []}


def test_matches_are_reported_with_a_count(library, call_tool, parse_payload):
    book_id = library.add_book("A Book")
    library.link_author(book_id, library.add_author("Jane Doe"))
    library.link_series(book_id, library.add_series("Series One"))

    result = call_tool("find_books")

    # Same book the CalibreDB seam returns in test_find_books; wrapping it must
    # not change the entries, only report them alongside a count.
    assert parse_payload(result) == {
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
