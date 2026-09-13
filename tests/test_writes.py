"""Write tools at the ``CalibreDB`` seam.

mark_book_read / mark_book_unread write 1 / 0 into the bool read column;
set_book_rating writes the doubled star value into Calibre's rating tables.
"""

import sqlite3

import pytest

import calibre_mcp_server.calibre_api as calibre_api
from calibre_mcp_server.calibre_api import Book, CalibreDB
from calibre_mcp_server.exceptions import ConfigurationError, DatabaseError, NotFoundError


def _db(library, **kwargs):
    return CalibreDB(str(library.path), **kwargs)


def _column_value(library, column_id, book_id):
    rows = library.query(
        f"SELECT value FROM custom_column_{column_id} WHERE book = ?",
        (book_id,),
    )
    return rows[0]["value"] if rows else None


def test_mark_read_writes_one(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("read", "bool")

    _db(library).mark_book_read(book_id)

    assert _column_value(library, col, book_id) == 1


def test_mark_unread_writes_zero(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("read", "bool")

    _db(library).mark_book_unread(book_id)

    assert _column_value(library, col, book_id) == 0


def test_mark_read_is_idempotent(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("read", "bool")
    db = _db(library)

    db.mark_book_read(book_id)
    db.mark_book_read(book_id)

    rows = library.query(
        f"SELECT value FROM custom_column_{col} WHERE book = ?", (book_id,)
    )
    assert len(rows) == 1
    assert rows[0]["value"] == 1


def test_mark_unread_is_idempotent(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("read", "bool")
    db = _db(library)

    db.mark_book_unread(book_id)
    db.mark_book_unread(book_id)

    rows = library.query(
        f"SELECT value FROM custom_column_{col} WHERE book = ?", (book_id,)
    )
    assert len(rows) == 1
    assert rows[0]["value"] == 0


def test_mark_read_missing_column_errors_and_names_it(library):
    book_id = library.add_book("A Book")

    with pytest.raises(ConfigurationError, match="read"):
        _db(library).mark_book_read(book_id)


def test_mark_read_unknown_book_errors(library):
    library.add_custom_column("read", "bool")

    with pytest.raises(NotFoundError):
        _db(library).mark_book_read(999)


def test_custom_read_column_label_is_used_on_write(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("finished", "bool")

    _db(library, read_column_label="finished").mark_book_read(book_id)

    assert _column_value(library, col, book_id) == 1


def test_set_rating_writes_doubled_value(library):
    book_id = library.add_book("A Book")

    _db(library).set_book_rating(book_id, 4)

    rows = library.query(
        "SELECT r.rating FROM ratings r "
        "JOIN books_ratings_link brl ON brl.rating = r.id "
        "WHERE brl.book = ?",
        (book_id,),
    )
    assert rows[0]["rating"] == 8


def test_set_rating_replaces_existing(library):
    book_id = library.add_book("A Book")
    db = _db(library)

    db.set_book_rating(book_id, 2)
    db.set_book_rating(book_id, 5)

    rows = library.query(
        "SELECT r.rating FROM ratings r "
        "JOIN books_ratings_link brl ON brl.rating = r.id "
        "WHERE brl.book = ?",
        (book_id,),
    )
    assert len(rows) == 1
    assert rows[0]["rating"] == 10


def test_set_rating_zero_clears_the_rating(library):
    book_id = library.add_book("A Book")
    db = _db(library)
    db.set_book_rating(book_id, 4)

    result = db.set_book_rating(book_id, 0)

    assert result == {"book_id": book_id, "rating": None}
    # Calibre's unrated state is an absent link row, not a zero rating.
    assert library.query(
        "SELECT rating FROM books_ratings_link WHERE book = ?", (book_id,)
    ) == []
    assert Book(book_id, str(library.path)).rating is None


def test_cleared_rating_drops_out_of_a_rating_filter(library):
    book_id = library.add_book("A Book")
    db = _db(library)
    db.set_book_rating(book_id, 4)

    db.set_book_rating(book_id, 0)

    assert db.find_books(rating_min=1, limit=10) == []


def test_set_rating_invalid_stars(library):
    book_id = library.add_book("A Book")
    db = _db(library)

    for bad in (6, -1, 2.5, "4", None, True):
        with pytest.raises(ValueError):
            db.set_book_rating(book_id, bad)


def test_set_rating_unknown_book_errors(library):
    with pytest.raises(NotFoundError):
        _db(library).set_book_rating(999, 3)


def test_held_write_lock_retries_then_reports(monkeypatch, library):
    book_id = library.add_book("A Book")
    library.add_custom_column("read", "bool")
    monkeypatch.setattr(calibre_api, "WRITE_BUSY_TIMEOUT", 0.2)

    holder = sqlite3.connect(library.db_path)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(DatabaseError, match="locked|busy|writer"):
            _db(library).mark_book_read(book_id)
    finally:
        holder.rollback()
        holder.close()
