"""Rating exposure on ``Book``.

Calibre stores ratings doubled (0-10) in ``ratings`` + ``books_ratings_link``.
``Book.rating`` exposes whole stars 1-5, or None when unrated.
"""

from calibre_mcp_server.calibre_api import Book


def _book(book_id, library):
    return Book(book_id, str(library.path))


def test_unrated_book_rating_is_none(library):
    book_id = library.add_book("A Book")

    assert _book(book_id, library).rating is None


def test_rating_exposed_in_stars(library):
    book_id = library.add_book("A Book")
    library.set_rating(book_id, 4)

    assert _book(book_id, library).rating == 4


def test_each_star_level(library):
    book_id = library.add_book("A Book")
    for stars in range(1, 6):
        library.set_rating(book_id, stars)
        assert _book(book_id, library).rating == stars


def test_rating_exposed_in_to_json(library):
    book_id = library.add_book("A Book")
    library.set_rating(book_id, 3)

    assert _book(book_id, library).to_json()["rating"] == 3
