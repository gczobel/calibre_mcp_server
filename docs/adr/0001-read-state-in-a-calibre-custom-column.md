# Read state lives in a shared Calibre custom column

Status: accepted

Read/unread state is stored in one Calibre custom column, `#read` (Yes/No), written directly to
`metadata.db` by the MCP. The column and the read/write semantics are deliberately the ones
Calibre-Web already uses, so a user who runs both gets one shared piece of state instead of two that
disagree. This makes the MCP a writer to the user's library, which is the reason the library must be
mounted read-write.

## Considered options

- **A sidecar database owned by the MCP.** Simplest and safest: no Calibre writes, no schema coupling.
  Rejected because the state would live outside Calibre, invisible in Calibre's own window and in
  Calibre-Web, which is the opposite of the point.
- **Calibre-Web's own `book_read_link` table.** Needs no Calibre change. Rejected because that table is
  keyed per (book, user) while read state here is per book, and because writing into another
  application's private database means fighting the application that owns it.
- **`calibredb` against a running Content Server.** Calibre's own recommended path, and it avoids
  external writes to a live database. Rejected because it makes Calibre a runtime dependency of the
  container image for a feature that needs one SQL statement.
- **Overloading an existing field.** Rejected: it would give a field two meanings.

## Consequences

- The container mounts the library read-write. The image is unchanged; only the mount is.
- Writing is confined to `custom_column_<id>`, which fires no trigger needing Calibre's SQL functions
  (`title_sort`, `uuid4`). No UDF registration is required. Those functions are needed only by
  triggers on `books`, which a read-state write never touches.
- Calibre-Web reads the column with `coalesce(value, False)`, so a missing row and a `0` both mean
  unread. We write `0` rather than deleting the row, matching Calibre-Web's own writer.
- Two writers can touch this column: the MCP and, if bound, Calibre-Web's UI. Both are plain SQLite
  writers and Calibre-Web keeps no in-memory cache of Calibre metadata, so the realistic failure is a
  `SQLITE_BUSY` to retry, not a lost write. This reasoning does not extend to Calibre itself, which
  does cache metadata and would silently overwrite an external write.
- `bool` columns are `normalized = 0`, the layout the existing reader cannot read. Fixing the reader is
  a prerequisite for any of this being visible.
