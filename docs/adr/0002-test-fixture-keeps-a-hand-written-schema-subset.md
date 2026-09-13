# The test fixture keeps a hand-written schema subset

Status: accepted

Tests build a minimal Calibre-like `metadata.db` by hand instead of loading Calibre's real schema. The
subset is kept, and kept deliberately: it is *sufficient* rather than *faithful*. It models the tables
and columns this server's SQL touches, not the schema Calibre ships, because the paths where the two
differ are paths this code does not act on.

## Considered options

- **Extract Calibre's real DDL from a live library into committed `.sql`.** The live target carries 46
  tables, 70 indexes, 15 views and 56 triggers. Four triggers sit on `books`, and two of them call
  `title_sort()` and `uuid4()` — Python UDFs Calibre registers on its own connection, which a plain
  `sqlite3` fixture would have to register too or `add_book()` dies with `no such function`. The server
  never inserts into `books` and never deletes anything: it writes custom-column rows and rating links,
  so **none of those 56 triggers ever fires on a path this code touches**. Fidelity would be bought
  precisely where the code does not act, at the cost of a fixture that only a machine with Calibre can
  regenerate.
- **A drift guard: assert the fixture covers every table and column the server's SQL references.**
  Rejected because it guards presence, and the measured deltas are of a different kind. Both the fixture
  and Calibre expose a `value` column on a custom-column table; the fixture declares it `INTEGER` for a
  bool column where Calibre declares `BOOL`, and declares a `datetime` column `TEXT` where Calibre
  declares `timestamp`. A guard on names passes on every one of those. It would also assert agreement
  between two things that agree by construction, since the fixture was written from the server's own
  queries — so it can confirm the fixture is sufficient, never that it is Calibre's.

## Consequences

- A green suite proves the server works against a schema of Calibre's *shape*. It does not prove it works
  against Calibre's schema, and no test in the repo claims otherwise.
- The accepted structural deltas are known, not accidental. The fixture omits the custom-column table's
  own `id` column, the `NOT NULL` on `value`, the dictionary table's `link` column, its `UNIQUE(value)`
  and `COLLATE NOCASE`, the series link table's `extra REAL`, every index, and every foreign-key
  trigger.
- One delta is behavioural rather than structural. Calibre declares a `datetime` custom column
  `timestamp` (numeric affinity) while the fixture declares it `TEXT`. Measured across all ten of
  Calibre's custom datatypes, every value the server reads back is identical — because Calibre's own
  writer stores a datetime as an ISO string, which stays text under either affinity. A *numeric* value
  in that column would read as `'2460000.5'` from the fixture and `2460000.5` from a real library.
- Three of Calibre's ten custom datatypes — `rating`, `enumeration` and `series` — have no reader test.
  That is a gap in test coverage, not in fixture fidelity, and this decision does not close it.
- The decision stops holding if the server starts inserting into `books`, deleting rows, or writing
  anything else that fires Calibre's triggers. Those are exactly the paths where the subset is thinnest,
  so revisit this ADR rather than extending the fixture case by case.
