# Read state in other apps

The read column belongs to Calibre. Two other views of the same library can disagree with it, and
neither disagreement is a failed write: Calibre-Web keeps a read state of its own unless you bind it to
the column, and Calibre's own window shows an outside write only once it restarts.

## Calibre-Web: bind it to the column

Calibre-Web is optional, and out of the box it does **not** use this column: it keeps its own read
state, per user, in its own database (`book_read_link`). So

- a book marked read in the Calibre-Web UI still comes back `read: false` from the MCP, and
- a book marked read through the MCP does not change in Calibre-Web.

Neither app is failing. They are reading two different sources.

To make Calibre-Web read and write the Calibre column instead:

1. **Create the column in Calibre first** — Calibre-Web cannot. See `docs/read-status.md`.
2. In Calibre-Web, open **Admin → UI Configuration** and set **"Link Read/Unread Status to Calibre
   Column"** to the column. The list offers `0` plus every Yes/No column in the library. `0` is the
   default and means unbound.
3. Restart Calibre-Web.

Four things about that setting are easy to miss:

- It is Calibre-Web's own `config_read_column`, stored in **its** `app.db`, and it holds the column's
  **numeric id rather than its label**. On `metadata.db`, `SELECT id, label FROM custom_columns` gives
  the id to look for.
- It is set in the UI only. **No environment variable sets it.**
- The restart in step 3 is not optional. Calibre-Web reads the library's custom columns only when it
  starts, so a column created while it is running stays invisible to it, with no error on either side.
- Once bound, Calibre-Web stops listing that column among a book's custom columns and renders it as its
  read/unread button instead. The value is there, under a different control.

Setting it back to `0` returns Calibre-Web to its own read state. The column keeps whatever it holds.

## Calibre's window: stale, not lost

Calibre's desktop application holds the library's metadata in memory and draws from its own copy. An
external write — this server's, or Calibre-Web's — reaches `metadata.db` at once, and Calibre shows it
only after the application restarts.

Observed here: an MCP `mark_book_read` appeared in the Calibre-Web browser UI immediately, and in
Calibre only after a restart. So an unchanged Calibre window is not proof that the write failed: check
the database first, with the query in `docs/deployment/write-enabled-mount.md`.

That same in-memory copy is the reason Calibre must not have the library open while this server writes:
Calibre writes its copy back, and the external write is gone with no error. So quit Calibre before
writing, and start it again to see the result.
