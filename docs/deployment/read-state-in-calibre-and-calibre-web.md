# Read state in Calibre and Calibre-Web

The server writes read state to the read column in `metadata.db`. Calibre-Web and Calibre each have a
way of not showing that value, and neither one means the write failed.

## Calibre-Web keeps a read state of its own

Calibre-Web is optional. Until you point it at the read column it does not use the column at all, and
stores read state per user in its own table, `book_read_link`. The two then disagree:

- a book marked read in Calibre-Web comes back `read: false` from the server, and
- a book marked read through the server does not change in Calibre-Web.

Both apps work as designed. They read different data.

To point Calibre-Web at the column:

1. Create the column in Calibre first. Calibre-Web cannot create it. See `docs/read-status.md`.
2. In Calibre-Web, open Admin, then UI Configuration, and set "Link Read/Unread Status to Calibre
   Column" to your column. The list holds `0` and every Yes/No column in the library. `0` is the
   default, and means Calibre-Web uses its own read state.
3. Restart Calibre-Web.

Notes on that setting:

- It is `config_read_column` in Calibre-Web's own `app.db`. It stores the column's numeric id, not its
  label. On `metadata.db`, `SELECT id, label FROM custom_columns` gives the id to look for.
- Calibre-Web's UI is the only way to set it. It has no environment variable.
- Step 3 is required. Calibre-Web looks up the library's custom columns once, when it starts, so a
  column created while it is running is invisible to it, and nothing reports an error.
- While it is pointed at the column, Calibre-Web stops listing that column with the book's other custom
  columns. It shows it as the read/unread button instead.

Setting it back to `0` returns Calibre-Web to its own read state. The column keeps its values.

## Calibre shows the old value until you restart it

Calibre reads the library's metadata into memory when it starts, and keeps showing that copy. A write
from outside Calibre, this server's or Calibre-Web's, reaches `metadata.db` right away, and appears in
Calibre only after a restart.

Observed here: a `mark_book_read` appeared in the Calibre-Web browser at once, and in Calibre only
after restarting the application. So Calibre showing the old value is not proof that the write failed.
Check the database first, with the query in `docs/deployment/write-enabled-mount.md`.

The same in-memory copy is why Calibre must not have the library open while this server writes. Calibre
writes its copy back over the file, and the outside write is gone with no error. Quit Calibre before
writing, and start it again to see the result.
