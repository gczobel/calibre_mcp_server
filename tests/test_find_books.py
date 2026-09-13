"""``find_books`` at the ``CalibreDB`` seam.

Criteria are optional and combine with AND; text criteria match case- and
accent-insensitively; rating is in whole stars; read is a boolean filter.
"""

import pytest


def _ids(rows):
    """The book ids of ``find_books`` rows, sorted, for comparing to a list."""
    return sorted(row["id"] for row in rows)


def test_returns_book_fields(db, add_book):
    book_id = add_book("A Book", author="Jane Doe", series="Series One")

    rows = db().find_books(limit=10)

    assert rows == [{
        "id": book_id,
        "title": "A Book",
        "author": "Jane Doe",
        "series": "Series One",
        "rating": None,
        "read": None,
    }]


def test_author_criterion_filters(db, add_book):
    b1 = add_book("Book One", author="Jane Doe")
    add_book("Book Two", author="John Roe")

    assert _ids(db().find_books(author="Jane", limit=10)) == [b1]


def test_tag_criterion_filters(db, add_book):
    b1 = add_book("Book One", tags=["fiction"])
    add_book("Book Two", tags=["history"])

    assert _ids(db().find_books(tag="fiction", limit=10)) == [b1]


def test_series_criterion_filters(db, add_book):
    b1 = add_book("Book One", series="Alpha")
    add_book("Book Two", series="Beta")

    assert _ids(db().find_books(series="Alpha", limit=10)) == [b1]


def test_criteria_combine_with_and(db, add_book):
    b1 = add_book("Match", author="Jane Doe", tags=["fiction"])
    add_book("Author only", author="Jane Doe", tags=["history"])
    add_book("Tag only", author="John Roe", tags=["fiction"])

    assert _ids(
        db().find_books(author="Jane", tag="fiction", limit=10)
    ) == [b1]


def test_rating_range(library, db, add_book):
    b1 = add_book("Low")
    library.set_rating(b1, 2)
    b2 = add_book("Mid")
    library.set_rating(b2, 4)
    b3 = add_book("High")
    library.set_rating(b3, 5)

    assert _ids(
        db().find_books(rating_min=3, rating_max=4, limit=10)
    ) == [b2]


def test_rating_min_only(library, db, add_book):
    b1 = add_book("Low")
    library.set_rating(b1, 2)
    b2 = add_book("High")
    library.set_rating(b2, 5)

    assert _ids(db().find_books(rating_min=4, limit=10)) == [b2]


def test_rating_returned_in_stars(library, db, add_book):
    book_id = add_book("A Book")
    library.set_rating(book_id, 4)

    assert db().find_books(limit=10)[0]["rating"] == 4


def test_read_true_false_and_omitted(library, db, add_book):
    col = library.add_custom_column("read", "bool")
    b1 = add_book("Read book")
    library.set_direct_value(col, b1, 1)
    b2 = add_book("Unread book")
    library.set_direct_value(col, b2, 0)
    b3 = add_book("No row book")
    seam = db()

    assert _ids(seam.find_books(read=True, limit=10)) == [b1]
    # A book with no row is unread, same as a stored 0.
    assert _ids(seam.find_books(read=False, limit=10)) == sorted([b2, b3])
    assert _ids(seam.find_books(limit=10)) == sorted([b1, b2, b3])


def test_read_is_none_without_column(db, add_book):
    add_book("A Book")

    assert db().find_books(limit=10)[0]["read"] is None


def test_read_returned_as_bool(library, db, add_book):
    col = library.add_custom_column("read", "bool")
    book_id = add_book("A Book")
    library.set_direct_value(col, book_id, 1)

    assert db().find_books(limit=10)[0]["read"] is True


def test_limit_has_a_sane_default(db, add_book):
    for i in range(30):
        add_book(f"Book {i:02d}")

    assert len(db().find_books()) == 20


def test_limit_is_respected(db, add_book):
    for i in range(30):
        add_book(f"Book {i:02d}")

    assert len(db().find_books(limit=5)) == 5


def test_matching_is_accent_insensitive(db, add_book):
    b1 = add_book("Cien años", author="Gabriel García Márquez")

    assert _ids(db().find_books(author="Garcia", limit=10)) == [b1]


def test_rating_min_greater_than_max_errors(db):
    with pytest.raises(ValueError):
        db().find_books(rating_min=5, rating_max=1)
