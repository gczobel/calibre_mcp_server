"""Write tools at the ``CalibreDB`` seam.

mark_book_read / mark_book_unread write 1 / 0 into the bool read column;
set_book_rating writes the doubled star value into Calibre's rating tables.
"""

import sqlite3

import pytest

import calibre_mcp_server.calibre_api as calibre_api
from calibre_mcp_server.exceptions import ConfigurationError, DatabaseError, NotFoundError


def test_mark_read_writes_one(library, db, direct_column_value):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("read", "bool")

    db().mark_book_read(book_id)

    assert direct_column_value(col, book_id) == 1


def test_mark_unread_writes_zero(library, db, direct_column_value):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("read", "bool")

    db().mark_book_unread(book_id)

    assert direct_column_value(col, book_id) == 0


def test_mark_read_is_idempotent(library, db):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("read", "bool")
    seam = db()

    seam.mark_book_read(book_id)
    seam.mark_book_read(book_id)

    rows = library.query(
        f"SELECT value FROM custom_column_{col} WHERE book = ?", (book_id,)
    )
    assert len(rows) == 1
    assert rows[0]["value"] == 1


def test_mark_unread_is_idempotent(library, db):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("read", "bool")
    seam = db()

    seam.mark_book_unread(book_id)
    seam.mark_book_unread(book_id)

    rows = library.query(
        f"SELECT value FROM custom_column_{col} WHERE book = ?", (book_id,)
    )
    assert len(rows) == 1
    assert rows[0]["value"] == 0


def test_mark_read_missing_column_errors_and_names_it(library, db):
    book_id = library.add_book("A Book")

    with pytest.raises(ConfigurationError, match="read"):
        db().mark_book_read(book_id)


def test_mark_read_unknown_book_errors(library, db):
    library.add_custom_column("read", "bool")

    with pytest.raises(NotFoundError):
        db().mark_book_read(999)


def test_custom_read_column_label_is_used_on_write(library, db, direct_column_value):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("finished", "bool")

    db(read_column_label="finished").mark_book_read(book_id)

    assert direct_column_value(col, book_id) == 1


def test_set_rating_writes_doubled_value(library, db):
    book_id = library.add_book("A Book")

    db().set_book_rating(book_id, 4)

    rows = library.query(
        "SELECT r.rating FROM ratings r "
        "JOIN books_ratings_link brl ON brl.rating = r.id "
        "WHERE brl.book = ?",
        (book_id,),
    )
    assert rows[0]["rating"] == 8


def test_set_rating_replaces_existing(library, db):
    book_id = library.add_book("A Book")
    seam = db()

    seam.set_book_rating(book_id, 2)
    seam.set_book_rating(book_id, 5)

    rows = library.query(
        "SELECT r.rating FROM ratings r "
        "JOIN books_ratings_link brl ON brl.rating = r.id "
        "WHERE brl.book = ?",
        (book_id,),
    )
    assert len(rows) == 1
    assert rows[0]["rating"] == 10


def test_set_rating_zero_clears_the_rating(library, db, book):
    book_id = library.add_book("A Book")
    seam = db()
    seam.set_book_rating(book_id, 4)

    result = seam.set_book_rating(book_id, 0)

    assert result == {"book_id": book_id, "rating": None}
    # Calibre's unrated state is an absent link row, not a zero rating.
    assert library.query(
        "SELECT rating FROM books_ratings_link WHERE book = ?", (book_id,)
    ) == []
    assert book(book_id).rating is None


def test_cleared_rating_drops_out_of_a_rating_filter(library, db):
    book_id = library.add_book("A Book")
    seam = db()
    seam.set_book_rating(book_id, 4)

    seam.set_book_rating(book_id, 0)

    assert seam.find_books(rating_min=1, limit=10) == []


def test_set_rating_invalid_stars(library, db):
    book_id = library.add_book("A Book")
    seam = db()

    for bad in (6, -1, 2.5, "4", None, True):
        with pytest.raises(ValueError):
            seam.set_book_rating(book_id, bad)


def test_set_rating_unknown_book_errors(db):
    with pytest.raises(NotFoundError):
        db().set_book_rating(999, 3)


def test_held_write_lock_retries_then_reports(monkeypatch, library, db):
    book_id = library.add_book("A Book")
    library.add_custom_column("read", "bool")
    monkeypatch.setattr(calibre_api, "WRITE_BUSY_TIMEOUT", 0.2)

    holder = sqlite3.connect(library.db_path)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(DatabaseError, match="locked|busy|writer"):
            db().mark_book_read(book_id)
    finally:
        holder.rollback()
        holder.close()
