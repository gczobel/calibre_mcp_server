"""Rating exposure on ``Book``.

Calibre stores ratings doubled (0-10) in ``ratings`` + ``books_ratings_link``.
``Book.rating`` exposes whole stars 1-5, or None when unrated.
"""


def test_unrated_book_rating_is_none(library, book):
    book_id = library.add_book("A Book")

    assert book(book_id).rating is None


def test_rating_exposed_in_stars(library, book):
    book_id = library.add_book("A Book")
    library.set_rating(book_id, 4)

    assert book(book_id).rating == 4


def test_each_star_level(library, book):
    book_id = library.add_book("A Book")
    for stars in range(1, 6):
        library.set_rating(book_id, stars)
        assert book(book_id).rating == stars


def test_rating_exposed_in_to_json(library, book):
    book_id = library.add_book("A Book")
    library.set_rating(book_id, 3)

    assert book(book_id).to_json()["rating"] == 3
