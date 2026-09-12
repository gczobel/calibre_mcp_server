# Read-tracking PoC findings

Captured 2026-09-12 from the live homelab. All probes mounted the library **read-only**; nothing was
written to Calibre or Calibre-Web. Probe stack: `calibre-poc-probe` (Portainer id 39, env 2).

## Library

- Host: a home NAS running Docker, `<nas-host>`. Library path on host: `<library-path>`.
- 62,729 books. Schema `user_version = 27`. `journal_mode = delete` (no WAL).

### Custom columns, as they actually are

| id | label | name | datatype | is_multiple | normalized | data table | rows |
|----|-------|------|----------|-------------|------------|------------|------|
| 1 | `autor_ord` | Autores | composite | 0 | 0 | `custom_column_1` | 0 |
| 2 | `epg_id` | EPL Id | float | 0 | 0 | `custom_column_2` | 62,715 |
| 3 | `estado` | Estado | text | 0 | **1** | `books_custom_column_3_link` | 62,715 |
| 4 | `pages` | Páginas | int | 0 | 0 | `custom_column_4` | 62,715 |
| 5 | `version` | Versión | text | 1 | **1** | `books_custom_column_5_link` | 62,715 |

There is **no read/unread column**. Labels `read`, `read_date`, `read_notes` are all free.

## The reader bug, confirmed against this library

`_load_custom_columns()` in `src/calibre_mcp_server/calibre_api.py` only reads
`books_custom_column_<id>_link`. For `normalized = 0` columns that table does not exist and the value
lives in `custom_column_<id>.value` keyed by `book`. The code has no branch for it, so it assigns
`None` and moves on.

| column | datatype | `normalized` | rows with data | `get_book_details` |
|---|---|---|---|---|
| `estado` | text | 1 | 62,715 | `"Disp."` correct |
| `version` | text | 1 | 62,715 | `"1.2"` correct |
| `pages` | int | 0 | **62,715** | **`null` — bug** |
| `epg_id` | float | 0 | **62,715** | **`null` — bug** |
| `autor_ord` | composite | 0 | 0 | `null` — correct, column is genuinely empty |

Sample `custom_column_4` values: `226, 70, 120, 279, 1108, 250, 385, 410`.
Sample `custom_column_2` values: `10002548.0, 10018828.0, 10016505.0`.

Two of five columns return `null` despite holding a value for every book in the library.

The affected datatypes are `bool`, `int`, `float`, `datetime`, `comments`, `composite`, which is to say
a Yes/No `#read` column would be invisible even after a successful write.

## Rating is invisible too

`books_ratings_link` has 7 rows, `ratings` has 3. `get_book_details` exposes no rating field:
`_load_book_data()` never joins those tables.

## Calibre-Web

Stack `calibres`, container `/calibre-web`, image `lscr.io/linuxserver/calibre-web:latest` with
`DOCKER_MODS=linuxserver/mods:universal-calibre` (so the Calibre CLI is already present in that
container). It mounts the library read-write, so it is already a writer to this library. No real
Calibre process runs against it.

Config read from Calibre-Web's own `app.db` under its config directory:

| setting | value |
|---|---|
| `config_read_column` | **0** (no Calibre column bound) |
| `config_calibre_dir` | `/books` |
| `config_calibre_uuid` | `<library-uuid>` |
| `config_kobo_sync` | 0 |
| `schedule_metadata_backup` | **0** (built-in metadata backup is off) |

Read status is stored in Calibre-Web's own database, not in Calibre:

```
table book_read_link (id, book_id, user_id, read_status, last_modified,
                      last_time_started_reading, times_started_reading)
row   (1, 88870, 1, 1, '2026-09-12 13:59:03.126471', None, 0)
```

Book 88870 is "Fundación" by Isaac Asimov. Marking it read also created one row each in
`kobo_reading_state`, `kobo_bookmark` and `kobo_statistics`.

Because `config_read_column = 0`, Calibre-Web has nowhere in Calibre to put read state, so no tool
reading `metadata.db` can ever see it. Calibre-Web requires the Calibre column to already exist and
cannot create one itself.

## Deployment facts

| container | image | library mount | port |
|---|---|---|---|
| `<mcp-container>` | `ghcr.io/gczobel/calibre-mcp:latest` | `<library-path>:/books:ro` | 9001 |
| `calibre-web` | `lscr.io/linuxserver/calibre-web:latest` | `<library-path>:/books` (rw) | 8083 |

The MCP speaks FastMCP over HTTP at `<host>:9001/mcp` (SSE responses, `mcp-session-id` header).
It advertises 10 tools. This is how the findings above were read from a remote machine.

## Constraints this establishes

1. Any Calibre write path must cope with `journal_mode = delete` and no WAL.
2. Calibre-Web is already an external writer to this library, so a second writer is not a new class
   of risk here, but two writers on one column still need a rule about who wins.
3. `add_custom_column` cannot run remotely, and locally it is blocked while Calibre holds the
   library. Creating a column needs a Calibre-closed step. Calibre-Web does not hold that lock, so a
   one-shot container running `calibredb add_custom_column` against `/books` is plausible.
4. `schedule_metadata_backup = 0`: turn Calibre-Web's metadata backup on before any write work.
