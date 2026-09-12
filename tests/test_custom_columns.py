"""Custom-column reader tests.

The reader must return stored values for the non-link layout (bool, int,
float, datetime, comments) while keeping the link layout working. These tests
exercise the reader through ``Book``.
"""

from calibre_mcp_server.calibre_api import Book


def _book(book_id, library):
    return Book(book_id, str(library.path))


def test_int_column_returns_stored_value(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("pages", "int")
    library.set_direct_value(col, book_id, 321)

    book = _book(book_id, library)
    assert book.custom_columns["pages"] == 321


def test_float_column_returns_stored_value(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("price", "float")
    library.set_direct_value(col, book_id, 12.5)

    book = _book(book_id, library)
    assert book.custom_columns["price"] == 12.5


def test_bool_column_returns_true_and_false(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("read", "bool")
    library.set_direct_value(col, book_id, 1)

    assert _book(book_id, library).custom_columns["read"] is True

    library.set_direct_value(col, book_id, 0)
    assert _book(book_id, library).custom_columns["read"] is False


def test_comments_column_returns_stored_text(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("notes", "comments")
    library.set_direct_value(col, book_id, "some long text")

    assert _book(book_id, library).custom_columns["notes"] == "some long text"


def test_datetime_column_returns_stored_value(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("added", "datetime")
    library.set_direct_value(col, book_id, "2024-01-01 00:00:00+00:00")

    assert (
        _book(book_id, library).custom_columns["added"]
        == "2024-01-01 00:00:00+00:00"
    )


def test_link_layout_column_still_works(library):
    """Regression guard: the existing link-table layout keeps resolving values."""
    book_id = library.add_book("A Book")
    col = library.add_custom_column("genre", "text")
    library.add_link_value(col, book_id, "Science Fiction")

    assert _book(book_id, library).custom_columns["genre"] == "Science Fiction"


def test_multiple_link_values_are_joined(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("genre", "text")
    library.add_link_value(col, book_id, "Science Fiction")
    library.add_link_value(col, book_id, "Fantasy")

    assert (
        _book(book_id, library).custom_columns["genre"]
        == "Science Fiction & Fantasy"
    )


def test_composite_column_reads_stored_text(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("computed", "composite")
    library.set_direct_value(col, book_id, "Jane Doe")

    assert _book(book_id, library).custom_columns["computed"] == "Jane Doe"
