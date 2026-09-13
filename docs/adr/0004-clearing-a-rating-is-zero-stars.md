# Clearing a rating is set_book_rating with zero stars

Status: accepted

`set_book_rating(book_id, stars)` accepts `0` to clear, rather than the surface gaining a separate
`clear_book_rating` tool. "No rating" is a state of the rating field, not a different operation on it,
so one tool expresses every state the field can be in.

Calibre's unrated state is the absence of a row in `books_ratings_link`, not a stored zero, so clearing
deletes the book's link. The shared `ratings` dictionary row is deliberately left alone: other books may
point at it, and deleting it would unrate them too.

## Considered options

- **A separate `clear_book_rating` tool.** Keeps `stars` a 1-5 range and makes clearing explicit rather
  than overloading a boundary value. Rejected in favour of one tool that can express every state of the
  field, so a caller holding a star count never has to choose an entry point as well as a value.

## Consequences

- `stars` now spans 0-5, and its lower bound no longer means "invalid". Zero is a legal argument.
- Clearing an already-unrated book is a no-op that still reports `rating: null`, which keeps the tool
  idempotent.
- Because `0` is meaningful, a coerced `false` would silently clear a rating. That is why the parameter
  is declared strict — see [ADR-0005](0005-the-tool-boundary-refuses-what-the-seam-refuses.md).
