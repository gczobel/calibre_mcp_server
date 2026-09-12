# Read status: the column contract

Read state is stored in **one Calibre custom column**. Everything here depends on Calibre alone.

Calibre-Web is a **compatibility reference, not a dependency**. We borrow two things from it: the
column it expects for read status, and the semantics it reads and writes. The payoff is that if a
user does run Calibre-Web, it agrees with us instead of maintaining a second, conflicting read state.
Nothing in the install, the setup, or the runtime requires Calibre-Web to exist.

## The column

| property | value |
|---|---|
| label | the server's read-column setting, default `read` (Calibre displays it as `#read`) |
| datatype | `bool` (Yes/No) |
| storage | auxiliary table `custom_column_<id>` |
| constraint | `UNIQUE(book)`, `value INT NOT NULL` |

`<id>` is the numeric `custom_columns.id`, assigned when the column is created. Nothing is stored on
the `books` table; `books` is never touched by a read-status change.

The label is configurable so a user who already keeps read state in a differently named column does
not have to rename it. Whatever the label, the column must exist before read status can be read or
written.

## Semantics

| value | meaning |
|---|---|
| row with `1` | read |
| row with `0` | unread |
| no row at all | unread |

Absence and `0` both mean unread. A newly created column has no rows, so every book starts unread with
no backfill.

## When the column is absent

**Reads tolerate it.** Book data reports read state as `null`, which means "this library has no read
tracking" and is deliberately not the same as `false`. Search and browsing carry on unchanged, with no
join and no error.

**Writes do not.** Marking a book read or unread without the column raises an error naming the column.
A write that silently does nothing is worse than a refusal.

## We use Calibre-Web's logic

Calibre-Web's `edit_book_read_status()` is the reference implementation. We match it exactly:

- **mark read**: write `1`
- **mark unread**: write `0`. It does **not** delete the row.
- **a book with no row** that gets marked read gets a row with `1`

Calibre-Web reads the column with `coalesce(value, False) != True` for unread, so a missing row and a
`0` are equivalent to it. Matching its writer means the column never drifts depending on which side
you clicked.

## If the user happens to run Calibre-Web (optional)

Skip this entirely if they don't. Nothing above depends on it.

Calibre-Web stores the **numeric column id, not the label**, in its `config_read_column` setting. Once
set, Calibre-Web's read/unread button writes this column instead of its private `book_read_link`
table, and both the MCP and the Calibre-Web UI operate on the same state. Left unset, Calibre-Web
keeps its own separate read state, which will disagree with this column.

## SQL

Read one book:

```sql
SELECT value FROM custom_column_<id> WHERE book = ?
```

Write, using the `UNIQUE(book)` index Calibre already creates:

```sql
INSERT INTO custom_column_<id> (book, value) VALUES (?, ?)
  ON CONFLICT(book) DO UPDATE SET value = excluded.value
```

## Creating the column

**Calibre-Web is not involved, and is not required.** It cannot create a custom column at all. A user
with nothing but a Calibre library needs one of these:

- **Calibre's GUI**, the normal path for most people: Preferences → Add your own columns → Add custom
  column. Lookup name `read` (or whatever the read-column setting names), column type Yes/No.
- **Calibre's CLI**: `calibredb add_custom_column read "Read" bool`. It is marked `no_remote`, so it
  must run against a local library, and it is blocked while Calibre has that library open.

Either route also produces the `custom_column_<id>` table, its `UNIQUE(book)` index, its index on
`book`, and its foreign-key check triggers. No manual DDL is needed.

## Prerequisite

`bool` is one of the datatypes the current reader returns `null` for, because
`_load_custom_columns()` only reads the link-table layout used by `normalized = 1` columns. A `#read`
column is `normalized = 0`. **The reader must be fixed before read status is visible at all.** See
`docs/research.md`.
