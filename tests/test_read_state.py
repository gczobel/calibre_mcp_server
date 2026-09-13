"""Read-state exposure on ``Book``.

``read`` is True (stored 1), False (stored 0 or no row), or None when the
library has no bool column with the read label.
"""


def test_no_read_column_read_is_none(library, book):
    book_id = library.add_book("A Book")

    assert book(book_id).read is None


def test_read_column_with_no_row_is_false(library, book):
    book_id = library.add_book("A Book")
    library.add_custom_column("read", "bool")

    assert book(book_id).read is False


def test_read_column_one_is_true(library, book):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("read", "bool")
    library.set_direct_value(col, book_id, 1)

    assert book(book_id).read is True


def test_read_column_zero_is_false(library, book):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("read", "bool")
    library.set_direct_value(col, book_id, 0)

    assert book(book_id).read is False


def test_custom_read_column_label(library, book):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("finished", "bool")
    library.set_direct_value(col, book_id, 1)

    assert book(book_id, read_column_label="finished").read is True


def test_non_bool_column_with_read_label_is_ignored(library, book):
    book_id = library.add_book("A Book")
    library.add_custom_column("read", "text")
    library.add_link_value(1, book_id, "whatever")

    # A text column named "read" is not the read column.
    assert book(book_id).read is None


def test_read_is_exposed_in_to_json(library, book):
    book_id = library.add_book("A Book")
    col = library.add_custom_column("read", "bool")
    library.set_direct_value(col, book_id, 1)

    assert book(book_id).to_json()["read"] is True
