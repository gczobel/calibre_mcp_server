"""Read-state exposure on ``Book``.

``read`` is True (stored 1), False (stored 0 or no row), or None when the
library has no bool column with the read label.
"""

from calibre_mcp_server.calibre_api import Book


def _book(book_id, library, **kwargs):
    return Book(book_id, str(library.path), **kwargs)


def test_no_read_column_read_is_none(library):
    book_id = library.add_book("A Book")

    assert _book(book_id, library).read is None


def test_read_column_with_no_row_is_false(library):
    book_id = library.add_book("A Book")
    library.add_custom_column("read", "bool")

    assert _book(book_id, library).read is False


def test_read_column_one_is_true(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("read", "bool")
    library.set_direct_value(col, book_id, 1)

    assert _book(book_id, library).read is True


def test_read_column_zero_is_false(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("read", "bool")
    library.set_direct_value(col, book_id, 0)

    assert _book(book_id, library).read is False


def test_custom_read_column_label(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("finished", "bool")
    library.set_direct_value(col, book_id, 1)

    book = _book(book_id, library, read_column_label="finished")
    assert book.read is True


def test_non_bool_column_with_read_label_is_ignored(library):
    book_id = library.add_book("A Book")
    library.add_custom_column("read", "text")
    library.add_link_value(1, book_id, "whatever")

    # A text column named "read" is not the read column.
    assert _book(book_id, library).read is None


def test_read_is_exposed_in_to_json(library):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("read", "bool")
    library.set_direct_value(col, book_id, 1)

    assert _book(book_id, library).to_json()["read"] is True
