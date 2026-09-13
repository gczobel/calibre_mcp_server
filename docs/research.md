# Research notes

Condensed from four longer documents that were working notes. The decisions live in `docs/adr/`, the
contracts in `docs/tool-surface.md` and `docs/read-state.md`. This file holds only what those rest on.

## Calibre's storage, as far as we touch it

- A custom column is an auxiliary table `custom_column_<id>`: one row per book, `UNIQUE(book)`,
  `value INT NOT NULL`. The `books` table is never touched by a read-state write.
- Calibre's triggers on that table are foreign-key checks only. The triggers that call SQL functions
  (`title_sort`, `uuid4`) are on `books`, so a custom-column write needs no UDF registration. That is
  the workaround `Xpresi/calibre-mcp` needed for title writes; we do not need it.
- Non-normalized datatypes (`bool`, `int`, `float`, `datetime`, `comments`, `composite`) use that
  layout. `text`, `series`, `enum` and `rating` use a dictionary table plus a link table. The reader
  currently handles only the link layout, which is the bug.
- `journal_mode = delete`, not WAL, so writers exclude each other at whole-file granularity.
- Ratings live in `ratings` plus `books_ratings_link`, stored doubled at 0–10. Calibre-Web's star widget
  renders `rating / 2` padded to five, which is why the tools speak in 1–5 stars. A stored `0` means no
  rating, and those rows are absent.

## Why writes sit behind a precondition

Direct SQLite writes are not safe by default. Calibre keeps metadata in memory and writes it back with
`INSERT OR REPLACE`, so an externally written value survives only until Calibre next edits that book and
field. Then it is overwritten with no error and no trace. The failure mode is silent loss, not
corruption.

Nothing in the database tells a third-party process whether Calibre holds the library, so the
precondition cannot be checked, only documented. That is why the read-write mount is an explicit
operator decision rather than a default.

## What the other projects do

Twelve Calibre MCP servers were surveyed. One writes `metadata.db` directly, five shell out to
`calibredb`, one drives Calibre's Python API through a `calibre-debug` worker, four are read-only, and
none uses the Content Server's HTTP write API. **None creates a custom column**; every one writes into
a column the user made by hand. **None implements read-tracking.**

Both mechanisms that avoid direct writes cost a running dependency: `calibredb --with-library` needs a
Content Server plus a write-enabled account, and a local `calibredb` refuses to start while Calibre
holds the library. Requiring either before a user can mark a book read was judged a worse trade than
accepting the risk above.

## Calibre-Web: compatibility, never a dependency

Calibre-Web keeps read state in its own `book_read_link` table when no Calibre column is bound, and in a
bound Calibre column when one is. Its writer `edit_book_read_status()` writes `1` for read and `0` for
unread and never deletes the row. Its reader uses `coalesce(value, False)`, so a missing row and a `0`
both mean unread. We match both, so a user running Calibre-Web gets one shared state rather than two
that disagree. Nothing requires Calibre-Web to exist.

## Live evidence

Verified against a real library, mounted read-only. Columns using the non-link layout (an Integer and
a Float, each holding a value for every book) returned `null`. Columns using the link layout, both
text, read correctly. A newly added Yes/No column also returned `null`, which is the reader bug sitting
directly on the feature.

The join is not the cost. A whole-library `LEFT JOIN` onto a column table completes in tens of
milliseconds, which is why the reader fix is about correctness rather than performance.
