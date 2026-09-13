# Tool surface

The tools this fork adds or changes, and the data they carry. This file records what the surface is;
`docs/adr/` records why it is that shape and what each decision rejected.

## Two different kinds of work

**Exposing what Calibre already has.** Rating has always been stored; the server has simply never
returned it. So have `timestamp`, `last_modified`, `uuid` and the ebook formats on disk. None of this is a new feature; it is the server
under-reporting a library that already holds the data.

**Adding what does not exist.** Calibre has no read field. `#read` is genuinely new data, needs a
column the user creates, and is the only reason a write path exists.

## Rating scale

**1 to 5 whole stars, no halves.** That is what Calibre's GUI shows and what Calibre-Web shows: its star
widget renders `rating / 2` filled stars padded to five.

Calibre stores ratings doubled, 0 to 10, in `ratings` plus `books_ratings_link`. A book's rating *is*
its row in `books_ratings_link`, so "unrated" is an absent row there, not a stored `0`. Tools speak in
stars and convert at the boundary, so a stored value never leaks into a tool's arguments or result.

## Reading a book

`get_book_details` gains two fields:

- `read`: `true`, `false`, or `null` when the library has no read column. `null` means "no read
  tracking here", which is not the same as unread, and the distinction must survive into the result.
- `rating`: whole stars 1 to 5, or `null` when unrated.

## Finding books

One filter tool, not a flag repeated on each of the existing list tools. The useful questions combine
criteria, and the existing tools each take exactly one.

```
find_books(author?, tag?, series?, rating_min?, rating_max?, read?, limit?)
```

- every criterion optional, combined with AND
- `rating_min` / `rating_max` in stars, so an exact rating is `min = max` ("4 stars") and "4 or better"
  needs no different shape
- `read`: `true` for read only, `false` for unread only, omitted for both
- `limit` has a small default, so an omitted parameter cannot return a library
- returns `count` alongside `books`, each row carrying `id`, `title`, `author`, `series`, `rating`,
  `read`

No matches is `{"count": 0, "books": []}`. That wrapper exists because a bare empty list renders no
content at all at the tool boundary, which left a caller unable to tell "nothing matched" from "the
call failed". It is a deliberate break rather than an inconsistency to tidy away — the older list tools
still return bare lists — so read [ADR-0003](adr/0003-find-books-returns-a-count-alongside-its-books.md)
before simplifying it back.

Criteria match case- and accent-insensitively, reusing the text normalization the title search already
applies. A Spanish library has to find "García" when asked for "Garcia".

The existing narrow tools are not removed. They become redundant rather than wrong, and removing them
would be a breaking change for anyone already calling them.

## Writing

- `mark_book_read(book_id)`, idempotent
- `mark_book_unread(book_id)`, idempotent
- `set_book_rating(book_id, stars)`, 1 to 5, or `0` to clear, idempotent

Clearing (`stars = 0`) deletes the book's row from `books_ratings_link`, which is Calibre's own unrated
state: an absent link, not a stored `0`. The `ratings` dictionary row is deliberately left in place,
because other books may share it. Clearing an already-unrated book is therefore a no-op that still
reports `rating: null`. There is no separate clearing tool on purpose: see
[ADR-0004](adr/0004-clearing-a-rating-is-zero-stars.md).

`stars` is declared strict, so `"4"` is refused as well as `false` rather than being coerced to a
number. The boundary refuses what the `CalibreDB` seam refuses, and never more permissively: see
[ADR-0005](adr/0005-the-tool-boundary-refuses-what-the-seam-refuses.md).

Writes need the library mounted read-write and the `#read` column to exist. A missing column is an
error naming the column. Reads tolerate its absence and report `null` instead. That asymmetry is
deliberate: a read that cannot find read state is still a useful read, but a write that silently does
nothing is worse than a refusal.

## Deliberately not exposed yet

`timestamp` (date added), `last_modified`, `uuid`, and the ebook formats on disk stay unreturned.
Formats is the one likely to be wanted next, since knowing an epub exists is what makes "send this to
my Kindle" answerable.
