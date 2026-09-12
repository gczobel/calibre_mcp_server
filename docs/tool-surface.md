# Tool surface

The tools this fork adds or changes, and the data they carry.

## Two different kinds of work

**Exposing what Calibre already has.** Rating has always been stored; the server has simply never
returned it. So have `timestamp`, `last_modified`, `uuid` and the ebook formats on disk. And custom
columns using Calibre's non-link storage layout (bool, int, float, date, long text, composite) return
`null` today whatever is stored in them. None of this is a new feature; it is the server
under-reporting a library that already holds the data.

**Adding what does not exist.** Calibre has no read field. `#read` is genuinely new data, needs a
column the user creates, and is the only reason a write path exists.

## Rating scale

**1 to 5 whole stars, no halves.** That is what Calibre's GUI shows and what Calibre-Web shows: its star
widget renders `rating / 2` filled stars padded to five.

Calibre stores ratings doubled, 0 to 10, in `ratings` plus `books_ratings_link`. A stored `0` means no
rating, and Calibre deletes both rows rather than keeping one. Tools speak in stars and convert at the
boundary, so a stored value never leaks into a tool's arguments or result.

## Reading a book

`get_book_details` gains two fields:

- `read`: `true`, `false`, or `null` when the library has no read column. `null` means "no read
  tracking here", which is not the same as unread, and the distinction must survive into the result.
- `rating`: whole stars 1 to 5, or `null` when unrated.

Both stay invisible until the custom-column reader is fixed for the non-link layout.

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
- returns rows carrying `id`, `title`, `author`, `series`, `rating`, `read`

Criteria match case- and accent-insensitively, reusing the text normalization the title search already
applies. A Spanish library has to find "García" when asked for "Garcia".

The existing narrow tools are not removed. They become redundant rather than wrong, and removing them
would be a breaking change for anyone already calling them.

## Writing

- `mark_book_read(book_id)`, idempotent
- `mark_book_unread(book_id)`, idempotent
- `set_book_rating(book_id, stars)`, 1 to 5

Writes need the library mounted read-write and the `#read` column to exist. A missing column is an
error naming the column. Reads tolerate its absence and report `null` instead. That asymmetry is
deliberate: a read that cannot find read state is still a useful read, but a write that silently does
nothing is worse than a refusal.

## Deliberately not exposed yet

`timestamp` (date added), `last_modified`, `uuid`, and the ebook formats on disk stay unreturned.
Formats is the one likely to be wanted next, since knowing an epub exists is what makes "send this to
my Kindle" answerable.
