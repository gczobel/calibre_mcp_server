"""The legacy list tools: bounded results, and an empty result is not an error.

Every one of these predates ``find_books``. They used to return *every* match,
and to raise when a search matched nothing — so a broad pattern could return a
whole library, and "does this library have X?" arrived as a failure.
"""

import pytest

from calibre_mcp_server.calibre_api import DEFAULT_SEARCH_LIMIT, CalibreDB


def _db(library):
    return CalibreDB(str(library.path))


def _book(library, title, author=None, series=None, tags=None):
    book_id = library.add_book(title)
    if author:
        library.link_author(book_id, library.add_author(author))
    if series:
        library.link_series(book_id, library.add_series(series))
    for tag in tags or []:
        library.link_tag(book_id, library.add_tag(tag))
    return book_id


def test_title_search_is_capped_by_default(library):
    for i in range(DEFAULT_SEARCH_LIMIT + 10):
        _book(library, f"Python Book {i:02d}")

    assert len(_db(library).search_books_by_title("Python%")) == (
        DEFAULT_SEARCH_LIMIT
    )


def test_title_search_respects_an_explicit_limit(library):
    for i in range(10):
        _book(library, f"Python Book {i:02d}")

    assert len(_db(library).search_books_by_title("Python%", limit=3)) == 3


def test_a_limit_above_the_match_count_returns_them_all(library):
    for i in range(5):
        _book(library, f"Python Book {i:02d}")

    assert len(_db(library).search_books_by_title("Python%", limit=99)) == 5


def test_limit_must_be_positive(library):
    _book(library, "A Book")

    with pytest.raises(ValueError):
        _db(library).search_books_by_title("A%", limit=0)


def test_tag_lookup_is_capped_too(library):
    for i in range(10):
        _book(library, f"Book {i:02d}", tags=["fiction"])

    assert len(_db(library).get_books_by_tag("fiction", limit=4)) == 4


@pytest.mark.parametrize("method, argument", [
    ("search_books_by_title", "Nope%"),
    ("search_authors_by_name", "Nope%"),
    ("search_books_by_tag", "Nope%"),
    ("get_books_by_author", "Nobody At All"),
    ("get_books_by_author_id", 4242),
    ("get_books_by_series", "No Such Series"),
    ("get_books_by_tag", "no-such-tag"),
])
def test_no_matches_is_an_empty_list_not_an_error(library, method, argument):
    _book(library, "A Book", author="Jane Doe", tags=["fiction"])

    assert getattr(_db(library), method)(argument) == []
