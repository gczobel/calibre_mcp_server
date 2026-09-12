"""``find_books`` at the ``CalibreDB`` seam.

Criteria are optional and combine with AND; text criteria match case- and
accent-insensitively; rating is in whole stars; read is a boolean filter.
"""

import pytest

from calibre_mcp_server.calibre_api import CalibreDB


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


def _ids(rows):
    return sorted(r["id"] for r in rows)


def test_returns_book_fields(library):
    book_id = _book(library, "A Book", author="Jane Doe", series="Series One")

    rows = _db(library).find_books(limit=10)

    assert rows == [{
        "id": book_id,
        "title": "A Book",
        "author": "Jane Doe",
        "series": "Series One",
        "rating": None,
        "read": None,
    }]


def test_author_criterion_filters(library):
    b1 = _book(library, "Book One", author="Jane Doe")
    _book(library, "Book Two", author="John Roe")

    assert _ids(_db(library).find_books(author="Jane", limit=10)) == [b1]


def test_tag_criterion_filters(library):
    b1 = _book(library, "Book One", tags=["fiction"])
    _book(library, "Book Two", tags=["history"])

    assert _ids(_db(library).find_books(tag="fiction", limit=10)) == [b1]


def test_series_criterion_filters(library):
    b1 = _book(library, "Book One", series="Alpha")
    _book(library, "Book Two", series="Beta")

    assert _ids(_db(library).find_books(series="Alpha", limit=10)) == [b1]


def test_criteria_combine_with_and(library):
    b1 = _book(library, "Match", author="Jane Doe", tags=["fiction"])
    _book(library, "Author only", author="Jane Doe", tags=["history"])
    _book(library, "Tag only", author="John Roe", tags=["fiction"])

    assert _ids(
        _db(library).find_books(author="Jane", tag="fiction", limit=10)
    ) == [b1]


def test_rating_range(library):
    b1 = _book(library, "Low")
    library.set_rating(b1, 2)
    b2 = _book(library, "Mid")
    library.set_rating(b2, 4)
    b3 = _book(library, "High")
    library.set_rating(b3, 5)

    assert _ids(
        _db(library).find_books(rating_min=3, rating_max=4, limit=10)
    ) == [b2]


def test_rating_min_only(library):
    b1 = _book(library, "Low")
    library.set_rating(b1, 2)
    b2 = _book(library, "High")
    library.set_rating(b2, 5)

    assert _ids(_db(library).find_books(rating_min=4, limit=10)) == [b2]


def test_rating_returned_in_stars(library):
    book_id = _book(library, "A Book")
    library.set_rating(book_id, 4)

    assert _db(library).find_books(limit=10)[0]["rating"] == 4


def test_read_true_false_and_omitted(library):
    col = library.add_custom_column("read", "bool")
    b1 = _book(library, "Read book")
    library.set_direct_value(col, b1, 1)
    b2 = _book(library, "Unread book")
    library.set_direct_value(col, b2, 0)
    b3 = _book(library, "No row book")
    db = _db(library)

    assert _ids(db.find_books(read=True, limit=10)) == [b1]
    # A book with no row is unread, same as a stored 0.
    assert _ids(db.find_books(read=False, limit=10)) == sorted([b2, b3])
    assert _ids(db.find_books(limit=10)) == sorted([b1, b2, b3])


def test_read_is_none_without_column(library):
    _book(library, "A Book")

    assert _db(library).find_books(limit=10)[0]["read"] is None


def test_read_returned_as_bool(library):
    col = library.add_custom_column("read", "bool")
    book_id = _book(library, "A Book")
    library.set_direct_value(col, book_id, 1)

    assert _db(library).find_books(limit=10)[0]["read"] is True


def test_limit_has_a_sane_default(library):
    for i in range(30):
        _book(library, f"Book {i:02d}")

    assert len(_db(library).find_books()) == 20


def test_limit_is_respected(library):
    for i in range(30):
        _book(library, f"Book {i:02d}")

    assert len(_db(library).find_books(limit=5)) == 5


def test_matching_is_accent_insensitive(library):
    b1 = _book(library, "Cien años", author="Gabriel García Márquez")

    assert _ids(_db(library).find_books(author="Garcia", limit=10)) == [b1]


def test_rating_min_greater_than_max_errors(library):
    with pytest.raises(ValueError):
        _db(library).find_books(rating_min=5, rating_max=1)
