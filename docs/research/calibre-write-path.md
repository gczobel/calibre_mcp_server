# Writing reading-status metadata to a Calibre library: on-disk schema, sanctioned write paths, and concurrency safety

Research for a proposed feature: mark a book as *read* (plus finish date, rating, note), store it in
Calibre itself, and query it back. This document establishes what the Calibre formats and APIs
actually are, before any design is committed to.

## Scope, version, and method

**Calibre versions researched**

| What | Version | Date |
|---|---|---|
| Latest release at time of writing | **9.14.0** (`v9.14.0`) | released 2026-08-28 |
| Source code read | `kovidgoyal/calibre` `master` @ `f472f7c762c7d327e41cc1dacba9db0ba9293de5` | 2026-09-12 |
| Test database file read | `src/calibre/db/tests/metadata.db`, sha256 `87f6025937728b5312d7af55160565208e0aae0308c9e9bc19873cf502bf56a1` | from `master` |

All source citations are permalinks pinned to the commit above, so the line anchors stay valid.
Every downloaded file was hash-checked; the important ones:

- `src/calibre/db/backend.py` — sha256 `b491d83e0b324dcc61ee0ed379ef6d0fc4286a6e1a844c42884a1f1ac50002ef`
- `src/calibre/db/write.py` — sha256 `705c1fb2274af4addd9dbdfb8ffae8141daca913d5e1b76f7bb63f67719fab57`
- `src/calibre/srv/cdb.py` — sha256 `6cf1ad09de93f5e838ddc626ab63bc2e0b2c2e2dcc74f0f0ea52007aedcae053`
- `src/calibre/db/cli/main.py` — sha256 `389f12643c629cfd10dc8150191f2e658834f619048becc3fd78064b9c69867b`

**Epistemic labels used throughout.** Each substantive claim is marked:

- **[verified]** — read directly in Calibre source, or observed in a Calibre-produced `metadata.db`.
- **[documented]** — stated in Calibre's own manual or by the maintainer in a public tracker answer.
- **[inferred]** — a conclusion I drew from source behaviour; not stated as such anywhere.
- **[uncertain]** — evidence is thin, contradictory, or I could not confirm it.

A note on the brief: it names `src/calibre/db/schema.py` as a key file. That module no longer exists on
`master`; schema construction now lives in `src/calibre/db/backend.py` (creation) and
`src/calibre/db/schema_upgrades.py` (historical migrations). The binary test fixture
`src/calibre/db/tests/metadata.db` was the most direct evidence available and is used heavily below.

---

## A. Exact on-disk schema of `metadata.db`

### A.1 The `custom_columns` table

**[verified]** — source: `src/calibre/db/schema_upgrades.py`, `SchemaUpgrade.upgrade_version_9`
(permalink: [`schema_upgrades.py#L264-L282`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/schema_upgrades.py#L264-L282)),
confirmed byte-for-byte against `PRAGMA table_info(custom_columns)` on the shipped
`src/calibre/db/tests/metadata.db` (schema version 27).

```sql
CREATE TABLE custom_columns (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    label    TEXT NOT NULL,
    name     TEXT NOT NULL,
    datatype TEXT NOT NULL,
    mark_for_delete   BOOL DEFAULT 0 NOT NULL,
    editable BOOL DEFAULT 1 NOT NULL,
    display  TEXT DEFAULT "{}" NOT NULL,
    is_multiple BOOL DEFAULT 0 NOT NULL,
    normalized BOOL NOT NULL,
    UNIQUE(label)
);
CREATE INDEX IF NOT EXISTS custom_columns_idx ON custom_columns (label);
```

Meaning of each column:

| Column | Meaning | Evidence |
|---|---|---|
| `id` | The **column number** `N`. The physical table is named after this number, not the label. | `DB.custom_table_names()` returns `custom_column_{num}`, `books_custom_column_{num}_link` — [`backend.py#L1697-L1698`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L1697-L1698) |
| `label` | Machine name, used with a `#` prefix (`#read`). Must match `^\w*$`, start with a letter, and be all lowercase. | `DB.create_custom_column()` validation — [`backend.py#L1389-L1390`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L1389-L1390) |
| `name` | Human-readable heading shown in the UI. | [`backend.py#L823-L833`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L823-L833) |
| `datatype` | One of `rating, text, comments, datetime, int, float, bool, series, composite, enumeration`. Enforced by `DB.create_custom_column()` against the `CUSTOM_DATA_TYPES` frozenset. | `CUSTOM_DATA_TYPES` — [`backend.py#L87-L98`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L87-L98); check at [`#L1391-L1392`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L1391-L1392) |
| `mark_for_delete` | Soft-delete tombstone. On the next library open, `initialize_custom_columns()` drops both physical tables, drops the indexes/triggers/views, queues `update_all_last_mod_dates_on_start`, and finally `DELETE FROM custom_columns WHERE mark_for_delete=1`. | [`backend.py#L791-L815`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L791-L815); set by `delete_custom_column()` at [`#L1536-L1539`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L1536-L1539) |
| `editable` | Whether the field can be edited through the metadata editor. Surfaced to `calibredb set_metadata --list-fields`, which filters on `m['is_editable']`. | `cmd_set_metadata.get_fields()` — [`cmd_set_metadata.py#L97-L110`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/cmd_set_metadata.py#L97-L110) |
| `display` | JSON blob of per-datatype presentation options (`date_format`, `enum_values`, `number_format`, `is_names`, `composite_template`, `allow_half_stars`, `default_value`, …). Parsed with `json.loads` into `data['display']`. | [`backend.py#L823-L835`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L823-L835); documented option lists in `cmd_add_custom_column.py#L50-L74` |
| `is_multiple` | "Tag-like" multi-valued column. **Coerced**: `is_multiple = is_multiple and datatype in ('text', 'composite')`. | [`backend.py#L1394`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L1394) |
| `normalized` | Storage-layout selector. Computed once, at creation, as `datatype not in ('datetime', 'comments', 'int', 'bool', 'float', 'composite')`. Never changes afterwards. | [`backend.py#L1393`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L1393) |

**[verified]** `display` is the *only* one of these fields that can be changed after creation.
`DB.set_custom_column_metadata(num, name=, label=, is_editable=, display=)` issues `UPDATE`s for exactly
those four and has no parameter for `datatype`, `is_multiple`, or `normalized` —
[`backend.py#L1363-L1382`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L1363-L1382).
**[inferred]** Consequently, a column's storage layout is immutable for its lifetime. Changing a
column's *type* means deleting the column and creating a new one, which discards the data.

**Orphan cleanup [verified].** `initialize_custom_columns()` cross-checks every row against
`DB.custom_tables` (a set of table names matching `custom_column_*` or `books_custom_column_*`). If the
expected physical table is missing — or, for a normalized column, the link table is missing — the row is
deleted from `custom_columns` with the warning
`WARNING: Custom column {!r} not found, removing.` —
[`backend.py#L848-L867`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L848-L867).
This matters for the feature: **if the physical tables do not exist, Calibre silently deletes the
`custom_columns` row on next open.**

### A.2 `custom_columns.id` ↔ data tables; `is_multiple` and `normalized`

**[verified]** `DB.create_custom_column()` emits one of two schemas depending on `normalized`
([`backend.py#L1412-L1530`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L1412-L1530)).
Type affinity is chosen by this mapping, taken verbatim from
[`#L1401-L1411`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L1401-L1411):

| `datatype` | SQL type in the physical table | `normalized` |
|---|---|---|
| `rating`, `int` | `INT` | `True` |
| `text`, `comments`, `series`, `composite`, `enumeration` | `TEXT` (+ `COLLATE NOCASE`) | `True`, except `comments` and `composite` → `False` |
| `float` | `REAL` | `False` |
| `datetime` | `timestamp` | `False` |
| `bool` | `BOOL` | `False` |

**Layout 1 — `normalized = 1` (value dictionary + link table).** Real schema from the shipped test
database, `custom_column_2` (a `rating` column) and its link table:

```sql
CREATE TABLE custom_column_2(
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    value INT NOT NULL, link TEXT NOT NULL DEFAULT "",
    UNIQUE(value));
CREATE INDEX custom_column_2_idx ON custom_column_2 (value);

CREATE TABLE books_custom_column_2_link(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book INTEGER NOT NULL,
    value INTEGER NOT NULL,
    UNIQUE(book, value));
CREATE INDEX books_custom_column_2_link_aidx ON books_custom_column_2_link (value);
CREATE INDEX books_custom_column_2_link_bidx ON books_custom_column_2_link (book);
```

Plus three `fkc_*` triggers enforcing that `book` exists in `books` and `value` exists in
`custom_column_2` (`fkc_insert_*`, `fkc_update_*_a`, `fkc_update_*_b`), one `fkc_delete_{lt}` trigger
deleting links when a dictionary entry is deleted, and two `tag_browser_*` views.

**Layout 2 — `normalized = 0` (value inline, one row per book).**

```sql
CREATE TABLE custom_column_1(
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    book  INTEGER,
    value TEXT NOT NULL COLLATE NOCASE,
    UNIQUE(book));
CREATE INDEX custom_column_1_idx ON custom_column_1 (book);
```

Plus `fkc_insert_custom_column_1` / `fkc_update_custom_column_1` triggers.

**The critical asymmetry for this feature [verified].** In Layout 1 the *value* column is an integer
pointing into the dictionary table's `id`. In Layout 2 the *value* column holds the value itself and the
row is keyed by `book`. Confirmed by data: `custom_column_2` holds `(id=1, value=2)`, `(id=2, value=4)`
and `books_custom_column_2_link` holds `(4, 1, 2)`, `(5, 2, 3)` — i.e. link rows carry `book, value=id`.

**[verified]** `is_multiple` selects the in-memory table class, and only matters for normalized columns:
`ManyToManyTable` when `is_multiple`, `ManyToOneTable` otherwise —
[`backend.py#L1046-L1053`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L1046-L1053).
Because `is_multiple` is forced `False` for every datatype except `text` and `composite`, a
`Y/N`/`Date`/`rating` column is always single-valued.

**[inferred]** Redundant duplicates are structurally impossible for Layout 1 single-valued columns:
`books_custom_column_N_link` has `UNIQUE(book, value)`, but nothing enforces at most one row per book.
Calibre itself relies on its own logic to keep one row per book (`DELETE ... WHERE book=?` then
`INSERT`, see C.3). A third-party writer has no such guarantee from the schema.

### A.3 Where each of the four fields lives, and how it is encoded

#### A.3.1 Yes/No (`bool`)

**[verified]** Not normalized. One row per book in `custom_column_<id>`, keyed by `book`, unique per
book. On-disk value is **integer `0` or `1`**, ordinary SQLite integer affinity despite the `BOOL`
type name: the test fixture's `custom_column_6` (`datatype = bool`) contains `typeof(value)` = `integer`
for both `1` and `0`.

```sql
-- #read = yes for book 42, where #read has custom_columns.id = 6
INSERT OR REPLACE INTO custom_column_6 (book, value) VALUES (42, 1);
-- #read = no
INSERT OR REPLACE INTO custom_column_6 (book, value) VALUES (42, 0);
```

**[verified] Undefined is a third state, expressed as absence of the row.** Calibre defaults to tri-state
booleans: `defs['bools_are_tristate'] = tweaks.get('bool_custom_columns_are_tristate', 'yes') == 'yes'` —
[`backend.py#L702-L704`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L702-L704).
The bool adapter maps the strings `'none'` and `''` to Python `None` —
`adapt_bool()` at [`backend.py#L901-L914`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L901-L914)
and `write.adapt_bool()` at [`write.py#L92-L105`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/write.py#L92-L105)
— and `None` takes the delete path in `one_one_in_other()`:
`DELETE FROM {table} WHERE book=?` — [`write.py#L227-L231`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/write.py#L227-L231).
**Design consequence:** "not read" is genuinely distinguishable from "unread" (explicit `false`). The
feature should decide which one `#read = false` means, and write `None`/absent if it wants "unknown".

#### A.3.2 Date (`datetime`)

**[verified]** Not normalized. One row per book in `custom_column_<id>`, value column is SQL type
`timestamp`.

**On-disk encoding: an ISO-8601 string, not a Julian day float.** This directly contradicts the
hypothesis in the brief. Evidence:

```sql
CREATE TABLE custom_column_5(               -- datatype = datetime
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book INTEGER, value timestamp NOT NULL, UNIQUE(book));
```
and the actual values in the shipped fixture:
`2011-09-05 06:00:00+00:00`, `2011-09-01 06:00:00+00:00`, with `typeof(value) = 'text'`.

The serializer is unambiguous —
`src/calibre/db/write.py`, `sqlite_datetime()`:

```python
def sqlite_datetime(x):
    return isoformat(x, sep=' ') if isinstance(x, datetime) else x
```
([`write.py#L20-L21`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/write.py#L20-L21)),

with `isoformat()` at
[`calibre/utils/date.py#L213-L219`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/utils/date.py#L213-L219)
normalising to UTC (`as_utc=True` is the default) and joining with a **space**, not `T`.
`sqlite_datetime` is the value mapper on the write path for both
`one_one_in_books()` ([`write.py#L204`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/write.py#L204))
and `one_one_in_other()` ([`write.py#L236`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/write.py#L236)).

**The sentinel for "no date"**: `UNDEFINED_DATE = datetime(101, 1, 1, tzinfo=utc_tz)` —
[`calibre/utils/iso8601.py#L14`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/utils/iso8601.py#L14).
`adapt_datetime()` (read side, [`write.py#L65-L70`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/write.py#L65-L70))
and the reader `c_parse()` ([`db/tables.py#L20-L43`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/tables.py#L20-L43))
both map undefined dates to that sentinel rather than `NULL`. So `None` on write means "delete the row";
the *sentinel string* means "explicitly undefined".

**[verified]** The reader tolerates an integer: `c_parse` catches a bare number and returns
`datetime(int(val), 1, 3, tzinfo=utc_tz)` with the comment
`# If a value like 2001 is stored in the column, apsw will return it as an int`. So a year-only or
Julian-looking integer is accepted on read but is not what Calibre writes.

**Encoding summary for a writer:** store
`YYYY-MM-DD HH:MM:SS+00:00` in UTC. Either add the Python value as a `datetime` and let an adapter
format it, or format it explicitly — do not assume SQLite date functions will agree, since the column is
stored as text.

#### A.3.3 Long text (`comments`)

**[verified]** Not normalized. One row per book in `custom_column_<id>`:

```sql
CREATE TABLE custom_column_1(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book INTEGER, value TEXT NOT NULL COLLATE NOCASE, UNIQUE(book));
```
Values in the fixture are **HTML fragments**: `<div>My Comments One<p></p></div>`.

The adapter for `comments` is `single_text` (strip, empty → `None`), deliberately *not* the multi-value
adapter: `'comments': lambda x, d: adapt_text(x, {'is_multiple': False})` —
[`backend.py#L939`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L939).

**[inferred]** The `COLLATE NOCASE` and the leading/trailing HTML wrapper are Calibre UI conventions for
the *comments* datatype; a `text` datatype column (`datatype = 'text'`, `normalized = 1`, dictionary +
link table) is the more natural fit for a short note that is not meant to render as flowing prose.
**[uncertain]** I found no normative statement in the manual that `#notes` must be HTML-wrapped; the
fixture value and `single_text` are all I have. A design that must survive round-tripping through
Calibre's own editor should probably store HTML.

#### A.3.4 Built-in `rating` — the brief's suspicion is **confirmed**

**[verified]** Rating is **not** a column on `books`. It is a dictionary table plus a link table, exactly
as suspected. Real definitions from the shipped fixture:

```sql
CREATE TABLE ratings (
    id INTEGER PRIMARY KEY,
    rating INTEGER CHECK(rating > -1 AND rating < 11),
    link TEXT NOT NULL DEFAULT "",
    UNIQUE (rating));

CREATE TABLE books_ratings_link (
    id INTEGER PRIMARY KEY,
    book INTEGER NOT NULL,
    rating INTEGER NOT NULL,
    UNIQUE(book, rating));
CREATE INDEX books_ratings_link_aidx ON books_ratings_link (rating);
CREATE INDEX books_ratings_link_bidx ON books_ratings_link (book);
```

plus `fkc_insert_books_ratings_link`, `fkc_update_books_ratings_link_a/_b` triggers, and — importantly —
the `books_delete_trg` trigger established at schema version 5 runs
`DELETE FROM books_ratings_link WHERE book=OLD.id;`
([`schema_upgrades.py#L147-L158`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/schema_upgrades.py#L147-L158)).

The field metadata that binds these tables is declared in
`src/calibre/library/field_metadata.py`:
`'rating': {'table': 'ratings', 'column': 'rating', 'link_column': 'rating', 'datatype': 'rating', …}`
([`field_metadata.py#L121-L137`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/library/field_metadata.py#L121-L137)).

**Scale — this is the single easiest thing to get wrong [verified].** The *stored* range is **0–10**;
the UI range is 0–5 with optional half stars.

- `CHECK(rating > -1 AND rating < 11)` — the schema above.
- `rating_to_stars(value, allow_half_stars=False)`: `r = max(0, min(int(value or 0), 10)); ans = star * (r // 2)` — [`ebooks/metadata/__init__.py#L502-L507`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/ebooks/metadata/__init__.py#L502-L507).
- Search parses a user query with `adjust(x) = x // 2` for `datatype == 'rating'` — [`db/search.py#L290-L305`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/search.py#L290-L305).

**A trap worth flagging [verified].** The two *CLI* entry points to a rating field use **different
scales**:

| Path | Conversion | Source |
|---|---|---|
| `calibredb set_metadata --field rating:4` (built-in) | `val = float(raw) * 2` → stores `8` | `field_from_string()`, [`ebooks/metadata/book/base.py#L872-L873`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/ebooks/metadata/book/base.py#L872-L873) |
| `calibredb set_custom rating <id> 5` (custom `rating` column) | `None if x in {None,0} else min(10, max(0, int(x)))` → stores `5` | `get_adapter()`, [`db/write.py#L160-L163`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/write.py#L160-L163) |

So through `set_custom`, a custom `rating` column takes the **raw 0–10** value, while
`set_metadata --field` for the built-in rating takes **0–5** and doubles it. A feature that goes through
`set_metadata --field rating:5` writes `10`; the same feature expressed as a custom column must write
`10` directly for a 5-star rating.

**[verified] Additional semantics for the built-in rating**, from `RatingTable.read_id_maps()`
([`db/tables.py#L371-L385`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/tables.py#L371-L385)):

- A stored rating of `0` is treated as "no rating", not "zero stars": on read, links to `rating = 0`
  rows are **deleted** and the `ratings` row with `rating = 0` is **deleted**.
- Therefore a writer must not create `ratings.rating = 0`; clearing a rating means deleting the
  `books_ratings_link` row.
- `ratings` is a *shared dictionary*: rows are reused across books and, per `many_one()`, unused rows are
  garbage-collected (`DELETE FROM ratings WHERE id=?`) when their last link disappears —
  [`db/write.py#L376-L383`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/write.py#L376-L383).
  A direct-SQL writer must therefore resolve-or-create the `ratings.id` for a value, then upsert the
  link row, and must not assume stable ids across Calibre operations.

### A.4 Schema stability across versions

**No — the schema is not stable, and it changed very recently.** Three concrete pieces of evidence:

1. **[verified]** Schema versioning is a forward-only ladder: `SchemaUpgrade.__init__` loops
   `upgrade_version_{uv}` from the current `PRAGMA user_version` upward inside a
   `BEGIN EXCLUSIVE TRANSACTION`, writing `PRAGMA user_version = uv + 1` after each step
   ([`schema_upgrades.py#L11-L31`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/schema_upgrades.py#L11-L31)).
   It runs on **every** database open, from the `DB.__init__` constructor —
   [`backend.py#L579-L580`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L579-L580).
   The shipped fixture is at `user_version = 27`; the highest upgrade step on `master` is
   `upgrade_version_26` ("Drop unused columns from books and create pages table").
2. **[verified]** That step 26 does `ALTER TABLE books DROP COLUMN` for `flags`, `isbn`, and `lccn`,
   creates `books_pages_link`, recreates the `meta` view, and sets
   `PRAGMA application_id = 0x63616c69` —
   [`schema_upgrades.py#L816-L895`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/schema_upgrades.py#L816-L895).
3. **[documented]** This drop has already broken a real third-party deployment. In the MobileRead
   thread *Calibre 9.3.1 incorrectly reports database is corrupted* (2026-02-26), a user reports:
   *"Calibre 9 removes three long unused columns from the 'books' table (isbn, lccn and flags). If
   something previously created a SQLite view called metax in your metadata.db (likely a third party
   plugin that somehow needed an extended meta view) then SQLite refuses to drop those columns because
   metax still references them."*
   Fix required manual SQL (`DROP VIEW IF EXISTS metax;`) outside Calibre.
   <https://www.mobileread.com/forums/showthread.php?p=4570014> — note this is a *user* post, not the
   maintainer; the maintainer's involvement is reported second-hand ("Problem fixed thanks to Kovid
   Goyal"), so treat the mechanism as **documented-by-report**, and the schema change itself as
   **[verified]** from source.

**[verified]** `custom_columns` itself has been added to: step 25 walks every normalized column and runs
`ALTER TABLE custom_column_{N} ADD COLUMN link TEXT NOT NULL DEFAULT '';`, and does the same for
`publishers`, `series`, `tags`, `languages`, `ratings` —
[`schema_upgrades.py#L820-L846`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/schema_upgrades.py#L820-L846).
**Consequence for a direct-SQL writer:** the `link` column is `NOT NULL DEFAULT ''`, so inserts that omit
it are fine; but a writer that assumes a fixed column list, or that issues a bare `INSERT INTO
custom_column_N (book, value)`, is relying on defaults that were themselves added by a migration.

**Does Calibre rebuild or renormalize these tables?** 

- **[verified]** Deleting a column (setting `mark_for_delete = 1`) is destructive and final: the next
  open runs `DROP INDEX`, `DROP TRIGGER`, `DROP VIEW`, `DROP TABLE` and then removes the
  `custom_columns` row ([`backend.py#L796-L815`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L796-L815)).
- **[verified]** Merely *opening* a library will run `DDL` if `user_version` is behind.
- **[inferred]** Renormalizing a live column (flipping `normalized` or `is_multiple` in place) does not
  appear anywhere in the codebase — the values are read once and used to pick a table class
  ([`backend.py#L1039-L1060`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L1039-L1060)).
  **[uncertain]** There is no explicit guard preventing a *future* Calibre version from doing so.
- **[verified]** Directory-restore (`calibredb restore_database`) **recreates** custom columns from OPF
  metadata and explicitly detects conflicting definitions, reporting
  *"The following custom columns have conflicting definitions and were not fully restored"* —
  `src/calibre/db/restore.py`, `Restore.conflicting_custom_cols` /
  `Restore.report` ([`restore.py#L78-L121`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/restore.py#L78-L121)).
  Custom column *values* do live in OPF files (`serialize_user_metadata()` writes
  `calibre:user_metadata:<label>` entries —
  [`ebooks/metadata/opf2.py#L522-L541`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/ebooks/metadata/opf2.py#L522-L541)),
  **but** the OPF is only refreshed for books in the `metadata_dirtied` table (see B.9/C.3).

**Bottom line for A.4:** the *shape* of `custom_columns` and of a given custom column's physical table is
stable in the sense that Calibre won't spontaneously rewrite it. What is not stable is (a) `user_version`
laddering forward on open, (b) the `books` table's own column set (three columns dropped in v9), and
(c) anything a third party adds to the database that a future migration touches.

---

## B. Sanctioned write paths for an external process

### B.5 `calibredb set_metadata`

**[documented]** Manual: <https://manual.calibre-ebook.com/generated/en/calibredb.html> (section
`set_metadata`), and the option help is generated from `cmd_set_metadata.option_parser()`
([`cmd_set_metadata.py#L57-L94`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/cmd_set_metadata.py#L57-L94)).

```
calibredb set_metadata [options] book_id [/path/to/metadata.opf]
  -f, --field  field_name:value   (repeatable)
  -l, --list-fields
```

**[verified]** `--field` parsing is `field, val = x.partition(':')[::2]` — so **the value is everything
after the first colon**, and the field name is everything before it
([`cmd_set_metadata.py#L150-L151`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/cmd_set_metadata.py#L150-L151)).
That is what makes `--field identifiers:isbn:XXXX,doi:YYYYY` work, and it means a note containing a colon
is fine *after* the first separator. Field names are validated against
`set_metadata --list-fields`, which enumerates every `is_editable` field from `field_metadata`,
including custom columns under their `#label` names, plus `sort`→`title_sort` aliasing and any
`#series_index`-style companions
([`cmd_set_metadata.py#L97-L110`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/cmd_set_metadata.py#L97-L110),
[`#L146-L170`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/cmd_set_metadata.py#L146-L170)).

**Real examples for the four fields this feature needs:**

```bash
# Yes/No custom column  #read  (bool)  -> stored as integer 1
calibredb set_metadata --field '#read:true' 42
calibredb set_metadata --field '#read:no'   42     # bool parser accepts true/yes/y and false/no/n

# Date custom column  #read_date  (datetime)
calibredb set_metadata --field '#read_date:2026-09-12' 42
calibredb set_metadata --field '#read_date:2026-09-12T20:15:00+00:00' 42

# Long-text custom column  #read_notes  (comments or text)
calibredb set_metadata --field '#read_notes:Finished on the train. Great ending.' 42

# Built-in rating -> user scale 0-5, doubled internally to 0-10
calibredb set_metadata --field 'rating:5' 42
```

**[verified]** The value coercion behind those examples is `field_from_string()`
([`ebooks/metadata/book/base.py#L865-L903`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/ebooks/metadata/book/base.py#L865-L903)):

| datatype | accepted | notes |
|---|---|---|
| `bool` | `true/yes/y` → `True`; `false/no/n` → `False` | anything else raises `ValueError: Unknown value for {field}: {raw}`. **`none`/empty are *not* accepted here**, even though the DB layer understands them |
| `datetime` | `parse_iso8601(raw, require_aware=True)` — **timezone-aware required** — falling back to `parse_only_date(raw)` | so a bare `2026-09-12` works via the fallback; a naive datetime string does not |
| `rating` | `float(raw) * 2` | user scale 0–5 |
| `int`, `float` | `int(raw)` / `float(raw)` | |
| `text` with `is_multiple` | split on `is_multiple['ui_to_list']` | |
| anything else | raw string | |

**[verified] A subtle failure mode:** `set_metadata --field` for a **`rating` custom column** is ambiguous
in the code, because `field_from_string` switches on datatype only and a custom `rating` column has
`datatype == 'rating'`. `--field '#myrating:5'` therefore also multiplies by 2, producing a stored `10`.
This matches the built-in rating but is the opposite of `set_custom`'s raw 0–10 for the same column type.
**[inferred]** Both work out to "5 UI stars = stored 10" for `set_metadata`; but a caller mixing the two
CLIs for a custom rating column will silently get 2× errors on one of the paths.

**Can it target a running Calibre instance? Yes — via a URL, and it does route through the content
server.**

**[documented]** Manual, Global Options:

> `--library-path`, `--with-library` — Path to the calibre library. Default is to use the path stored in
> the settings. You can also connect to a calibre Content server to perform actions on remote libraries.
> To do so use a URL of the form: `http://hostname:port/#library_id` …

**[verified]** Implementation: `DBCtx.__init__` treats a `library_path` whose scheme is `http`/`https` as
**remote** and stores a `browser` (mechanize) instance plus `is_remote = True`; the URL fragment becomes
`library_id`, and `#-` triggers a library listing via `/ajax/library-info`
([`db/cli/main.py#L140-L176`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/main.py#L140-L176),
[`#L235-L248`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/main.py#L235-L248)).

**[verified]** `DBCtx.remote_run()` POSTs msgpack to
`{url}/cdb/cmd/{command}/{version}`, optionally `?library_id=…`, with
`Content-Type: application/vnd.calibre.msgpack` and `Accept` the same —
[`db/cli/main.py#L213-L233`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/main.py#L213-L233).
So yes: **targeting a running instance routes through the content server's `/cdb/cmd/...` API.**

**[documented]** Kovid Goyal's answer in the MobileRead "Server" thread *Linux running gui and using
calibredb at the same time* (2024-04-13):

> Run the content server in the gui, then have calibredb connect to the server, and you can add books and
> do other operations. See the docs for calibredb on how to specify a server to connect to.

<https://www.mobileread.com/forums/showthread.php?p=4414690>

### B.6 `calibredb add_custom_column`

**[documented]** Manual:

```
calibredb add_custom_column [options] label name datatype
  --is-multiple          (only applies if datatype is text)
  --display              JSON dict of per-type options
```
`datatype` is one of `bool, comments, composite, datetime, enumeration, float, int, rating, series, text`.

**[verified]** The datatype set is hard-coded twice: `CUSTOM_DATA_TYPES` in
[`cmd_add_custom_column.py#L13-L24`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/cmd_add_custom_column.py#L13-L24)
and the identical frozenset in
[`db/backend.py#L87-L98`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L87-L98).

Exact commands for this feature:

```bash
# Yes/No - "read"
calibredb add_custom_column read "Read" bool

# Date - "date finished"
calibredb add_custom_column read_date "Date read" datetime

# Long text - "reading notes" (comments renders as prose; text is a plain value)
calibredb add_custom_column read_notes "Reading notes" comments
```

Optional, equivalent forms via `--display`:

```bash
calibredb add_custom_column read_notes "Reading notes" text \
  --display '{"is_names": false}'
calibredb add_custom_column read_date "Date read" datetime \
  --display '{"date_format": "yyyy-MM-dd"}'
```

**[verified] `add_custom_column` cannot target a running library.** The module declares
`no_remote = True` ([`cmd_add_custom_column.py#L12`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/cmd_add_custom_column.py#L12)),
and `run_cmd()` refuses:
`raise SystemExit(_('The {} command is not supported with remote (server based) libraries'))` —
[`db/cli/main.py#L54-L59`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/main.py#L54-L59).
Its `implementation()` is a bare `raise NotImplementedError()`.

**[verified]** Locally, it is also blocked whenever Calibre is running. `DBCtx.__init__` calls
`singleinstance('db')`, and if that fails raises the message quoted in C.10
([`db/cli/main.py#L163-L176`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/main.py#L163-L176)).

**[verified]** After creating the column it re-opens the library and persists refreshed field metadata
into the `field_metadata` preference —
[`cmd_add_custom_column.py#L83-L92`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/cmd_add_custom_column.py#L83-L92).
**[inferred]** A tool that creates the column by direct SQL instead would skip this step; the practical
effect is at worst a stale preference that Calibre rewrites, not corruption. **[uncertain]** I did not
verify whether a stale `field_metadata` preference causes any visible misbehaviour.

### B.7 Does the content server expose an endpoint that writes book metadata?

**Yes — `POST /cdb/set-fields/{book_id}` writes arbitrary metadata fields, including custom columns.**
It is real, it is what the official CLI uses, and it is **not documented in the manual**.

**[verified]** Endpoint registry. `cdb_run` handles `/cdb/cmd/{which}/{version}` and refuses unless the
command module is readable by the caller:

```python
if not getattr(m, 'readonly', False):
    ctx.check_for_write_access(rd)
```
— [`srv/cdb.py#L27-L41`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/srv/cdb.py#L27-L41).
It also refuses for users with per-library restrictions and requires an exactly matching command
`version`.

**[verified]** Full inventory of write-capable content-server endpoints on `master`, with their
`needs_db_write` flag (which the router asserts into `ctx.check_for_write_access` —
[`srv/routes.py#L369-L372`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/srv/routes.py#L369-L372)):

| Endpoint | File / symbol | What it writes | Writes custom columns? |
|---|---|---|---|
| `POST /cdb/set-fields/{book_id}[/{library_id}]` | `srv/cdb.py::cdb_set_fields` ([L182-L254](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/srv/cdb.py#L182-L254)) | arbitrary field names via `db.set_field(field, {book_id: value})`, plus cover, added/removed formats | **yes** — `#label` fields go straight through |
| `POST /cdb/cmd/{which}/{version}` | `srv/cdb.py::cdb_run` ([L27-L65](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/srv/cdb.py#L27-L65)) | dispatches to any `readonly = False` CLI command module | **yes** — via `set_metadata` / `set_custom` |
| `POST /cdb/add-book/{job_id}/{add_duplicates}/{filename}[/{library_id}]` | `cdb_add_book` ([L73-L126](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/srv/cdb.py#L73-L126)) | new book + formats | no |
| `POST /cdb/delete-books/{book_ids}[/{library_id}]` | `cdb_delete_book` ([L129-L146](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/srv/cdb.py#L129-L146)) | book removal | no |
| `POST /cdb/set-cover/{book_id}[/{library_id}]` | `cdb_set_cover` ([L149-L164](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/srv/cdb.py#L149-L164)) | cover | no |
| `POST /cdb/copy-to-library/{target_library_id}[/{library_id}]` | `cdb_copy_to_library` ([L257-L312](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/srv/cdb.py#L257-L312)) | copies books between libraries | copies them |
| `POST /book-set-last-read-position/{library_id}/{book_id}/{fmt}` | `srv/books.py::…` ([L233](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/srv/books.py#L233)) | reading position | no |
| `POST /set-note/{field}/{item_id}[/{library_id}]` | `srv/content.py` ([L534](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/srv/content.py#L534)) | category-item / field notes | notes only |

Plus one annotation-sync endpoint at `srv/content.py#L627` and `#L654` (endpoint decorators clipped in
my grep; flagged **[uncertain]** as to their exact routes).

**Authentication and authorisation [verified].** `Context.check_for_write_access()`
([`srv/handler.py#L120-L126`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/srv/handler.py#L120-L126)):

```python
def check_for_write_access(self, request_data):
    if not request_data.username:
        if request_data.is_trusted_ip:
            return
        raise HTTPForbidden('Anonymous users are not allowed to make changes')
    if self.user_manager.is_readonly(request_data.username):
        raise HTTPForbidden(f'The user {request_data.username} does not have permission to make changes')
```

Two important consequences:

1. **A write-capable account is required.** The read-only user model that most deployments use for the
   content server is not enough; the feature would need a separate, write-enabled account (or a
   trusted-IP/anonymous configuration, which is weaker).
2. `cdb_run` additionally requires `ctx.check_for_write_access(rd)` for any module without
   `readonly = True`, and both `set_metadata` and `set_custom` declare `readonly = False`. So
   `/cdb/cmd/set_metadata/0` is a **write** endpoint even though `set_metadata` can also be used purely
   to read field metadata (`action == 'field_metadata'`).

**[verified] Officially supported vs. internal.** `srv/cdb.py` carries `:type` documentation directives
generated by the `endpoint` decorator and the handlers have docstrings, but:

- **[verified]** `manual/server.rst` on `master` documents only end-user concerns — installation, user
  accounts, HTTPS, reverse proxying, offline mode. Grepping it for `API`, `endpoint`, `/ajax`, `/cdb`,
  or `REST` returns **nothing**. There is no content-server HTTP API chapter in the manual.
- **[documented]** The *only* public-sanctioned interface to `/cdb/cmd/...` is `calibredb
  --with-library http://…` — Kovid's answer at
  <https://www.mobileread.com/forums/showthread.php?p=4414690> and the `--with-library` manual text.
- **[inferred]** Therefore: `/cdb/cmd/...` is *stable in practice* (it is a documented-cross-version
  contract — `version = 0` is checked and a mismatch yields
  `The module {which} is not available in version: {version}`, and the CLI is tested in-tree via
  `src/calibre/db/cli/tests.py`), but it is **not a published API**. `/cdb/set-fields/...` is one step
  further from the contract: it is not even exposed by any `calibredb` subcommand. Building a feature
  directly on `/cdb/set-fields/` means depending on an internal endpoint. Building it on
  `calibredb --with-library` means depending on a shipped, documented CLI, which is much safer.

### B.8 Is Calibre's Python API usable as a library from another process?

**[documented]** The manual has a page for exactly this:
<https://manual.calibre-ebook.com/db_api.html> ("API documentation for the database interface"):

> This API is thread safe (it uses a multiple reader, single writer locking scheme). You can access this
> API like this:
> ```python
> from calibre.library import db
> db = db('Path to calibre library folder').new_api
> ```

Source: `manual/db_api.rst`.

**Embedding is possible but not officially supported as an external dependency. [verified]:**

- The API is not published as an installable package. There is no `calibre` distribution on PyPI that
  provides `calibre.db`; the project ships as a full source tree plus a bundled build
  (`manual/develop.rst` describes getting the source and running with `CALIBRE_DEVELOP_FROM` pointing at
  the `src` folder, or installing the Calibre binary and using it as a runtime).
- `src/calibre/db/backend.py` imports compiled extensions that are not separable:
  `from calibre_extensions.sqlite_extension import set_ui_language` and
  `plugins.load_apsw_extension(self, 'sqlite_extension')` in `Connection.__init__`
  ([`backend.py#L409-L415`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L409-L415)),
  plus `winutil` on Windows. `calibre_extensions` only exists inside a Calibre installation.
- `Connection` is an `apsw.Connection` subclass, and the schema itself registers Calibre-only SQL
  functions and collations — `title_sort`, `author_to_author_sort`, `uuid4`, `books_list_filter`,
  `icucollate`, `PYNOCASE`, `concat`, `sortconcat*`, `identifiers_concat`, `aum_sortconcat`
  ([`backend.py#L418-L436`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L418-L436)).
  The `books_delete_trg` trigger calls `title_sort(NEW.title)`; the `tag_browser_*` views call
  `books_list_filter`. **[inferred]** Concurrent access to the same database from a plain `sqlite3`
  connection would fail on those functions if any trigger or view needs them — a real hazard for a
  direct-SQL writer, though ordinary `INSERT`/`UPDATE` on the custom-column tables does not appear to
  touch them.

**[inferred] Verdict:** using `calibre.db` from another Python project is only realistic when Calibre
itself is installed and importable (i.e. the MCP server runs on the same host with Calibre's bundled
Python, or the plugin route in B.9). It is not a dependency you can declare in `pyproject.toml`.

### B.9 Other sanctioned mechanisms

- **[verified] `--library-path` semantics.** `--library-path` and `--with-library` are literal aliases of
  one option (`go.add_option('--library-path', '--with-library', …)` —
  [`db/cli/main.py#L66-L84`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/main.py#L66-L84)).
  A filesystem path is expanded with `os.path.expanduser`; anything starting with `http:`/`https:` is
  remote. Default is `prefs['library_path']`; if that is unset, the tool exits with
  `No saved library path, either run the GUI or use the --with-library option`.
- **[verified] `CALIBRE_OVERRIDE_DATABASE_PATH`.** Lets `metadata.db` live outside the library folder;
  `DB.__init__` reads it (`self.dbpath = os.environ.get('CALIBRE_OVERRIDE_DATABASE_PATH', self.dbpath)` —
  [`backend.py#L503-L541`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L503-L541)).
  **[documented]** The manual recommends it "if your library folder is on a networked drive that does
  not support file locking" (`manual/customize.rst`). **This is a design constraint for the feature:** a
  tool that hardcodes `<CALIBRE_LIBRARY_PATH>/metadata.db` is wrong on such deployments. The current MCP
  server does exactly that.
- **[verified] `read_only` exists but does not give you a lock-free reader.** `DB.__init__` has a
  `read_only=False` parameter; when set, it copies `metadata.db` to a temp file and points the connection
  there:
  ```python
  elif read_only and os.path.exists(self.dbpath):
      # Work on only a copy of metadata.db to ensure that
      # metadata.db is not changed
  ```
  ([`backend.py#L536-L541`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L536-L541)).
  **[uncertain]** No `calibredb` subcommand passes `read_only=True`; I found none in
  `src/calibre/db/cli/`. It is reachable only through `create_backend()` in `calibre/db/legacy.py`
  ([`legacy.py#L41-L50`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/legacy.py#L41-L50)).
- **[verified] Plugins.** Calibre plugins run *inside* Calibre and get the live `Cache` via
  `self.gui.current_db.new_api` ([documented] `manual/db_api.rst`). A plugin would be the
  best-integrated write path — it sees the in-memory cache, so it never clobbers it — but it requires
  installing code into Calibre, which is a far heavier ask than an MCP server talking to a library.
  **[verified]** There is also a content-server plugin mechanism
  (`src/calibre/srv/tests/content_server_plugin.py` exists in-tree), i.e. server-side plugins are a real
  extension point. **[uncertain]** Its stability/registration contract is outside what I verified here.
- **[documented] Not a mechanism: editing `.opf` files.** From bug #2003338, Kovid Goyal:
  *"OPF files are backups for metadata.db editing will have no effect."*
  <https://bugs.launchpad.net/calibre/+bug/2003338> — confirmed by
  `src/calibre/db/backup.py::MetadataBackup`, which walks the `metadata_dirtied` table every 2 seconds and
  **writes** OPFs from the DB, never the reverse
  ([`db/backup.py#L18-L110`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backup.py#L18-L110)).
  So writing `metadata.opf` cannot be used to smuggle metadata in.

---

## C. Concurrency and safety — the critical path

### C.10 What Calibre says about an external process writing to `metadata.db` while Calibre runs

**The strongest statement in the codebase is a hard refusal, not a warning.** `calibredb` will not even
start against a local library when another Calibre program holds the library. `DBCtx.__init__`:

```python
if not singleinstance('db'):
    ext = '.exe' if iswindows else ''
    raise SystemExit(
        _(
            'Another calibre program such as {} or the main calibre program is running.'
            ' Having multiple programs that can make changes to a calibre library'
            ' running at the same time is a bad idea. calibredb can connect directly'
            ' to a running calibre Content server, to make changes through it, instead.'
            ' See the documentation of the {} option for details.'
        ).format('calibre-server' + ext, '--with-library')
    )
```
— [`db/cli/main.py#L163-L176`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/main.py#L163-L176).

This is a **filesystem advisory lock**, not a database lock:
`singleinstance()` → `create_single_instance_mutex()` takes `fcntl.lockf(..., LOCK_EX | LOCK_NB)` on a
lock file (`~/.calibre-singleinstance-<euid>-db.lock` on Linux) —
[`calibre/utils/lock.py#L154-L201`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/utils/lock.py#L154-L201).
**[inferred]** It is keyed on the *program*, not the *library*: it stops `calibredb` from running
alongside Calibre at all, and it does nothing to stop a third-party process that does not participate in
it (such as an MCP server opening the file with `sqlite3.connect`).

**[documented]** Kovid Goyal, 2024, responding to exactly the "how bad can it be" question:

> Run the content server in the gui, then have calibredb connect to the server, and you can add books and
> do other operations.

<https://www.mobileread.com/forums/showthread.php?p=4414690>

**[documented]** Kovid Goyal, 2018, on why even *read-only* commands are blocked:

> There is no method that makes no changes to the database. Simply opening a database can make changes to
> it (schema upgrades happen automatically on database open).

— bug #1772293, status **Won't Fix**, <https://bugs.launchpad.net/calibre/+bug/1772293>

This second quote is the sharpest statement available for this section and it applies directly to the
proposed feature: **the read path in the existing MCP server is already not read-only in the strict
sense** — SQLite itself does not run DDL on open, but any Calibre process that opens the library will.
The schema-upgrade-on-open behaviour is **[verified]** in source: `SchemaUpgrade.__init__` runs inside
`DB.__init__` ([`backend.py#L579-L580`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L579-L580),
[`schema_upgrades.py#L11-L31`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/schema_upgrades.py#L11-L31)).

**[uncertain] Was that 2018 statement about `metadata.db` specifically?** The bug is about `calibredb`
concurrency generally, not about external tools. I found **no** maintainer statement that says in so many
words "do not write to metadata.db from a third-party tool" — nor one that sanctions it. The evidence is
a refusal plus a design that routes all writes through Calibre. I am flagging this because it means the
feature's PR rationale cannot cite a rule that says "don't"; it can only cite a rule that says "don't do
this *concurrently*", plus the mechanism-level evidence below.

### C.11 In-memory caching, write-back, locks, and journal mode

**Yes — Calibre caches the entire library in memory and writes its own state back. An external write can
be lost. This is the crux of the whole question.**

**[verified]** The class docstring, `src/calibre/db/cache.py`:

> An in-memory cache of the metadata.db file from a calibre library. This class also serves as a
> threadsafe API for accessing the database. The in-memory cache is maintained in normal form for
> maximum performance.
>
> SQLITE is simply used as a way to read and write from metadata.db robustly. All table
> reading/sorting/searching/caching logic is re-implemented.

— `src/calibre/db/cache.py` `#L146-L155`, the class-level docstring of `Cache`
([permalink](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cache.py#L146-L155)).

**[verified]** There is no watcher on `metadata.db` and no mtime check anywhere on this path. `LibraryBroker`
(`srv/library_broker.py`) keeps a `loaded_dbs` dict of long-lived `Cache` objects, one per library, and
only discards them on an explicit GUI library change or an unload
([`srv/library_broker.py#L216-L345`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/srv/library_broker.py#L216-L345)).
One caveat on this claim, since it is doing a lot of work: `src/calibre/srv/auto_reload.py` *is* a
filesystem watcher, but it is a development convenience that watches only source-like extensions —
`EXTENSIONS_TO_WATCH = frozenset('py pyj svg js css'.split())` with a 2-second `BOUNCE_INTERVAL`
([`srv/auto_reload.py#L31-L38`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/srv/auto_reload.py#L31-L38)) —
and has nothing to do with library data.
**[inferred]** A running Calibre will therefore *never* notice an external row that was inserted behind
its back, and will keep serving its stale in-memory copy. The only way to make it re-read is a library
switch/reload (or a restart).

**[verified] Where the clobber happens, per field layout.** Writes are keyed on the in-memory
`book_col_map`, and values equal to the cached value are skipped entirely:

- Non-normalized (`bool`, `datetime`, `comments`, `int`, `float`) — `one_one_in_other()`:
  ```python
  g = field.table.book_col_map.get
  book_id_val_map = {k: v for k, v in book_id_val_map.items() if v != g(k, missing)}
  ...
  db.executemany(
      'INSERT OR REPLACE INTO {}(book,{}) VALUES (?,?)'.format(...),
      ((k, sqlite_datetime(v)) for k, v in updated.items()))
  ```
  ([`db/write.py#L222-L239`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/write.py#L222-L239))
  Note `INSERT OR REPLACE` keyed on `book` — if Calibre sets a field for a book, it **replaces the whole
  row** for that book, discarding whatever an external writer put there for a *different* column in the
  same table. (For non-normalized columns each column has its own table, so cross-column clobbering is
  limited to the same column.)

- Normalized single-valued — `many_one()`, delete-then-insert:
  ```python
  if updated:
      sql = ('DELETE FROM {0} WHERE book=?; INSERT INTO {0}(book,{1}) VALUES(?, ?)')
      db.executemany(sql.format(table.link_table, m['link_column']), ...)
  ```
  ([`db/write.py#L361-L373`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/write.py#L361-L373))
  And unused dictionary rows are garbage-collected:
  `remove = {item_id: item_val for item_id, item_val in table.id_map.items() if not table.col_book_map.get(item_id, False)}` → `DELETE FROM {m['table']} WHERE id=?`
  ([`db/write.py#L375-L383`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/write.py#L375-L383))
  **[inferred]** This is a second, subtler clobber: an external writer that creates a dictionary row and
  a link row for a column Calibre believes is empty will have **both** rows deleted the next time
  Calibre rewrites that field for that book.

- Non-normalized columns are written with `sqlite_datetime(v)`, i.e. a Python `datetime` is converted on
  the way out ([`db/write.py#L232-L237`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/write.py#L232-L237)).

**So the failure is precisely conditioned:** an external write to a *book+field pair that Calibre has not
itself modified since the library was opened* survives, because the “value unchanged” filter and the
per-book keying mean Calibre never touches that row. The moment the same user edits that field for that
book in the GUI (or a bulk edit rewrites it), Calibre writes from its in-memory value and the external
value is gone — **silently**, with no error and no conflict detection. **[inferred]** Equally, a bulk
operation like "Edit metadata for many books" that sets the field for a selection will clobber every
external value in that selection.

**[verified] Locks.** Calibre's locking is in-process and unrelated to the database file.
`Cache.__init__` builds a readers/writer pair with `create_locks()`
([`db/cache.py#L173`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cache.py#L173));
`create_locks()` returns a `SHLock`-based multiple-readers/single-writer pair and explicitly warns that
misuse "will happen" and that `LockingError` is the benign outcome
([`db/locking.py#L30-L62`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/locking.py#L30-L62)).
`set_metadata` and `set_custom` take `with db.write_lock:` around the mutation
([`cmd_set_metadata.py#L30-L54`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/cmd_set_metadata.py#L30-L54),
[`cmd_set_custom.py#L13-L39`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cli/cmd_set_custom.py#L13-L39)).
**[inferred]** None of this is visible to another *process*. There is no advisory lock file a third-party
tool could take to coordinate.

**[verified] File-level locking is the only cross-process coordination, and it is configured as follows:**

- `Connection.BUSY_TIMEOUT = 10000  # milliseconds`, applied as
  `self.setbusytimeout(self.BUSY_TIMEOUT)` in `Connection.__init__` —
  [`db/backend.py#L406-L420`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L406-L420).
  **[inferred]** So Calibre will wait up to 10 s for a foreign lock before erroring.
- Calibre also sets `PRAGMA foreign_keys=ON`, `PRAGMA cache_size=-5000`, `PRAGMA temp_store=2` on every
  connection, same lines. **[verified]** Nothing sets `journal_mode`.

**[verified] `metadata.db` is in SQLite's default rollback-journal mode, not WAL.**
- No `PRAGMA journal_mode` / `WAL` occurrence anywhere in `src/calibre/db/*` or `src/calibre/srv/*`
  (grep over the downloaded files returned nothing).
- Direct measurement on Calibre's own shipped database: `PRAGMA journal_mode` → `delete`,
  `PRAGMA auto_vacuum` → `0`, `PRAGMA user_version` → `27`, `PRAGMA page_size` → `1024`, file magic
  `SQLite format 3`, no `-wal` or `-shm` sidecar committed.

**[inferred]** Because there is no WAL, a writer excludes readers and readers exclude writers at
whole-database granularity. Practical consequences for the feature: (1) a long external write transaction
can make Calibre's reads block and vice versa; (2) the 10 s busy timeout is a hard ceiling — a slow write
elsewhere surfaces as an error, not as a wait; (3) there is no reader/writer concurrency to exploit, so
"do the read while Calibre writes" is not a viable design.

### C.12 Official statements about third-party tools writing directly

I searched the manual (`manual/*.rst`), the codebase, the Launchpad tracker, and MobileRead. Findings,
in descending order of strength:

1. **[verified] The refusal message in `calibredb`** (C.10) is the codebase's own statement:
   *"Having multiple programs that can make changes to a calibre library running at the same time is a
   bad idea."* It is the closest thing to an official position on the subject, and it is about
   *concurrency*, not about external tools as such.
2. **[documented] Kovid Goyal, 2018:** *"There is no method that makes no changes to the database. Simply
   opening a database can make changes to it (schema upgrades happen automatically on database open)."*
   <https://bugs.launchpad.net/calibre/+bug/1772293>
3. **[documented] Kovid Goyal, 2024:** the prescribed answer to "I want to script against a running
   library" is to route through the running content server:
   *"Run the content server in the gui, then have calibredb connect to the server…"*
   <https://www.mobileread.com/forums/showthread.php?p=4414690>
4. **[documented] Kovid Goyal, 2023, on the authority of the DB vs. the OPF:**
   *"OPF files are backups for metadata.db editing will have no effect."*
   <https://bugs.launchpad.net/calibre/+bug/2003338>
5. **[documented] The manual on library-file integrity:** *"**Do not put your calibre library on a
   networked drive**."* (`manual/faq.rst`, section *I am getting errors with my calibre library on a
   networked drive/NAS?*), and the `CALIBRE_OVERRIDE_DATABASE_PATH` note about networked drives that
   "do not support file locking" (`manual/customize.rst`). The manual further documents recovery for
   corruption: *"Your metadata.db file was deleted/corrupted. In this case, you can ask calibre to
   rebuild the metadata.db from its backups"* (`manual/faq.rst`, section *The list of books in calibre is
   blank!*) — and `calibredb restore_database`'s own warning that it *"completely regenerates your
   database"*, losing saved searches, user categories, plugboards, per-book conversion settings and
   custom recipes.
6. **[verified] A real precedent of third-party schema objects breaking Calibre:** the `metax` view case
   (A.4 item 3), where a leftover third-party `VIEW` caused `ALTER TABLE books DROP COLUMN` to fail and
   Calibre 9 to report the database as corrupted.

**What I did *not* find, and want to state plainly:** there is no FAQ entry, manual page, or maintainer
statement that says "third-party tools must not write to `metadata.db`". Anyone citing such a rule should
be asked for the source. The honest summary is: Calibre's own tools are *architected* so that all writes
go through one process (or through the content server), and the one maintainer statement on record about
concurrent modification calls it "a bad idea" — but the prohibition is architectural, not editorial.

### C.13 Are externally inserted rows tolerated, or rebuilt/overwritten?

Split by operation. All **[verified]** from source unless marked.

**Tolerated (survives):**

- Rows in `custom_column_<N>` and `books_custom_column_<N>_link` for a book that Calibre does not
  subsequently modify: yes. Reading is a straight `SELECT` over both tables
  (`ManyToOneTable.read_id_maps()` / `read_maps()`,
  [`db/tables.py#L199-L211`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/tables.py#L199-L211)),
  and `initialize_custom_columns()` never inspects row contents
  ([`db/backend.py#L791-L967`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L791-L967)).
- The `custom_columns` row itself, as long as the physical tables exist and the values satisfy
  `create_custom_column`'s validity rules (lowercase label, `\w`, leading alpha, known datatype).
  **[inferred]** A hand-inserted row that violates those rules is not re-validated on open — only the
  table existence is checked — so it would be tolerated but could behave oddly.

**Rebuilt or removed:**

- A `custom_columns` row whose physical table is missing is **deleted** on next open, with a warning
  (A.1).
- Rows whose `mark_for_delete = 1` are destroyed along with their tables (A.1).
- A rating of `0`: the link row *and* the `ratings` row are deleted on read (`RatingTable.read_id_maps()`,
  [`db/tables.py#L374-L385`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/tables.py#L374-L385)).
- Unreferenced dictionary rows in a normalized column, and orphaned entries in a link table, are
  garbage-collected once Calibre writes that field
  ([`db/write.py#L375-L383`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/write.py#L375-L383)).
- Orphaned links (a link whose `value` has no dictionary row) are actively repaired in memory and
  deleted from the database by `ManyToOneTable.fix_link_table()` /
  `ManyToManyTable.fix_link_table()` ([`db/tables.py#L213-L224`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/tables.py#L213-L224),
  [`#L408-L419`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/tables.py#L408-L419)).
  **[inferred]** This is a *recovery* path, but it is also a trap: a writer that inserts a link row
  pointing at a nonexistent dictionary `value` should expect it to be deleted rather than repaired
  upward. Note also that the FK *triggers* (`fkc_insert_books_custom_column_N_link`) would `RAISE(ABORT)`
  on such an insert **if** the writing connection has `PRAGMA foreign_keys=ON` — a plain
  `sqlite3.connect()` connection does not enable that pragma by default.
- Whole-library rebuild: `calibredb restore_database` regenerates the DB from OPFs and *does* recreate
  custom columns (from OPF `calibre:user_metadata:` entries), reporting conflicts; anything only ever
  written to the DB and never to an OPF is lost (A.4).

**Never rebuilt but stale:** the **`.opf` backup files**. **[verified]** OPF regeneration is driven by
the `metadata_dirtied` table, which only Calibre populates: `Cache.mark_as_dirty()` calls
`backend.dirty_books()` → `INSERT OR IGNORE INTO metadata_dirtied (book) VALUES (?)`
([`db/cache.py#L1906-L1922`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/cache.py#L1906-L1922),
[`db/backend.py#L2603-L2611`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backend.py#L2603-L2611)),
and `MetadataBackup.do_one()` consumes that table every 2 seconds
([`db/backup.py#L28-L110`](https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/src/calibre/db/backup.py#L28-L110)).
**[inferred]** An external SQL writer *can* insert into `metadata_dirtied` to flag the book — the column
is just a book id and the write is `INSERT OR IGNORE`-style-safe — and that would cause the *running*
Calibre to rewrite the OPF from its own (stale) in-memory metadata. That is worse than doing nothing: it
would overwrite the OPF with pre-write values. So the safe direct-SQL write is one that does **not** touch
`metadata_dirtied`, and instead relies on the next Calibre-side edit to that book to refresh the OPF.

### C.14 Realistic failure mode

Separating what is documented from what I inferred:

| Scenario | Outcome | Status |
|---|---|---|
| External write to a book+field Calibre never touches | Persists; Calibre shows it after a library reload, and `calibredb` reads it immediately | **[inferred]** from the per-book keying and the "unchanged value" filters in `one_one_in_other` / `many_one` |
| External write to a field, then that same field edited in the GUI for that book | **Silent loss** of the external value; no error, no prompt, no conflict | **[inferred]** from the same code: the write comes from `book_col_map`, `INSERT OR REPLACE` / `DELETE`+`INSERT` |
| External write, then a bulk metadata edit covering that book | Same silent loss, at selection scale | **[inferred]** |
| External write visible in the GUI right away? | **No.** The GUI/standalone server serves its in-memory `Cache`; only a library switch/reload re-reads the DB | **[inferred]** — `LibraryBroker.loaded_dbs` has no invalidation path other than explicit change/unload (`srv/library_broker.py`) |
| External write concurrent with a Calibre write | One side blocks up to 10 s (`BUSY_TIMEOUT`), then `SQLITE_BUSY`/"database is locked"-style errors. No WAL, so writer/reader overlap is excluded | **[verified]** for the timeout and journal mode; **[inferred]** for the observed error class |
| Corrupted database file? | **Not the expected outcome.** SQLite's rollback journal protects against torn writes; Calibre's own "corrupted" reports in the wild trace to *schema* conflicts (the `metax` view case), not to interleaved writers | **[inferred]** — I found no report of `metadata.db` corruption attributable to a third-party concurrent writer. Note the manual's *"Your metadata.db file was deleted/corrupted"* FAQ text is about rebuilding, not about a mechanism |
| Stale `.opf` backups | Real and quiet: metadata that exists only in the DB is not in the OPF, so `restore_database` cannot recover it | **[verified]** for the `metadata_dirtied` mechanism; **[inferred]** for the recovery consequence |
| Wrong values (rather than lost values) | Very plausible: writing a 0–10 rating where a 0–5 is expected (or vice versa), writing a date in a format `c_parse` cannot read (it falls back to `UNDEFINED_DATE` rather than erroring), or misreading a non-normalized column as if it were a dictionary-and-link column | **[verified]** for each mechanism individually (B.5, A.3.2, A.2) |

**The realistic failure mode is silent, partial, delayed loss of the very data the feature records — not
file corruption.** That distinction matters for how the feature is documented, but it does not make the
failure benign: a user who marks 50 books read and later bulk-edits the rating column loses the read
flags for those books with no indication anything happened.

---

## Implications for the proposed feature

### Which write mechanisms are actually viable

| Mechanism | Viable for this MCP server? | Preconditions |
|---|---|---|
| **`calibredb --with-library http://host:port/#lib`** → content server `/cdb/cmd/set_metadata` or `/cdb/cmd/set_custom` | **Yes — the best option.** Shipped CLI, documented, uses the live in-memory cache so nothing is clobbered, works while Calibre runs, and is exactly what the maintainer prescribes | Calibre installed and on `PATH`, or the MCP server shells out to a known path; a **write-enabled** content-server user (`--username/--password`); `#read_date`/`#read_notes` must already exist (see below); command/`version` must match the server's Calibre |
| **Content server `/cdb/set-fields/{book_id}` directly over HTTP** | Technically works and is simpler than shelling out, but it is an **undocumented internal endpoint** with no `calibredb` subcommand behind it | Same auth; acceptance that the endpoint is not a published API and could change shape between versions without notice |
| **`calibredb` with a local `--library-path`** | **Conditionally viable only when Calibre is not running.** `singleinstance('db')` actively refuses to start when it is | Nobody else has the library open. Combine with the content-server path as a fallback |
| **Direct SQLite writes to `metadata.db`** | **Not safe by default.** Every write is a bet that Calibre will never rewrite that book+field | Calibre not running *and* not started between the write and the next read; see below |
| **Embedding `calibre.db` as a library** | **No.** Not pip-installable; needs `calibre_extensions`, apsw, and Calibre's registered SQL functions | Only if the MCP server runs inside a Calibre install's Python — i.e. it becomes a plugin, not an MCP server |
| **A Calibre plugin** | Best-integrated, but a different product | Users install code into Calibre |

### Can a direct-SQLite write path ever be safe by default?

**No — not in the present architecture, and this is a source-level conclusion, not a preference.**

Three reasons, each independently sufficient:

1. **There is no way for the tool to know whether Calibre holds the library.** The single-instance lock
   is a per-program file lock in the writing process's own `~/.calibre-singleinstance-<euid>-db.lock`
   (`utils/lock.py`); a third-party process cannot reliably take it, and Calibre only ever writes its
   *own* library paths into `prefs`. There is no per-library lock file, no lock table, and
   `metadata.db`'s own file locks are held only for the duration of a transaction, not for a session.
2. **The clobber is silent and indistinguishable from success.** `INSERT OR REPLACE` and
   `DELETE`+`INSERT` from the in-memory cache produce no error, no warning, and no on-disk trace that a
   value was overwritten. The feature could report success and be wrong.
3. **"Calibre is not running" is not a stable precondition** for an MCP server. The user finishes their
   chat, opens Calibre, edits a rating, and the read flags for that selection are gone. The MCP server
   has no way to make that not happen, and no way to notice it afterwards.

So: **the direct-SQLite path can only ever be an explicitly opt-in mode with a documented precondition
("Calibre must not be running against this library, and must not be started before the next Calibre-side
edit to these books")**, and even then it should be secondary. It should not be the default, and it should
not be the only path. If the MCP server has to work with a running Calibre — which is the common case for
a homelab deployment, and certainly the case anyone would demo — the content-server route is the only
option that does not rely on the user remembering a rule.

A defensible design has **one write path per precondition**, chosen at runtime and stated in the tool's
own output:

1. If a content-server URL and write credentials are configured → `calibredb --with-library http://…`
   (or `/cdb/set-fields/`). Works whether or not Calibre is running. **Default.**
2. Else if `calibredb` is available and the library is not locked → local `calibredb --library-path`.
3. Else → refuse to write, and say why. Do not fall back to direct SQL silently.

If a direct-SQL mode is offered at all, it needs: an explicit opt-in flag, a check for evidence that
Calibre is running (for example the presence of a fresh `-journal`/`-wal` sidecar, or an explicit
user-supplied assertion), a documented warning that an open GUI can silently revert the change, and a
statement that the `.opf` backup will be stale.

### Requirements the proposed design is missing

1. **Who creates the custom columns — the design does not say, and it cannot be skipped.**
   `#read`, `#read_date` and `#read_notes` do not exist in a fresh library. Creating them is the one
   operation that **cannot** go through the running content server:
   `cmd_add_custom_column` declares `no_remote = True` and `run_cmd()` raises
   `The add_custom_column command is not supported with remote (server based) libraries`. Locally it is
   also blocked by `singleinstance('db')` while Calibre runs. So:
   - The feature must **detect** the columns (read `custom_columns` by `label`) and either (a) require the
     user to create them out-of-band with `calibredb add_custom_column`, documenting the exact commands,
     or (b) create them itself in a one-off setup step that requires Calibre to be closed.
   - It must handle the columns being **absent at call time** with a clear error, not a crash and not a
     silent no-op. This is not hypothetical: `initialize_custom_columns()` deletes `custom_columns` rows
     whose tables are missing, and a user can delete a column from the GUI at any time.
   - It must handle the columns existing with the **wrong datatype** — the label is only unique, the
     datatype is not enforced against what the feature expects.
   - It must **not** hardcode `custom_columns.id`. The id is an `AUTOINCREMENT` value, the physical table
     name is derived from it, and deletion plus re-creation changes it. Resolve `label → id → table name`
     at runtime, every time. The existing `_load_custom_columns()` already does this correctly, and that
     logic should be shared.
2. **`#read` needs a decision about the third state.** Calibre's boolean columns are tri-state by default
   (`bools_are_tristate`, from the `bool_custom_columns_are_tristate` tweak, default `yes`): a missing row
   means "undefined", which is *not* the same as `false`. `field_from_string` refuses to accept
   `none`/empty for a bool, so clearing a bool through `set_metadata --field` is not possible —
   `set_custom` with `none` is the way (the write adapter maps `none`/`''` → `None` → row deleted). The
   design must say what `#read = false` means and how to express "unknown".
3. **The rating scale and the two different CLI scales must be pinned down in the code.**
   `set_metadata --field rating:5` doubles to 10; `set_custom <ratingcol> <id> 5` stores 5.
   Storage is 0–10 (`CHECK(rating > -1 AND rating < 11)`), and `rating_to_stars` divides by 2. A reader
   that returns "rating" without stating the scale will produce off-by-a-factor-of-two bugs in the LLM
   layer. Also note `rating = 0` is deleted on read, so "0 stars" must be modelled as "no rating".
4. **The date format must be stated, and "no date" must be modelled explicitly.** Stored as
   `YYYY-MM-DD HH:MM:SS+00:00` text in UTC. Not Julian, not `T`-separated, not epoch seconds.
   `field_from_string` requires a timezone-aware ISO string (with a date-only fallback), so
   `--field '#read_date:2026-09-12T20:15:00Z'` is safer than a naive local timestamp. The "undefined"
   sentinel is `datetime(101, 1, 1, UTC)` — an absent row is the better representation of "no finish
   date", and a reader must not surface the year-101 sentinel to the model as a real date.
5. **`CALIBRE_LIBRARY_PATH` + `/metadata.db` is the wrong way to locate the database.** Calibre honours
   `CALIBRE_OVERRIDE_DATABASE_PATH`, and the manual specifically recommends it for libraries on
   filesystems without file locking. Any path resolution added by this feature (and arguably the
   existing read path) should respect that variable, or at minimum document the limitation.
6. **Rating is not currently readable by the MCP server at all.** The book query in
   `src/calibre_mcp_server/calibre_api.py` (`_load_book_data`) joins authors, series, publishers,
   identifiers, languages, comments and tags but **not** `books_ratings_link`/`ratings`. Since the
   feature reuses the built-in `rating` field, the read side needs that join added — and it must
   implement the `rating = 0` → "no rating" rule and the /2 scale.
7. **The existing custom-column reader will report `null` for every non-normalized column, including the
   `#read` and `#read_date` this feature would create.** In `_load_custom_columns()`, a value is only
   assigned if the **link** table `books_custom_column_<id>_link` exists; there is no fallback branch for
   a non-normalized column's `custom_column_<id>.value` (which is keyed by `book`, not `id`).
   `bool`, `datetime` and `comments` columns all have `normalized = 0` and therefore have no link table —
   so a book's `#read`, `#read_date` and `#read_notes` would all come back `None` even after a successful
   write. **[verified]** by reading the code path
   (`src/calibre_mcp_server/calibre_api.py:330-421`). This is a blocking defect for the feature as
   specified: reading the status back is half the feature, and it would silently appear to work while
   returning nothing. The reader must branch on `custom_columns.normalized` (which the current query does
   not even select) and use `WHERE book = ?` for the non-normalized case.
8. **Write-account and network requirements are deployment-visible.** The content-server route needs a
   non-read-only user, credentials passed safely (`--password <stdin>` or `<f:path>` are the documented
   non-argv options), and a reachable URL. The PR should state this, and should not assume the currently
   configured read-only user can write.
9. **A documented, testable definition of "safe" is needed before the PR.** Concretely, the PR should be
   able to answer: under what conditions does this tool write, what does it do when it cannot write
   safely, and what does it tell the user afterwards. "It writes directly to `metadata.db`" answers none
   of those.

---

## Appendix: primary sources consulted

Calibre source (`kovidgoyal/calibre` @ `f472f7c762c7d327e41cc1dacba9db0ba9293de5`; link form
`https://github.com/kovidgoyal/calibre/blob/f472f7c762c7d327e41cc1dacba9db0ba9293de5/<path>`):

- `src/calibre/db/backend.py` — `DB.__init__`, `Connection`, `initialize_custom_columns`, `initialize_tables`, `create_custom_column`, `delete_custom_column`, `set_custom_column_metadata`, `custom_table_names`, `custom_tables`, `dirtied_books`/`dirty_books`, `CUSTOM_DATA_TYPES`
- `src/calibre/db/schema_upgrades.py` — `SchemaUpgrade.__init__`, `upgrade_version_5`, `_9`, `_25`, `_26`
- `src/calibre/db/tables.py` — `Table`, `OneToOneTable`, `ManyToOneTable`, `ManyToManyTable`, `RatingTable`, `c_parse`
- `src/calibre/db/write.py` — `sqlite_datetime`, `adapt_bool`, `adapt_datetime`, `get_adapter`, `one_one_in_books`, `one_one_in_other`, `many_one`, `many_many`, `Writer`
- `src/calibre/db/cache.py` — `Cache` (class docstring, locking, `set_field`, `mark_as_dirty`, `set_metadata`)
- `src/calibre/db/backup.py` — `MetadataBackup`
- `src/calibre/db/restore.py` — `Restore`, `conflicting_custom_cols`
- `src/calibre/db/locking.py` — `create_locks`, `SHLock`
- `src/calibre/db/constants.py`, `src/calibre/db/search.py`
- `src/calibre/db/cli/main.py` — `COMMANDS`, `DBCtx`, `remote_run`, `run_cmd`
- `src/calibre/db/cli/cmd_set_metadata.py`, `cmd_set_custom.py`, `cmd_add_custom_column.py`
- `src/calibre/library/field_metadata.py` — the `rating` field record
- `src/calibre/ebooks/metadata/book/base.py` — `field_from_string`
- `src/calibre/ebooks/metadata/__init__.py` — `rating_to_stars`
- `src/calibre/ebooks/metadata/opf2.py` — `serialize_user_metadata`
- `src/calibre/utils/date.py` — `isoformat`, `parse_date`, `timestampfromdt`
- `src/calibre/utils/iso8601.py` — `UNDEFINED_DATE`
- `src/calibre/utils/lock.py` — `singleinstance`, `create_single_instance_mutex`
- `src/calibre/srv/cdb.py`, `srv/routes.py`, `srv/handler.py`, `srv/library_broker.py`, `srv/books.py`, `srv/content.py`
- `src/calibre/db/tests/metadata.db` — the binary fixture inspected with `sqlite3`

Calibre manual:

- <https://manual.calibre-ebook.com/generated/en/calibredb.html> (`set_metadata`, `set_custom`, `add_custom_column`, `custom_columns`, `remove_custom_column`, `restore_database`, `--library-path`)
- <https://manual.calibre-ebook.com/db_api.html>
- `manual/server.rst` (`https://manual.calibre-ebook.com/server.html`)
- `manual/faq.rst`, `manual/customize.rst`, `manual/metadata.rst`
- `manual/develop.rst`

Tracker and forum (maintainer answers, quoted above):

- <https://bugs.launchpad.net/calibre/+bug/1772293> — Kovid Goyal, 2018-05-21: *"There is no method that makes no changes to the database…"* (Won't Fix)
- <https://bugs.launchpad.net/calibre/+bug/2003338> — Kovid Goyal, 2023-01-19: *"OPF files are backups for metadata.db editing will have no effect."*
- <https://www.mobileread.com/forums/showthread.php?p=4414690> — kovidgoyal, 2024-04-13: *"Run the content server in the gui, then have calibredb connect to the server…"*
- <https://www.mobileread.com/forums/showthread.php?p=4570014> — 2026-02-26, user report of the Calibre 9 `metax` / `ALTER TABLE books DROP COLUMN` conflict (**user** post, not maintainer; used only as corroboration for a schema change I verified in source)

GitHub releases API for the version stamp: <https://api.github.com/repos/kovidgoyal/calibre/releases/latest>
