# Prior art: how other Calibre MCP servers write metadata

Research question: `ajtudela/calibre_mcp_server` is read-only — it opens `metadata.db` with
plain `sqlite3.connect()` and only ever `SELECT`s. A feature is proposed to **write** book
metadata back into Calibre ("mark a book as read", plus optional finish date, rating, note).
Two other Calibre MCP servers already implement read/write and their READMEs make strong
safety claims. This document verifies those claims against the actual source code and extracts
the concrete implementation pattern.

## Method and scope

- Every claim below is cited as `repo / path / symbol / line`. Line numbers refer to the
  shallow-cloned commits recorded in [Appendix: revision pins](#appendix-revision-pins).
- **Verified in source** and **claimed in README/docs but not found in the code** are marked
  explicitly. Where a README claim is not backed by code, that is reported as a finding.
- No project code was modified. Clones live under
  `.research-tmp/clones/` (gitignored scratch space, not part of the deliverable).
- Scope: two deep dives (`caelum29/calibre-mcp`, `FaceDeer/calibre_full_mcp_server`) plus a
  twelve-repo scan of write handling.

### Headline result

**The scan found one direct-SQLite writer out of twelve projects: `Xpresi/calibre-mcp`.** It is
not an accident or a legacy corner — direct SQLite is its primary metadata-write path, and it
ships a substantial safety apparatus (Calibre-closed process check, WAL, Calibre's trigger UDFs,
fail-closed pre-write backup, dry-run default) to make that work. Its own changelog is a
catalogue of data-loss incidents along the way.

The other eleven projects, including both maintained read/write servers, write through Calibre's
own interfaces: the `calibredb` CLI, Calibre's Python API via `calibre-debug`, or nothing at all.

---

## Target 1 — `caelum29/calibre-mcp` (TypeScript, Node)

**Revision:** `e58db358d7df2ddbcd2087df6d51239f526e838c` (v0.7.4, 2026-08-21). ~25.3k lines of
TypeScript under `src/` and `test/`.

### 1.1 README claim scorecard

| README claim | Verdict |
|---|---|
| "Safe by default — read-only unless you explicitly enable writes" (README:40) | **Verified.** Two independent gates, see §1.4. |
| "destructive operations preview first and require confirmation" (README:40–41) | **Verified, with a caveat.** Preview/confirm is an in-band boolean parameter, not a token protocol, and it is *not* applied to every write — see §1.5. |
| "all writes route through the Content Server so they never race the Calibre GUI" (README:41–42) | **Substantially true, but imprecise.** Writes do go to the Content Server, but the MCP server never calls a Content Server *HTTP endpoint* to write. It shells out to the `calibredb` CLI pointed at the server URL, and `calibredb` speaks the server protocol on its behalf. See §1.2. |
| "Calibre with the Content Server running" is a hard requirement (README:46–47) | **Verified.** `ContentServerClient.resolveLibraryId` throws if the server reports no libraries (`src/calibre/content-server.ts:145–148`), and connect failures raise `CalibreHttpError` (`src/calibre/http.ts:39–47`). |
| "Tested against Calibre 9.x" (README:47) | **Claimed, not verifiable from source.** No version assertion exists anywhere in the code — `src/calibre/discover.ts` locates the `calibredb` binary but performs no version check. Treated as a tested-against statement, not an enforced precondition. |

### 1.2 Which Content Server endpoints does it call for writes?

**None.** This is the single most important correction to the README framing.

The write path is: **MCP tool → `calibredb` subprocess (argv array) → `--with-library
<serverUrl>/#<libId>` → Content Server.** No HTTP write request is constructed anywhere in
the codebase.

- `src/calibre/client.ts:79–85` — `CalibreClient.libraryUrl()` builds the `--with-library`
  value: `` `${this.cfg.serverUrl}/#${encodeURIComponent(lib)}` `` (e.g.
  `http://localhost:8080/#Programming_Books`). The comment states the intent: *"The
  `--with-library` value that routes calibredb through the live server."*
- `src/calibre/client.ts:92–128` — `CalibreClient.calibredb()` prepends
  `["--with-library", this.libraryUrl(opts.library), ...args]` and runs it via `spawnCollect`.
- `src/calibre/metadata-fields.ts:66–72` — `buildSetMetadataArgs(id, changes)` produces the
  argv tail: `["set_metadata", "<id>", "--field", "name:value", ...]`. One `--field` pair per
  changed field. Values are formatted per field type by `formatFieldValue()`
  (`metadata-fields.ts:38–63`): `identifiers` → `scheme:value,scheme:value`; `authors` →
  joined with ` & `; `tags`/`languages` → comma-joined; scalars → `String(value)`.
- `src/tools/calibre_update_book.ts:78–80` — the call site:
  `deps.calibre.calibredb(buildSetMetadataArgs(numericId, changes), { library: libId })`.
- `src/tools/calibre_remove_book.ts:75` — `calibredb(["remove", numericIds.join(",")], ...)`.

So the request payload shape is not JSON at all — it is a **CLI argv array**, deliberately
never a shell string (`src/calibre/client.ts:1–3`: *"All invocations use execFile with an argv
array (never a shell string) to defeat command injection"*). Note `set_metadata` splits each
`--field` token on the **first** colon only, which is why values containing colons are safe
(`metadata-fields.ts:33–37`).

**Read** paths, by contrast, *are* direct HTTP, in `src/calibre/content-server.ts`:

| Method | Endpoint | Purpose | Symbol / line |
|---|---|---|---|
| GET | `/ajax/library-info` | library map + default | `libraryInfo` :126 |
| GET | `/ajax/search/{libId}?query&num&offset&sort&sort_order` | search → ids | `search` :161 |
| GET | `/ajax/book/{id}/{libId}` | full book | `getBook` :183 |
| GET | `/ajax/books/{libId}?ids=1,2,3` | batched books | `booksByIds` :193 |
| GET | `/ajax/categories/{libId}` | category list | `categories` :282 |
| GET | `/ajax/category/{hex}/{libId}` | category values | `categoryItemsByUrl` :296 |
| GET | `/interface-data/init?library_id={libId}` | virtual libraries | `virtualLibraries` :267 |
| GET | `/get/thumb/{id}/{libId}?sz=WxH` | cover thumbnail | `coverThumb` :245 |

**Finding.** The README's "all writes route through the Content Server" is the right *effect*
(the Content Server is what actually mutates the database) but the wrong *mechanism*
(a `calibredb` subprocess, not an HTTP write client). To send the request directly you would
need an HTTP write client — and the project's own internal design note reserves exactly that
for later: `CLAUDE.md` states *"a direct `/cdb/set-fields` HTTP client is a LATER opt"*. That
endpoint is referenced in the repo's internal docs only; **no `/cdb/...` path appears anywhere
in the shipped source** (`grep -r 'cdb/' src/` → no matches). Treat `/cdb/cmd/set-fields` as
an internal design note, not as verified behaviour of this project.

### 1.3 How does it authenticate to the Content Server?

**It doesn't.** There is no API key, password, token, or session handling anywhere.

- `src/calibre/http.ts:23–51` — `getJson()` calls bare `fetch(url, { signal })`. No headers
  other than those `fetch` sets itself; there is no auth-header construction in the file.
- `src/config.ts:93–110` — `loadConfig()` reads **no** credential of any kind. The full
  environment surface (README:317–340) is `CALIBRE_MCP_SERVER_URL`, `CALIBRE_MCP_LIBRARY`,
  `CALIBRE_MCP_ENABLE_WRITE`, `CALIBRE_MCP_CALIBREDB_PATH`, `CALIBRE_MCP_INDEX_DIR`,
  `CALIBRE_MCP_SEMANTIC_FLOOR`, `CALIBRE_MCP_RERANK`, `CALIBRE_MCP_MAX_BOOK_BYTES`,
  `CALIBRE_MCP_ADD_ROOTS`, `CALIBRE_MCP_BOARD_STYLE`. None is a credential.

Writes therefore depend on the **server** being configured to permit unauthenticated local
writes — Calibre's `--enable-local-write`, or the GUI's *Preferences → Sharing over the
net → Advanced → "Allow un-authenticated local connections to make changes to the library"*
(README:173–190). The README is explicit that **the GUI-embedded Content Server is read-only
by default** (README:175–176), which is why there is a second gate to satisfy.

The failure mode is classified rather than guessed:
`src/tools/write-refusal.ts:7–18` — `isWriteRefused()` tests stderr against
`/forbidden|unauthorized|\b401\b|\b403\b/i`, and `WRITE_REFUSED_MESSAGE` tells the user to
restart the server with `--enable-local-write` *"or configure an authenticated non-restricted
user."* That second option is advice for the **server's** configuration; this MCP server
provides no way to supply those credentials.

### 1.4 Exactly how is the write gate implemented?

**Two-key, and both keys are independent:**

**Key 1 — MCP-side, default off.** `src/config.ts:99`:
```ts
writeEnabled: truthy(env.CALIBRE_MCP_ENABLE_WRITE),
```
`truthy` (`config.ts:52–54`) accepts only `"1" | "true" | "yes"` — anything else, including
unset, is `false`. Enforced in `src/server.ts:139–141`:
```ts
if (t.write && !config.writeEnabled) reg.disable();
```
`reg.disable()` **unregisters** the tool — the README's claim that write tools "aren't even
registered" (README:172–173) is accurate. The `write: true` marker is declared per tool:
`calibre_update_book.ts:51`, `calibre_bulk_update.ts:58`, `calibre_add_book.ts:41`,
`calibre_remove_book.ts:36`, `calibre_merge_books.ts:78`, `calibre_manage_bundles.ts:156`,
`calibre_extract_isbn.ts:38`. `src/tools/registry.ts:56–67` asserts at registration time that
every tool with `readOnlyHint: false` carries either `write` or `localWrite`, so a new write
tool cannot be added without declaring its gate class.

Two consequences worth noting:
- The gate is **per tool, not per action**. README:168–171 admits this: it disables
  `calibre_manage_bundles` wholesale, including that tool's read-only `list` action.
- `reg.disable()` hides the tool from the model entirely, so an agent cannot discover a write
  tool while the gate is off.

**Key 2 — Calibre-side, default off.** The Content Server must also allow the write. This is
not code in this repo; it is the precondition described in §1.3. The README is blunt that
*"With only the first switch on, write tools appear but Calibre refuses the write"*
(README:190–191).

Tool `annotations` are set honestly as a third layer of signalling to the client:
`calibre_update_book.ts:50` `{ readOnlyHint: false, destructiveHint: false, idempotentHint: true }`
vs `calibre_remove_book.ts:35` `{ readOnlyHint: false, destructiveHint: true, idempotentHint: true }`.

### 1.5 How does the preview-then-confirm flow work? Is there a two-call protocol?

**It is a two-call protocol, but the second call is not authorised by a token — it carries an
in-band boolean.** There is no preview id, no plan hash, no server-side state, and no
expiry.

Two distinct parameter styles implement the same idea:

- **`confirm=true` for destructive tools** (default *false* → dry run):
  `calibre_remove_book.ts:26` `confirm: CoercedBool().default(false)`;
  the gate at `:56` — `if (!args.confirm) { ... return toolOk(...) }` returns a list of what
  *would* be removed and writes nothing. Same shape in `calibre_merge_books.ts:60,143` and
  `calibre_manage_bundles.ts:136,194,238`.
- **`preview=true` for bulk writes** (default *true* → dry run):
  `calibre_bulk_update.ts:40` `preview: CoercedBool().default(true)`, gate at `:110`;
  the diff is computed by `previewBookChanges()` (`src/calibre/metadata-fields.ts:127–135`),
  which reads current values and compares structurally, writing nothing.

**The explicit design decision that there is no token** is documented in the source itself —
`src/tools/calibre_merge_books.ts:164`:
> `/** Render the dry-run plan (this IS the preview — no plan token; confirm recomputes). */`

That has a real consequence: because `confirm` re-derives the plan from a **fresh read**
(`calibre_merge_books.ts:91`: *"Fresh reads every call: the confirm run re-verifies the sources
still exist"*), the plan approved by the user is not provably the plan executed. There is no
TOCTOU guarantee. The source treats this as acceptable for a local single-user library; a
stricter design would mint an opaque id — and at least one surveyed project does exactly that
(§3.2, `gustavofsousa`).

Two further details of the implementation worth copying:

- **The dry run is a success result, not an error.** `calibre_remove_book.ts:54–55` explains
  why: *"Success result, not isError — the gate worked as designed, and an error result makes
  agents refuse the confirm step."*
- **Confirm is not required for the non-destructive write.** `calibre_update_book` has no
  `confirm` parameter at all — it writes on the first call (`calibre_update_book.ts:32–51`),
  justified by `idempotentHint: true` and a reported before/after diff. So "destructive
  operations preview first" is precisely scoped: it applies to *remove*, *merge*, *bulk*, and
  *bundle* mutations, **not** to single-book metadata updates.

### 1.6 What happens when the Content Server is not running?

**It fails loudly. There is no degradation to read-only and no silent skip of writes.**

- Reads: `getJson()` converts any transport failure into
  `CalibreHttpError(0, url, "Cannot reach Calibre Content Server")` (`http.ts:36–47`). Nothing
  swallows it into an empty result. (The one exception is the cover thumbnail, which is
  explicitly best-effort: `content-server.ts:239–258` returns `null` on any failure by design.)
- Writes: `calibredb --with-library <dead-url>` exits non-zero; `CalibreClient.calibredb`
  raises `CalibreCliError` carrying both streams for classification
  (`client.ts:121–126`), and the tool handler returns `toolError(...)`.
- Library resolution with no reachable server throws an actionable error rather than silently
  picking a library (`content-server.ts:145–148`).
- The README documents the expectation: *"if the Content Server isn't reachable it logs an
  actionable hint to stderr"* (README:145–146), and the troubleshooting section lists
  "connection refused" as a named symptom (README:343–346).

Degrading to read-only would be a defensible design, but it is **not** what this project does.

### 1.7 Does it ever write to `metadata.db` directly via SQLite?

**No. Never, under any condition.**

- `grep -rn 'metadata\.db' src/` → no matches.
- SQLite appears only as `node:sqlite` for the project's **own semantic vector index**, a
  separate file under `indexDir` — `src/semantic/store.ts:1–12,833`. That database is not
  Calibre's and is never a library file.
- All library mutation goes through `calibredb` (subprocess) or the Content Server (reads).

This is a deliberate stance with a reproduced failure behind it — `CLAUDE.md` records:
> *"**GUI-concurrency lock is real (reproduced).** With the app open, direct
> `calibredb`/SQLite/DB-API access is refused or dangerous. Safe live paths: Content Server
> HTTP (reads) or `calibredb` routed *through* the server URL. Treat the DB as **read-mostly**;
> never race the GUI on writes."*

### 1.8 How does it create custom columns?

**It cannot create them.** It can *read* and *write* existing custom columns, and creating one
is left entirely to the user in the Calibre GUI.

- `src/calibre/metadata-fields.ts:28–31` — `isAllowedField(key)` returns true for a known
  built-in or **any** key starting with `#`. There is no schema lookup, so the allowlist is a
  *shape* check, not a knowledge of which columns exist.
- `grep -rni 'add_custom_column|create_custom|create.*column' src/` → **no matches**. No tool
  creates a column.
- Consequence: `calibre_update_book` will happily build
  `--field #mycol:value` for a column that does not exist; the failure surfaces from
  `calibredb`, not from the MCP server.
- Reading custom columns is real but partial: `ContentServerClient.bookMergeFacts()`
  (`content-server.ts:207–232`) extracts `user_metadata` entries whose label starts with `#`,
  but the domain `Book` type does not carry them, so `bookFieldValue()`
  (`metadata-fields.ts:78–93`) returns `undefined` for any `#` field. The code is explicit
  about the resulting limitation (`metadata-fields.ts:99–100`): *"Custom #columns aren't
  carried on Book → unverifiable → false, so callers stay cautious rather than claim
  success."*

**Finding for the proposed feature.** If "mark as read" is modelled as a custom column, this
project's precedent is that **the human creates the column in Calibre first**; the MCP server
only ever writes into a column that already exists.

### 1.9 Two implementation details worth stealing regardless

- **Never report a committed write as failed.** `calibre_update_book.ts:83–89,141–164` —
  because a routed write commits *server-side before* `calibredb` replies, a client-side
  timeout is ambiguous. The handler re-reads the book and, if `changesSatisfied()` confirms the
  new values, reports **success**; if the re-read itself fails it still reports success with
  an "intended values" diff. Stated as an invariant in `CLAUDE.md`: *"Never report a committed
  write as failed."*
- **Kill the whole process group on timeout.** `src/calibre/spawn.ts:1–9,51–126` — `calibredb`
  routed through the server spawns a conversion/import worker as a *grandchild* that inherits
  the stdio pipes. Node's built-in `execFile` timeout kills only the direct child, so the
  promise never settles and the orphan keeps the library write lock. The fix is
  `spawn(bin, args, { detached: true })` plus `process.kill(-pid, 'SIGKILL')` (with `taskkill
  /T /F` on Windows). This is a real, hard-won concurrency mitigation and it is the only such
  mechanism in either deep-dive project.

---

## Target 2 — `FaceDeer/calibre_full_mcp_server` (Python)

**Revision:** `f46192bf7f87ef34b36124877220e403fd452eeb` ("uv support (#2)", 2026-03-05).
~2.6k lines of Python under `src/` (748 of which are `worker.py`).

### 2.1 README claim scorecard

| README claim | Verdict |
|---|---|
| "Granular Permissions: Define strict access controls per library, including read-only modes and field-level write restrictions" (README:17) | **Verified.** Per-library `permissions.write` accepts `true` / `false` / a field allowlist; checked at every write entry point. See §2.4. |
| "Must be installed on the host system. This server utilizes `calibre-debug` to execute worker processes." (README:23) | **Verified.** `cmd = ["calibre-debug", worker_path, lib_path]`. See §2.2. |
| Concurrency warning: do not point an agent at a library in use by the desktop app; `worker_timeout` "can reduce the risk … but don't rely on that" (README:25) | **Verified, and unusually honest.** The code implements only idle-process reaping; there is no lock file, PID check, or preflight. See §2.5. |

### 2.2 How does the `calibre-debug` worker mechanism work, and why?

**Command.** `src/worker_pool.py:56–96` — `WorkerPool.get_worker()` resolves
`worker_path = <this file's dir>/worker.py` and launches:
```python
cmd = ["calibre-debug", worker_path, lib_path]
proc = subprocess.Popen(
    cmd, stdin=PIPE, stdout=PIPE, stderr=log_file,
    text=True, bufsize=1, encoding="utf-8",
)
```
The library path is passed as **argv[1]** and read back at `worker.py:232–236`. `stderr` is
redirected to a log file (a temp file by default, or `logs/worker_<lib>_stderr.log` when
`enable_worker_logging` is on — `worker_pool.py:61–85`). One worker process **per library**,
kept alive between requests (`self.workers` is keyed by library name, `worker_pool.py:13,38`).

**IPC protocol: newline-delimited JSON-RPC 2.0 over stdin/stdout.**

- Request (`worker_pool.py:171–181`):
  `{"jsonrpc": "2.0", "method": "<name>", "params": {...}, "id": <int>}` written as one line
  plus `"\n"`, then `flush()`.
- Response (`worker.py:717–728`):
  `{"jsonrpc": "2.0", "id": <int>, "result": ...}` or
  `{"jsonrpc": "2.0", "id": <int>, "error": {"code": -32603, "message": "..."}}`, printed to
  stdout and flushed.
- Readiness handshake: the worker prints `{"status": "ready", "library": <path>}` **to stderr**
  after opening the database (`worker.py:250–252`). The parent does not block on it.
- The parent tolerates noise on the wire: it loops reading lines and skips any that is not
  valid JSON or lacks a `jsonrpc` key (`worker_pool.py:183–213`), logging them at debug level.
  Serialization uses `JsonSafeEncoder` (`worker.py:53–70`) to coerce datetimes to ISO strings,
  sets/frozensets to lists, and bytes to decoded text.
- Failure handling: a terminated worker raises `RuntimeError("Worker process terminated
  unexpectedly: <error>")`, with the error text scraped from the last 50 lines of the stderr
  log by `_extract_stderr_error()` (`worker_pool.py:111–159`). `BrokenPipeError` evicts the
  worker from the pool so the next call respawns it (`worker_pool.py:221–228`).

**Why a worker instead of importing Calibre directly?** The rationale is documented in
`doc/Architecture.md:5–25` — *"The Challenge: Environment Isolation"*:

> "Calibre is built on a highly customized Python environment. On Windows, it ships with a
> bundled Python … Custom C/C++ extensions for performance (Qt, lxml, etc.). A sandboxed
> structure that makes installing standard PyPI packages difficult. Incompatibility with binary
> wheels compiled for standard Python distributions (e.g., `pydantic-core` required by the
> `mcp` SDK). Attempts to run the MCP server directly inside Calibre's environment usually fail
> due to dependency mismatches (specifically `glibc` or ABI issues with `pydantic`)."

So the split is: **MCP protocol, config and permissions run on system Python** (where `mcp`,
`pydantic` install cleanly); **all Calibre API access runs inside Calibre's own interpreter**
launched via `calibre-debug`, which is the officially supported way to run a script in that
interpreter. The worker is stdlib-only by design (`doc/Architecture.md:39–44`).

This is the key architectural difference from `caelum29`: FaceDeer uses Calibre's **Python API
in-process**, caelum29 uses Calibre's **CLI against the Content Server**. Both avoid SQLite.

### 2.3 What Calibre Python API does the worker call to write metadata?

**Imports** (`worker.py:10–19`):
```python
from calibre.library import db
from calibre.ebooks.metadata.book.base import Metadata
from calibre.ebooks.metadata.meta import get_metadata
from calibre.ebooks.conversion.plumber import Plumber
from calibre.utils.logging import Log
```
Guarded by `try/except ImportError` → `None`, with a graceful error at `main()` if the script
was not run under `calibre-debug` (`worker.py:16–19, 226–229`).

**Database handle** (`worker.py:242–248`):
```python
database = db(library_path)          # calibre.library.db(library_path) -> LibraryDatabase
if hasattr(database, 'new_api'):
    database = database.new_api      # -> the Cache object (calibre.db.cache.Cache)
```
So the worker deliberately climbs to `new_api`, the modern `Cache` API, and every subsequent
call is on `Cache`. Note the `if hasattr(...)` fallback: on a hypothetical version without
`new_api` it stays on the older `LibraryDatabase` object.

**The single write primitive is `Cache.set_metadata(book_id, mi)`.** Every metadata mutation
builds a `Metadata` object and commits it:

| Operation | Symbol | Line | API calls |
|---|---|---|---|
| Single-book update | `main()` branch `"update_book"` | 630–645 | `database.get_metadata(book_id)` → mutate `mi` → **`database.set_metadata(book_id, mi)`** |
| Bulk field update | `main()` branch `"bulk_update_metadata"` | 498–628 | per book: `get_metadata` → mutate → **`set_metadata(book_id, mi)`** |
| Add books | `"add_book"` | 387–418 | `database.add_books(books_to_add)` → `(ids, _)` |
| Delete book / formats | `"delete_book"` | 480–496 | `database.remove_formats({id: [fmts]})` or `database.remove_books([book_id], permanent=True)` |
| Format conversion | `_ensure_format()` | 90–142 | `database.copy_format_to`, `Plumber(...).run()`, `database.add_format(..., replace=True)` |

The mutation of the `Metadata` object before the commit is where the field semantics live
(`worker.py:636–644`):
```python
mi = database.get_metadata(book_id)
for key, value in changes.items():
    if key.startswith("#"):
        if key in database.field_metadata.custom_field_keys():
            mi.set_user_metadata(key, value)      # custom column
    elif hasattr(mi, key):
        setattr(mi, key, value)                   # built-in field
database.set_metadata(book_id, mi)
```
and the equivalent in the bulk path (`worker.py:609–617`) with an extra special case:
```python
if is_custom:
    mi.set_user_metadata(field_name, final_val)
elif field_name == "identifiers":
    mi.set_identifiers(final_val)
else:
    setattr(mi, field_name, final_val)
database.set_metadata(book_id, mi)
```

**Answering the question directly:** `calibre.db.Cache` **is** the class used — reached via
`calibre.library.db(path).new_api` — and `set_metadata` **is** the commit call. There is **no
`WriteBackend`**, no raw `Cache.backend` manipulation, and no `calibredb` internals: the
worker uses the public `Cache` façade, which internally dispatches to the write backend.
`grep -rn 'calibredb' src/` → **no matches**.

Readers, for completeness: `database.search_getting_ids` (`worker.py:278`), `.search` (:282),
`.get_metadata` (:292), `.field_for` (:337), `.field_metadata.all_field_keys()` (:333),
`.formats(book_id)` (:299), `.has_format` (:103), `.format_abspath` (:138),
`.search_getting_ids('')` for all ids (:507), and an undocumented `database.fts_search(...)`
whose parameters the author reports finding by reading Calibre's source
(`worker.py:684`: *"This Calibre API is not documented. I found the parameters by inspecting
the source code."*).

**Two behaviours in this path are worth flagging as weaknesses, not patterns to copy:**
- **Unknown fields are silently ignored.** In `update_book`, a key that is neither `#`-prefixed
  nor an attribute of `Metadata` falls through both branches with no else-clause — nothing is
  written and no error is raised (`worker.py:637–644`). Same for a `#` column that fails the
  `custom_field_keys()` test. The caller gets `{"status": "success", "changes": [...the
  requested keys...]}` (`:645`) even when some of them did nothing. Contrast caelum29, which
  validates against `isAllowedField()` and returns an explicit "Unknown field(s)" error
  (`calibre_update_book.ts:58–64`).
- **`bulk_update_metadata` defaults to ALL books.** `worker.py:504–512`: if `book_ids` is
  falsy it substitutes every id in the library via `search_getting_ids('')`. A missing
  parameter means a library-wide mutation. caelum29 explicitly calls this out and refuses it —
  `calibre_bulk_update.ts:75–80`: *"A set is mandatory — refuse an unbounded all-books write
  (the FaceDeer default we fix)."*

### 2.4 How are field-level write permissions enforced, and what is the default?

**Enforcement lives in `src/logic/permissions.py`, called from the logic layer — never from
the worker.** The worker has no permission awareness at all; it trusts the parent. This is a
sound boundary: the sandboxed side holds no policy.

- `check_write_permission(lib_conf, changes_keys=None)` — `permissions.py:19–50`.
  - `write_perm = lib_conf.get("permissions", {}).get("write")`
  - `if not write_perm: raise PermissionError(f"Write access denied for library '{lib_name}'.")`
  - If `write_perm` is a **list**, it computes `denied = set(changes_keys) - set(write_perm)`
    and raises naming the denied fields and the allowed set. So a list is a per-field
    allowlist, checked *before* any RPC is sent.
- `check_write_permission_single_field(lib_conf, field_name)` — `permissions.py:53–78`, the
  bulk-update variant: if `write_perm` is a list, raises unless `field_name in write_perm`.
- `check_read_permission(lib_conf, field_name=None)` — `permissions.py:81–101`, the read-side
  analogue (a list restricts readable fields).

**Call sites (only three, all in the logic layer):**
- `src/logic/metadata_ops.py:222–223` — `_update_book_impl`: `check_write_permission(lib_conf, changes_keys=changes.keys())` then `worker_pool.send_rpc(library_name, "update_book", ...)`.
- `src/logic/metadata_ops.py:252–253` — `_bulk_update_metadata_impl`: `check_write_permission_single_field(lib_conf, field_name)`.
- `src/logic/metadata_ops.py:282–283` — `_get_field_values_impl`: `check_read_permission(...)`.

Separate coarse permissions gate the other mutating tools: `has_delete` and `has_convert`
(`src/server.py:76,78`) conditionally register `delete_book` (`server.py:283`) and
`convert_book`; `has_write` conditions `update_book` (`server.py:253`) and
`bulk_update_metadata` (`server.py:265`).

**Default when `permissions.write` is absent: DENY.** `perms.get("write")` returns `None`,
`not None` is true, so it raises `PermissionError`. The README's "read-only modes" claim holds.
The built-in fallback config is also deny-by-write — `src/config_manager.py:17–26`, used only
when no `config.json` exists at all:
```python
"permissions": {"read": True, "write": False}
```
and the shipped sample `config.json` uses an explicit field list for write, e.g.
`["title","authors","languages","tags","series","series_index","comments","rating","pubdate","publisher","identifiers"]`.

**One caveat about where the gate is applied.** `has_write = any(l["permissions"].get("write")
for l in libraries)` (`server.py:78`) is a **global OR across all libraries**. In a
multi-library config, if *any one* library permits writes, the `update_book` and
`bulk_update_metadata` tools are registered for the whole server; the per-library check then
rejects calls against read-only libraries at request time. The README's "per library"
framing is accurate for enforcement but not for tool visibility.

**Also note:** there is a field-level *validation* step distinct from permission —
`_validate_and_normalize_changes()` coerce values against the live library schema obtained from
the worker (`metadata_ops.py:225–231`, schema via `get_library_schema` → `worker.py:356–385`).
Permission is checked first, on the raw change keys; validation second.

### 2.5 What role does `worker_timeout` play, and is there any other concurrency protection?

**`worker_timeout` is an idle-exit timer for the worker process. It is not a request timeout
and it is not a lock.**

- Implementation: `WorkerPool._cleanup_workers()` (`worker_pool.py:235–271`), a daemon thread
  polling every 5 s. For each worker it skips any with `active_requests > 0` (`:248–249`),
  resolves the threshold per-library then falling back to the root setting (`:252–258`), and:
  ```python
  if not timeout or timeout <= 0:
      continue                      # "Default: never expire if timeout is missing, 0, or null"
  if time_idle > timeout:
      proc.terminate()
  ```
- The active-request guard means a long-running request is never killed mid-flight — so
  `worker_timeout` does **not** bound how long a write may hold the library open.
- The default is **off** (never expire). README:93 states this explicitly: *"If this is not set
  then processes are kept alive as long as the server is up."* The shipped `config.json` sets
  `"worker_timeout": 300`.

**Why it touches the concurrency risk at all:** the entire design keeps a long-lived
`Cache` object open against the library for as long as the process lives. Two effects follow.
(a) The worker itself *is* a concurrent opener of the library from Calibre's point of view, so
pointing it at a library the desktop GUI has open is exactly the unsafe case the README warns
about. (b) A shorter `worker_timeout` reduces the *window* during which that handle exists and
therefore reduces the chance of overlapping with a GUI session the user starts later — which is
precisely the limited, hedged claim the README makes: *"Setting a `worker_timeout` can reduce
the risk of this happening accidentally, but don't rely on that to protect your libraries."*
The code supports the mechanism and the hedge; the claim holds.

**Other protections: none for cross-process concurrency.** Verified by grep across `src/`,
`README.md`, `config.json` and `doc/`:
- No lock file, no `flock`/`LOCK_EX`, no PID file, no preflight check that the library is in
  use, no `metadata.db` mtime/marker inspection.
- The only `lock` in the codebase is `self.lock = threading.Lock()` (`worker_pool.py:16`),
  which guards the in-process `workers` dict and request-id counter. It is **intra-process
  only** and does nothing about another process (the GUI) touching the same library.
- Nothing checks whether the desktop app is running before opening the library.

So the concurrency story is **documentation plus an optional idle timer** — there is no
enforcement. The README is honest about this rather than overclaiming, which is worth noting as
a positive finding. For contrast, the one surveyed project that *does* write SQLite directly
implements exactly the process check FaceDeer lacks (§3.2, `Xpresi`).

One related gap: `worker.py` writes to `sys.stdout` for the JSON-RPC channel and redirects
`Plumber` output to stderr only inside `_ensure_format` (`worker.py:122–124`, *"redirecting
stdout to stderr to avoid polluting the JSON-RPC channel"*). Any other Calibre library code
that prints to stdout — e.g. that undocumented `fts_search` — would corrupt the protocol
stream. The parent's tolerant line-skipping parser (`worker_pool.py:205–213`) is the mitigation.

### 2.6 Does it ever write to `metadata.db` directly via SQLite?

**No. Never.** `grep -rni 'sqlite|metadata\.db|\.execute\(' src/` → **zero matches** across the
entire Python source. There is no `import sqlite3`, no SQL string anywhere, and no direct
file-level database manipulation.

All database access is through `calibre.library.db(...).new_api`, i.e. Calibre's own `Cache`,
which is the supported route and which handles Calibre's write backend, transactions, and
triggers for you.

**Finding — a doc/code drift worth recording.** `doc/Architecture.md:41` claims the worker
*"Imports `calibre.library.db.cache` to access `metadata.db` safely."* The actual import
(`worker.py:11`) is `from calibre.library import db`, and there is no `Cache` import anywhere.
The claim is directionally right (it does end up on the `Cache` object via `.new_api`) and the
"safely" is borne out by the absence of SQL — but the stated import path is wrong. Cite the
code, not the architecture doc.

### 2.7 How does it handle custom columns?

**Writing: yes, into existing columns only. Creation: no.**

- Write path requires the column to already exist — `worker.py:638–640`:
  ```python
  if key.startswith("#"):
      if key in database.field_metadata.custom_field_keys():
          mi.set_user_metadata(key, value)
  ```
  If the `#column` is not in `custom_field_keys()`, the write is **silently skipped** and the
  caller still receives `status: success` naming that key (see §2.3).
- Values are set via `Metadata.set_user_metadata(key, value)` on the object returned by
  `Cache.get_metadata(book_id)`, then committed by `Cache.set_metadata`.
- Creation: **no.** `grep -rni 'create_custom|add_custom_column|create_field|new_custom' src/`
  → no matches. No tool, no RPC method, no worker branch creates a custom column. The README
  tells the user to do it themselves (README:139): *"Custom Fields: If you use custom columns
  in Calibre, you must include the `#` prefix (e.g., `#my_custom_field`)."*
- Schema discovery is real and exposed to the model: `get_library_schema` (`worker.py:356–385`)
  emits per field a `name`, `datatype`, a `description` (Calibre's own, for custom columns, or
  a built-in table `STANDARD_DESCRIPTIONS` at `worker.py:21–48`), a `separator` for multi-value
  text columns, and `allowed_values` for enumerations. README:143 recommends putting guidance
  in the Calibre column description so the agent reads it: *"Use these in Calibre to give the
  agent hints on how to use specific custom columns."* This is a genuinely nice pattern for the
  proposed feature — a note-style or enumerated `#read_status` column could carry its own
  usage instructions.

---

## Target 3 — Scan: how twelve other Calibre MCP servers handle writes

The key question: **does ANY of them write to `metadata.db` directly with SQLite, and if so,
how does it justify the safety of doing so?**

### Answer: yes — exactly one of the twelve, and it is well documented

**`Xpresi/calibre-mcp` writes to `metadata.db` directly with SQLite, and direct SQLite is its
*primary* metadata-write path, not an edge case.** It justifies this with five specific
mechanisms: a Calibre-closed process check, WAL + foreign keys, registration of Calibre's own
trigger UDFs, a fail-closed pre-write backup, and dry-run-by-default. §3.3 below quotes each.

The other eleven do not. Two of them open `metadata.db` and are strictly read-only; three use
`calibredb`, one uses Calibre's Python API, two are read-only or HTTP-read-only, and the
remainder are read-only CLI wrappers. **Nobody in the survey uses the Content Server HTTP write
API.**

### 3.1 Classification table

| Repo | Write mechanism | Write ops | Write gate | Direct SQLite write? |
|---|---|---|---|---|
| `caelum29/calibre-mcp` | Content Server, via `calibredb` CLI | set_metadata, add, remove, merge, bundles | **Yes**, default off | No |
| `FaceDeer/calibre_full_mcp_server` | `calibre-debug` worker + Calibre Python API | set_metadata, add_books, remove_books, formats, convert | **Yes**, per-library + per-field, default deny | No |
| **`Xpresi/calibre-mcp`** | **direct SQLite (primary)** + `calibredb` | 15 tools: set/remove metadata, rename, bulk fixes, vacuum | **No master flag**; `dry_run=true` default + Calibre-closed check + backup | **YES** |
| `gustavofsousa/calibre-mcp` | `calibredb` CLI (+ `ebook-convert`, `calibre-smtp`) | 13 tools, incl. bulk, rename, merge, remove, convert, email | **No master flag**; plan→confirm token + mandatory backup | No — `mode=ro` |
| `ZehuiTIAN/calibre-mcp` | `calibredb` CLI | add, add_format | No | No |
| `2b3pro/calibre-mcp` | `calibredb` CLI | set_metadata, add_format, write_file_metadata, polish, convert | No | No — `readonly: true` |
| `Quentinbest/calibre_mcp` | `calibredb` CLI | add, add_format, **remove --permanent**, set_metadata, cover | No | No |
| `THeK3nger/calibre-mcp` | `calibredb` CLI | `set_custom` only | No | No |
| `xmkevinchen/calibre-mcp` | `calibredb` CLI | `set_custom`, `set_metadata` | No | No |
| `benoute/calibre-mcp` | **read-only** | none | n/a | No |
| `trieloff/calibre-mcp` | **read-only** (pure bash) | none | n/a | No sqlite at all |
| `ni-c/calibreweb-mcp` | HTTP (Calibre-Web **OPDS**), read-only by construction | none | n/a — deliberately none | No |

Bucket tally over the twelve: **1 direct SQLite · 5 `calibredb` CLI · 1 Calibre Python API
(via `calibre-debug`) · 1 Content Server (via `calibredb`) · 4 read-only · 0 Content Server
HTTP write API.**

### 3.2 The two non-obvious safe designs worth reading

Both of these are more rigorous about write safety than either deep-dive target, and both are
directly relevant to the proposed feature.

**`gustavofsousa/calibre-mcp` — the deliberate counter-example to direct SQLite.**

- Python ≥3.12, FastMCP, `src/calibre_mcp/` is 3,144 LOC across 14 modules, plus a large
  `.specs/` design-doc tree (49 markdown files). 13 write tools (`server.py:157`–`492`:
  `update_metadata`, `update_metadata_bulk`, `rename_author`, `rename_tag`, `rename_series`,
  `add_book`, `import_folder`, `remove_book`, `merge_duplicate_group`, `convert_book`,
  `convert_book_bulk`, `email_book`).
- **Explicit read-only SQLite.** `src/calibre_mcp/sqlite_reader.py:1–7`: *"All reads go through
  here; this layer NEVER writes. The connection is opened with the `file:{path}?mode=ro` URI
  (`uri=True`) so SQLite itself refuses any write."* The connect call is at
  `sqlite_reader.py:72–75`. Repo-wide grep for `INSERT|UPDATE|DELETE FROM|CREATE TABLE|PRAGMA`
  in Python source returns **no write statement**.
- **All mutation through the CLI**, with one choke point: `calibredb_runner.py:1` — *"The single
  `calibredb` subprocess call site"*; `_run` (line 53) is the only `subprocess` call, always an
  arg-list with `shell=False` (line 5) so metadata values cannot inject. `set_metadata` at
  `calibredb_runner.py:96–114`.
- **Plan→confirm token — the strongest confirmation design in the survey.** This is the
  mechanism `caelum29` explicitly declined to build (`calibre_merge_books.ts:164`: *"no plan
  token"*). `src/calibre_mcp/confirmation.py:21–32` — `plan_token(op, book_id, payload)`
  returns the first 16 hex chars of `SHA-256("op|book_id|json.dumps(payload, sort_keys=True)")`,
  so logically-equal payloads in any key order yield the same token. `verify` (35–45) recomputes
  and compares with **`hmac.compare_digest`**, raising `ConfirmationError("…re-plan and review
  before applying")` on mismatch. Enforced at `library.py:344, 391, 471, 558, 655, 764, 966`
  (remove), `1020` (email) — without a matching token nothing is written; e.g. `library.py:341`
  returns the diff plus the token and stops.
- **Mandatory backup before every write, fail-closed.** `backup.py:42–67` `backup_metadata_db()`
  uses `shutil.copy2` and **raises `OSError` to abort before any calibredb write runs** if the
  backup cannot be created. `_prune` (85–91) retains a rolling window (default 20). Call sites
  at `library.py:196, 252, 345, 392, 472, 559, 656, 765, 829, 895, 970`.
- **Recoverable deletes:** `backup.py:93–119` `trash_book_files` copies files to a managed trash
  dir alongside Calibre's own recycle bin. README: "never a hard delete".
- **No master read-only env switch** — config is `CALIBRE_LIBRARY_PATH` +
  `CALIBRE_MCP_BACKUP_DIR` only (`config.py:16–17`). Safety comes from the token + backup, not
  from a disable flag. This is the main respect in which caelum29's design is stronger.
- README:13–39 claims *"Most Calibre MCP servers are read-only… This one writes — and does it
  safely"* and *"Writes … go through Calibre's own CLI tools … never raw SQL — so Calibre stays
  authoritative over its own database."* **Verified true in source.**

**`2b3pro/calibre-mcp` — the most directly reusable precedent for this specific feature.**

- `src/tools/write.ts:4–21` `updateMetadata()` does **not** write SQL: L17
  `await cli.setMetadata(bookId, fields)`, then re-reads via `db.getBookById()`.
  `CalibreCLI.ts:98–112` `setMetadata()` shells out to `calibredb set_metadata <id>
  --field k:v`. Exposed as the MCP tool `update_metadata` at `index.ts:230–241`.
- **Why it matters here:** `setMetadata` passes *arbitrary* `--field name:value` pairs
  (`CalibreCLI.ts:107–109`), so modelling "read" as a custom column needs **no new plumbing** —
  the generic write path already covers it. The same is true of caelum29
  (`isAllowedField()` accepts any `#`-prefixed key) and of `xmkevinchen`/`THeK3nger`, which
  expose `set_custom` directly.
- Its README:7 claim *"Queries the Calibre `metadata.db` directly via SQLite"* is **verified,
  and it is read-only**: `src/calibre/Database.ts:31`
  `this.db = new Database(dbPath, { readonly: true })` — the only explicit SQLite `readonly`
  flag in the survey. No backup or lock logic exists, and the README makes no safety claim
  about it.
- False positive to pre-empt: `tests/db_helper.ts:23–40` contains
  `INSERT INTO books/authors/…`, but line 4 is `new Database(":memory:")` — an in-memory test
  fixture, not a library write.

### 3.3 `Xpresi/calibre-mcp` — the one direct-SQLite writer, in detail

Python ≥3.10, FastMCP, 31 tracked files; `backend.py` 553 lines, `tools/write.py` 940,
`tools/bulk.py` ~1180. Hybrid design: **read-only SQLite for reads, direct read-write SQLite
for the main metadata and delete paths**, plus `calibredb` for some operations. No Content
Server HTTP API.

**The writable connection factory** — `src/calibre_mcp/backend.py:346–365`,
`CalibreBackend.connect_write`:

```python
def connect_write(self, timeout: int = 30) -> sqlite3.Connection:
    """
    Open a writable SQLite connection to metadata.db.

    Verifies Calibre is closed first, then opens the connection in WAL mode.
    ...
    Registers Calibre's custom SQLite functions so DB triggers don't fail:
      - title_sort(text) — used by books_update_trg / series_update_trg
      - uuid4()          — used by books_insert_trg
    These functions are normally registered by the Calibre process at runtime;
    without them, any UPDATE on books.title raises "no such function: title_sort".
    """
    self.require_calibre_closed()
    conn = sqlite3.connect(str(self.db_path), timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("title_sort", 1, _calibre_title_sort)
    conn.create_function("uuid4", 0, _calibre_uuid4)
    return conn
```

**Metadata writes** — `src/calibre_mcp/tools/write.py:50–301`, `_set_metadata_sqlite`:
`conn = backend.connect_write(timeout=15)` (line 65) → `BEGIN` (66) → raw statements for
`title`/`sort` (73), authors (103, 113, 116, 123), series (140, 145, 147), `series_index` (159),
publishers (175, 179, 181), tags (192, 203, 207), `comments` (216, 219), languages (228, 239,
243), `identifiers` (260, 264), `pubdate` (272) → `COMMIT` (277). Docstring: *"Apply metadata
changes directly via SQLite. Much faster than calibredb for large libraries (no library
scan)."*

**Destructive delete** — `tools/write.py:304–396`, `_remove_books_sqlite`, verified directly:
`connect_write` (339) → `BEGIN` (341) → `DELETE` from every per-book child table (346) →
`DELETE FROM books` (347) → `COMMIT` (348); only *then* are directories sent to the recycle bin
(357–385). The docstring makes the ordering an explicit invariant: *"ALL database rows are
deleted and COMMITTED before any file is touched… the failure mode is an orphan directory on
disk (harmless) … never a ghost book."*

**Other direct-write call sites** (independently confirmed by grep for raw write verbs):
`tools/bulk.py:373` (`UPDATE books SET path=?`), `:524,530,536,548` (author renames),
`:714,722,730,739,742,745` (title/tag/publisher/series renames), `:842,905,910,1032`,
`:1097` and `:1166` (orphan pruning), plus `backend.write_transaction` at `:512, 709, 839, 903,
1029`. `backend.py:468–487` also runs a writable `VACUUM`.

**The five justifications it offers for writing directly:**

1. **Calibre-closed process check.** `backend.py:296–316` `is_calibre_running()` —
   `tasklist /FI "IMAGENAME eq calibre.exe"` on Windows, `pgrep -x calibre` elsewhere, 5 s
   timeout. `backend.py:318–324` `require_calibre_closed()` raises
   `CalibreError("Calibre is currently open. Close it before running write operations that
   access the database directly.")`. It is called **inside `connect_write` (line 359)**, so
   every write path inherits it from a single choke point.
   **Caveat, verified:** `except Exception: return False` (315–316) — *"Can't check → assume
   closed, let SQLite catch real locks"*. The guard **fails open**.
2. **`PRAGMA journal_mode=WAL` + `PRAGMA foreign_keys = ON`** (`361–362`).
3. **Registering Calibre's own SQLite UDFs so Calibre's triggers behave.** `backend.py:23–27`:
   *"Calibre registers these at runtime when its process opens the DB. Without them, triggers on
   books/series (`books_update_trg`, `series_update_trg`, etc.) fail with 'no such function'. We
   register Python equivalents so direct SQLite writes work even when Calibre is closed."*
   Implementations at `backend.py:41–48` (`_calibre_title_sort`, moving leading articles:
   `'El capitán' → 'capitán, El'`) and `:51–53` (`_calibre_uuid4`).
   **This is the single most important technical finding in the survey for anyone considering a
   direct-SQLite path** — it is a concrete, non-obvious requirement discovered the hard way.
4. **Automatic pre-write backup, fail-closed.** `backend.py:408–415` `backup_database`
   (`shutil.copy2`); `backend.py:417–466` `auto_backup_if_due(reason)`, gated on
   `config.backup_before_bulk_ops` (435), reusing an auto-backup younger than
   `AUTO_BACKUP_MAX_AGE_S = 30*60` (32–33, 446) so batched jobs don't copy the whole database
   per call. **The dispatcher treats a backup error as fatal** — `server.py:887–908` aborts the
   whole operation: *"Aborted {name}: backup_before_bulk_ops is enabled but the pre-operation
   backup failed … Nothing was modified."* Eligible tools: `_BACKUP_BEFORE` (`server.py:862–875`),
   triggered by `_needs_auto_backup` (878–884) only when the call will really write.
5. **Delete ordering** (rows committed before files touched, above) and **lexical path
   validation** — `backend.py:130–184` `resolve_book_dir` rejects empty/NULL `books.path`
   because `library / "" == library root` would aim `send2trash` at the entire library. That was
   a real incident: `CHANGELOG.md` 0.3.0 documents **two library-wipe events**.

**Gating and defaults:** no master read-only switch. `config.py:24–25` declares
`backup_before_bulk_ops: bool = True` and `dry_run_by_default: bool = True`, both `true` in
`config.json.example`. Write tools carry `"dry_run": {"type": "boolean", "default": True}` in
their schemas (`server.py:423`–`721`, 13 tools); execution requires explicit `dry_run=false`,
which is also what triggers the backup. Reads stay read-only: `backend.py:255–284` `query_db`
uses `file:{db_path}?mode=ro` with `uri=True` (267), and `tools/query.py:351–386`
`raw_sql_query` blocks non-SELECT via a keyword blocklist (386) with a negative lookahead so
the scalar `REPLACE(...)` function still works (383).

**Dead config worth flagging:** `dry_run_by_default` is declared (`config.py:25`) and logged
(`server.py:1078`) but **read nowhere** — the real defaults come from the tool schemas. This is
ironic given `CHANGELOG.md` 0.3.0 explicitly fixed the same class of bug for
`backup_before_bulk_ops`: *"The setting was declared in `config.json` and read by nothing."*

**README vs source — a real discrepancy.** `README.md:25–27` claims writes go *"Via `calibredb`
CLI (handles files, folders, and triggers correctly)"* and lists direct SQLite only for
*"Bulk writes"*. That **understates the source**: single-book `set_book_metadata` and
`_remove_books_sqlite` write and delete via SQLite on the primary path. The module docstrings
contradict their own bodies — `tools/write.py:1` says *"via calibredb CLI"* while `backend.py:1`
says *"calibredb CLI for writes, SQLite for reads"*, yet `connect_write` is called from
`write.py`. Verified: `write.py` has **zero** `run_calibredb` calls for set/remove (only for
`check_library`, `embed_metadata`, `backup_metadata_opf`, `catalog`, `fts_index`, `fts_search`).
To be fair the README warns elsewhere (line 7 "⚠️ WARNING: This server can delete files";
line 15 and line 197 both state the Calibre-closed check) — the direct-write behaviour is
acknowledged in prose but mis-tabulated in the architecture table.

### 3.4 The remaining eight, briefly

**`trieloff/calibre-mcp` — read-only, pure bash.** 4 tracked files, `calibre-mcp.sh` 911 lines,
no Python. Exactly two tools: `search` (`calibre-mcp.sh:612`) and `fetch` (`:662`). Every
`calibredb` invocation enumerated — `list` ×3 (340, 408, 527), `search` (320), `fts_search`
(377) — all reads; **no write subcommand anywhere**. Zero `sqlite3`/`metadata.db` references,
no HTTP, no `curl`. The only filesystem mutations are its own temp/log files, never inside the
library. README claim ("searching and reading books") matches source.

**`THeK3nger/calibre-mcp` — `calibredb`, one write tool.** Python ≥3.10 + FastMCP, `server.py`
344 lines. `setCustomColumn(book_id, column_name, value, append=False)` (`server.py:288–340`)
builds `calibredb --with-library <url> set_custom [--append] <column> <book_id> <value>`
(`:313–327`) via `subprocess.check_output` (`:330`). No gating of any kind.
**Doc drift:** its `CLAUDE.md` claims "two main tools" and "calibredb CLI: Used for all database
operations"; source has **six** `@mcp.tool()` functions including this write tool (`:288`) —
the docs understate the write surface. Also, despite docstrings mentioning the "Content
Server", it only shells out (`import subprocess`, `server.py:10`).

**`xmkevinchen/calibre-mcp` — `calibredb`, two write tools.** Python ≥3.11, `server.py` 277
lines. `set_custom_column` (`server.py:204–234`, builds `calibredb set_custom [--append] …`) and
`set_metadata` (`:237–269`, builds `calibredb set_metadata <id> --field name:value …`), both via
the single choke point `_run_calibredb` (`:24–32`, 30 s timeout, raises on non-zero exit). No
gating. Its `CLAUDE.md` records the deliberate choice of `calibredb` over both the Content
Server and direct DB access because it *"doesn't require Calibre GUI running"*.

**`ZehuiTIAN/calibre-mcp` — `calibredb`; the SQLite near-miss.** Writes via the CLI:
`calibre.py:140` builds `args = ["add"]` in `add_paths()` (L122–171); `ocr.py:374–378`
`attach_format()` calls `run_calibredb(settings, ["add_format", …])`. Its SQLite writes are
**not** to `metadata.db`: `src/calibre_mcp/fulltext.py:22` imports `sqlite3` and writes
`DELETE FROM texts` (187), `INSERT INTO texts` (189) and `INSERT INTO texts_raw … ON CONFLICT`
(193) inside `index_text()` (184–199) — but the target is its **own FTS5 index**:
`index_path()` (51–53) returns `cache_dir() / "index.sqlite"`, `cache_dir()` (39–48) defaulting
to the OS temp dir, overridable via `CALIBRE_TEXT_CACHE_DIR`.
**How it justifies safety: by isolation, not locking.** `fulltext.py:8–10`: *"Search uses our
own SQLite FTS5 index over those converted texts… The index lives in a cache directory —
**nothing inside the calibre library is ever modified**."* This is the one SQLite safety story in
the survey that works, and it works precisely by never touching the library.

**`Quentinbest/calibre_mcp` — `calibredb`; least guarded.** Python, FastMCP, 480 lines. All
writes via `run_calibredb()` (`server.py:21–30`): `_add_book` (94–118), `_convert_book`
(120–173), `_delete_book` (175–194, **`["remove", str(book_id), "--permanent"]` at L176** — the
only irreversible permanent delete in the survey), `_update_book` (221–252), `_manage_tags`
(254–288), `_set_cover` (290–314). **No gate, no confirmation, no dry run.** The only env var is
`server.py:12` `CALIBRE_LIBRARY_PATH`. Contrast caelum29, which deliberately never passes
`--permanent` so removals land in Calibre's Trash (`calibre_remove_book.ts:1–5,20–22`).

**`benoute/calibre-mcp` — read-only.** Go, 1179 lines. Five read tools
(`cmd/calibre-mcp/mcp.go:292–333`). `OpenLibrary()` (`pkg/calibre/db.go:14–21`) called once at
`mcp.go:282`; reads via `Query`/`QueryRow`/`QueryRowContext` only (`book.go:25,76,118`,
`epub.go:249`, `search.go:95,181,190,217,244`). No `os/exec`, no `calibredb`. **Nuance:**
`db.go:16` is `sql.Open("sqlite3", dbPath)` with **no `mode=ro`** in the DSN, so the handle is
technically read-write capable even though the code never writes (repo-wide grep for `.Exec(`,
`os.Create`, `os.Remove`, `os.Rename`, `Truncate` → no matches). Read-only *by behaviour*, not
*by enforcement* — compare `gustavofsousa`, which sets `mode=ro`.

**`ni-c/calibreweb-mcp` — HTTP, read-only by construction.** Targets **Calibre-Web** (the
third-party frontend), *not* Calibre's Content Server; it speaks the **OPDS** feed.
`src/api.ts:190` hardcodes `method: 'GET'`, and every request funnels through that one `init`
object (189–217) — no non-GET path exists. README:189 *"All tools are read-only
(`readOnlyHint: true`)."* — verified: `src/tools/annotations.ts:14–15` defines
`READ_ONLY = { readOnlyHint: true }`, applied at `books.ts:51,118`, `covers.ts:109`,
`shelves.ts:41,90`, `stats.ts:20`, enforced by a test at `test/server.test.ts:81`.
**The best-articulated read-only rationale in the survey** — `SECURITY.md:29–40`, under
*"Read-only by construction, not by setting"*: *"Most servers in this family take a
`*_READ_ONLY` variable that stops the write tools being registered. This one has none, and its
absence is the point: there is nothing to switch off. The server speaks OPDS, which is a
catalogue feed — it offers no way to change a library, so no writing tool exists to gate."* It
adds the sharp caveat that the *credentials* are not read-only: a Calibre-Web login carries
whatever roles the account has, so restraint must come from a dedicated View-and-Download
account.
**Directly relevant to "mark as read":** ni-c *consumes* read/unread state but never writes it —
`src/tools/books.ts:24–25` maps view `read` → `/opds/readbooks`, `unread` → `/opds/unreadbooks`
(used at 91, enum 98, 127); `docs/guide/faq.md:23–25` notes these feeds need a non-anonymous
user with "Show Read and Unread" enabled, surfaced as a hint at `src/result.ts:167–168`. So
Calibre-Web tracks read state independently of the Calibre library — evidence that "read" is
commonly modelled as **per-user/application state**, not as a `metadata.db` column.

### 3.5 No "mark as read" precedent anywhere in the survey

A grep for `mark.?as.?read|mark_read|#read|read_status|is_read|read_column|finished|percent_read|last_read`
across all twelve repos returns **no matches**. `ni-c` is the only project aware that read/unread
state exists, and only as a read-only OPDS feed. The nearest analogues to the proposed feature
are the generic custom-column writers — `THeK3nger`'s `setCustomColumn`, `xmkevinchen`'s
`set_custom_column`, and `2b3pro`'s arbitrary `--field` passthrough — all via `calibredb`.
(`Xpresi`'s schema at `backend.py:97` does treat `last_read_positions` as a book-child table,
but only to delete from it.)

---

## Convergent design pattern

What the maintained implementations agree on, checked against source.

### 1. The write gate is default-off in the serious implementations

- caelum29: master env flag `CALIBRE_MCP_ENABLE_WRITE` (`config.ts:99`, truthy-only
  `"1"|"true"|"yes"`), enforced by unregistering every `write: true` tool at
  `server.ts:139–141`.
- FaceDeer: per-library `permissions.write`, default **deny** when absent
  (`permissions.py:33–35`), with `false` = read-only library and a **list** = field-level
  allowlist, checked before any RPC (`metadata_ops.py:223,253`).
- **They disagree on granularity, and both are worth having.** caelum29 gates per *tool*;
  FaceDeer gates per *library* and per *field*. For "mark as read", FaceDeer's model is the
  better fit: an allowlist of `["#read_status", "rating"]` permits exactly the proposed feature
  and nothing else.
- **Both are two-key systems.** caelum29 needs the MCP flag *and* the Calibre-side
  `--enable-local-write`; FaceDeer needs `permissions.write` *and* the `calibre-debug`
  prerequisite. Neither treats a single switch as sufficient.
- **But this is not universal.** Of the twelve surveyed, only these two gate writes behind a
  flag. `Xpresi` and `gustavofsousa` have **no** master switch and instead rely on per-call
  safety (dry-run default + backup; plan token + backup). The other six CLI/read-only projects
  have no gating at all. So "default-off write gate" is the norm among the *careful* projects,
  not an industry-wide convention — but it is the norm among the two that people actually run
  for read/write.

### 2. Both deep-dive targets refuse direct SQLite — and the one that doesn't needed heavy machinery

- caelum29: no `metadata.db` reference in `src/` at all; SQLite appears only as its own
  semantic index (`src/semantic/store.ts`). `CLAUDE.md` records the GUI-concurrency lock as
  **reproduced**, concluding *"Treat the DB as read-mostly; never race the GUI on writes."*
- FaceDeer: zero matches for `sqlite` or `metadata.db` in `src/`. All access through
  `calibre.library.db(path).new_api`.
- `gustavofsousa` opens SQLite with `mode=ro` and states the layer *"NEVER writes"*
  (`sqlite_reader.py:1–7`); `2b3pro` opens it with `{ readonly: true }`
  (`Database.ts:31`).
- `Xpresi` is the sole exception, and it had to solve five separate problems to make direct
  writes safe (§3.3) — including discovering that Calibre's triggers call `title_sort` and
  `uuid4` UDFs that only exist when Calibre's own process has registered them. Its changelog
  records two library-wipe incidents along the way.

### 3. Three write mechanisms, and the choice is forced by the runtime

- **`calibredb` CLI** — 5 of 12, the plurality, and used by both the deep-dive target with the
  strongest safety posture (`gustavofsousa`) and the one with the broadest tool surface.
  Explicitly justified by two projects as keeping Calibre authoritative over its own database,
  and by one as not requiring the GUI to be running.
- **Calibre Python API via `calibre-debug`** — FaceDeer only. Required because it needs
  Calibre's bundled interpreter and C extensions; it must be installed on the host.
- **Content Server** — caelum29 only, and *achieved by pointing `calibredb` at the server URL*,
  not by HTTP. This is also what makes it safe to use while the GUI is open.
- **Content Server HTTP write API** — **0 of 12.** caelum29's internal design note mentions a
  `/cdb/set-fields` client as future work, and it appears nowhere in shipped code. There is no
  verified prior art in this survey for direct Content Server write requests.

### 4. Documented preconditions, stated plainly

- caelum29: "Calibre with the **Content Server running**" is a listed requirement (README:46–47),
  and "Enabling writes" spells out both switches including the exact GUI checkbox and the
  `calibre-server --enable-local-write` command (README:173–190).
- FaceDeer: "Calibre must be installed on the host system… utilizes `calibre-debug`"
  (README:23), and the concurrency warning is a top-level prerequisite, not a footnote
  (README:25).

### 5. What they do to avoid racing a running Calibre

| Mitigation | caelum29 | FaceDeer | Xpresi | gustavofsousa |
|---|---|---|---|---|
| Route writes through the process that owns the library lock | **Yes** (`--with-library <url>/#<lib>`) | No — opens the library itself | No — opens the DB file itself | No — but routes through `calibredb` |
| Process check: refuse to write while Calibre runs | No — avoided by construction | **No** | **Yes** (`pgrep`/`tasklist`, fails open) | No |
| Kill the whole process *group* on timeout so no orphan holds the lock | **Yes** (`spawn.ts:51–126`) | No | n/a | No |
| Reap idle workers to shrink the handle's lifetime | n/a (stateless subprocess) | **Yes** (`worker_pool.py:235–271`) | n/a | n/a |
| Backup before writing | No | No | **Yes**, fail-closed | **Yes**, mandatory |
| Preview/confirm before destructive ops | **Yes** (in-band boolean) | No | `dry_run=true` default | **Yes** (hash token) |
| Idempotent-by-default, diff-reported writes | **Yes** | No | No | Partial (returns plan) |

Three clean conclusions:

1. **The mechanism determines the concurrency story.** Routing through the Content Server gives
   caelum29 GUI-safety for free and needs no process check. Opening the library in-process
   leaves FaceDeer relying on a README warning with no enforcement. Opening the DB file directly
   forces `Xpresi` to build a process check from scratch. **The amount of safety machinery
   required is inversely proportional to how much you delegate to Calibre.**
2. **Only the direct-SQLite project detects a running Calibre** — which is telling. The projects
   that delegate don't need to; the one that doesn't delegate must.
3. **Nobody solves concurrency by inspecting the database.** No lock-file reading, no PID check
   against `metadata.db` markers anywhere. The observed strategies are *avoid the conflict*
   (route through the owning process), *detect the conflict* (`Xpresi`'s process check), or
   *warn about the conflict* (FaceDeer).

### 6. Custom columns are always the user's job to create

Both deep-dive targets read and write existing custom columns and **neither creates them**:

- caelum29: `isAllowedField()` accepts any `#`-prefixed key (`metadata-fields.ts:28–31`); no
  column-creation code exists.
- FaceDeer: writes only if `key in database.field_metadata.custom_field_keys()`
  (`worker.py:638–640`); no creation code exists. README:139 instructs the user to create
  columns in Calibre and include the `#` prefix.

Same across the scan — creation is always in Calibre's GUI, and the write tools
(`set_custom` in `THeK3nger`/`xmkevinchen`, arbitrary `--field` in `2b3pro`/caelum29) target
existing columns. The convergent position: **a custom column is a schema object owned by
Calibre, not something an MCP server should create.** FaceDeer goes further and lets the
*column's own Calibre description* carry usage guidance to the model (`worker.py:371–372`,
README:143) — directly applicable if "read" is modelled as an enumerated `#read_status` column.

---

## What this means for a direct-SQLite write path

### The evidence weighs strongly against it, but it is not impossible

The honest summary is narrower than "nobody does this" — one project does, and it works. But the
distribution matters:

- **1 of 12 writes `metadata.db` directly** (`Xpresi`). Its own changelog documents two
  library-wipe incidents and a class of safety bugs it had to fix retroactively (a config
  setting that was "declared in `config.json` and read by nothing").
- **Both maintained read/write servers refuse it.** caelum29's author **reproduced** the
  GUI-concurrency failure and documented the conclusion: *"With the app open, direct
  `calibredb`/SQLite/DB-API access is refused or dangerous… Treat the DB as read-mostly; never
  race the GUI on writes."*
- **4 of 12 are read-only**, and the two that open `metadata.db` do so with an explicit
  read-only guard (`gustavofsousa` `mode=ro`; `2b3pro` `readonly: true`).
- **`gustavofsousa` is the deliberate counter-example** — a project with 13 write tools and
  strong safety machinery that chose `calibredb` precisely to avoid raw SQL, and says so in its
  README.
- **The one SQLite-safety story that works** (`ZehuiTIAN`) works by never touching the library:
  *"nothing inside the calibre library is ever modified."*

### What a direct-SQLite path in this project would actually require

`Xpresi` shows the minimum viable safety apparatus — this is not a short list, and every item
was learned from a failure:

1. **A process check for a running Calibre** (`backend.py:296–324`), because Calibre does not
   expect another process writing its database. Note `Xpresi`'s check **fails open** on an
   unexpected exception — a stricter implementation would fail closed.
2. **Registering Calibre's SQLite UDFs** — `title_sort` and `uuid4` (`backend.py:23–27,
   363–364`). Without them every `UPDATE` on `books.title` raises
   `no such function: title_sort`, because Calibre's own triggers call them. **This is the
   non-obvious requirement that makes naive direct writes fail**, and there is no way to learn
   it except by reading `metadata.db`'s trigger definitions.
3. **`PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys = ON`** (`backend.py:361–362`).
4. **Writing the link tables by hand**, not just `books`. `Xpresi`'
   `_set_metadata_sqlite` writes `books`, `books_authors_link`, `authors`, `series`,
   `books_series_link`, `publishers`, `books_publisher_link`, `tags`, `books_tags_link`,
   `comments`, `languages`, `books_languages_link`, `identifiers` — each with the right
   insert-or-relink logic. `Cache.set_metadata` does all of this for you.
5. **A fail-closed pre-write backup** (`backend.py:408–466`, `server.py:887–908`) with a
   retention policy, because a mistake here is not self-healing.
6. **Correct delete ordering** — commit all row deletions before touching any file, so the
   failure mode is an orphan directory rather than a ghost book (`write.py:336–385`).

For this project specifically there is an additional cost: `calibre_api.py:60–66` currently
calls `conn.rollback()` on any `sqlite3.Error` and never commits, and the connection helper is
built around short-lived read transactions. Shepherding that into a correct multi-table write
transaction with trigger-compatible UDFs is real work, and it would leave the project owning a
class of correctness bug that Calibre currently owns.

### The safer alternatives, concretely

Ordered by how much Calibre machinery you inherit. All three are precedented; the first two have
working reference implementations with cited code.

**Option A — `calibredb` routed at a running Content Server.** *Precedent: `caelum29/calibre-mcp`;
also the mechanism `gustavofsousa` uses (without the server routing).*

```sh
calibredb --with-library "http://localhost:8080/#<libId>" \
  set_metadata <id> --field "#read_status:Yes" --field "rating:8"
```
- Python-native via `subprocess.run([...], shell=False)` with an **argv array** — never a shell
  string (`calibredb_runner.py:5` gives the injection rationale; `calibredb/client.ts:1–3` the
  same).
- **Resolve the library ID, not the display name**, or the routed write 404s
  (`calibre_update_book.ts:73–75`); the mapping comes from `/ajax/library-info`.
- Requires the Content Server running and permitting local writes (`--enable-local-write`). The
  GUI-embedded server is read-only by default.
- Two-gate design: your own env flag plus the server setting.
- Classify `Forbidden`/`401`/`403` stderr into a specific actionable message
  (`write-refusal.ts:7–18`) rather than surfacing a raw CLI failure.
- Cost: a hard dependency on the Content Server, plus `calibredb` on PATH.
- Kill the process **group** on timeout — `calibredb` routed at the server can spawn a
  grandchild that inherits the pipes and keeps the write lock (`spawn.ts:1–9`).

**Option B — `calibre-debug` worker using `Cache.set_metadata`.** *Precedent:
`FaceDeer/calibre_full_mcp_server`; also what `Xpresi`'s docstrings claim to do before falling
back to SQL.*

- Launch `calibre-debug worker.py <library_path>`; speak newline-delimited JSON-RPC 2.0 over
  stdin/stdout (`worker_pool.py:171–181`, `worker.py:717–728`). Keep stdout strictly for the
  protocol; send diagnostics to stderr.
- In the worker: `database = calibre.library.db(path).new_api`, then
  `mi = database.get_metadata(id)`; mutate with `setattr(mi, field, value)` /
  `mi.set_user_metadata("#col", value)` / `mi.set_identifiers({...})`; commit with
  `database.set_metadata(id, mi)` (`worker.py:636–645`).
- Requires Calibre installed on the host; **works without the Content Server** — the decisive
  advantage over Option A for a desktop-only user.
- **Concurrency is your problem.** FaceDeer does not solve it — it warns. You could do better
  than the prior art by borrowing `Xpresi`'s process check (`pgrep -x calibre` /
  `tasklist … calibre.exe`) and refusing to open the library while the GUI is up. That
  combination — worker-based writes **plus** a real process guard — is not implemented by any
  project in this survey and would be genuinely new.

**Option C — Content Server HTTP write API.** *No verified precedent in this survey.*

- caelum29's internal design note refers to a `/cdb/set-fields` HTTP client as a later option;
  that path appears **nowhere** in its shipped code and **0 of 12** surveyed projects issue any
  HTTP request to mutate a library. It would give true in-process HTTP writes with no
  `calibredb` binary and inherit Option A's GUI-safety.
- Treat as unverified. Confirm the endpoint against Calibre's own source before relying on it,
  and note that Calibre's Content Server write API is not a documented stable interface the way
  `calibredb` is.

**Option D — direct SQLite.** *Precedent exists (`Xpresi`) but is expensive.* Only defensible if
you replicate all six items in the list above, preferably plus a fail-closed process check. The
survey's evidence is that this is the highest-effort, highest-risk path, chosen by exactly one
project, which then spent a release hardening it.

### Two cross-cutting requirements for whichever option is chosen

1. **Preview-then-confirm is for destructive operations; "mark as read" is not destructive.**
   caelum29 requires `confirm=true` for remove/merge/bulk but writes single-book metadata
   updates immediately, justified by `idempotentHint: true` and a reported before/after diff
   (`calibre_update_book.ts:32–51`). A "mark as read" write should follow the *update* shape:
   write on first call, report the applied diff, include a `noop` indicator. If the feature grows
   a bulk "mark all as read" form, that is where a bounded-set requirement and a
   `preview`/`confirm` pair become appropriate — caelum29 refuses an unbounded all-books write
   outright (`calibre_bulk_update.ts:75–80`) and caps a bulk call at 500 books (`:26`), while
   FaceDeer's `bulk_update_metadata` silently defaults to *every book in the library*
   (`worker.py:504–512`). Prefer caelum29's stance.
2. **Never report a committed write as failed.** Any routed write can time out client-side
   after the server has already committed. Re-read the book and, if the intended values are
   present, report success; if the re-read itself fails, report success with the *intended* diff
   and say the verification read failed (`calibre_update_book.ts:83–89,141–164`). Getting this
   wrong is what makes an agent retry a write that already happened.

A third, optional: if the write is gated, consider `gustavofsousa`'s **deterministic plan
token** (`confirmation.py:21–45`, SHA-256 over a JSON-sorted payload, verified with
`hmac.compare_digest`) rather than caelum29's bare boolean. It is stateless, cheap, and closes
the TOCTOU gap that caelum29 explicitly accepts.

---

## Appendix: revision pins

Shallow clones (`--depth 1`) — re-verify against these SHAs if the projects move.

| Repo | Commit |
|---|---|
| `caelum29/calibre-mcp` | `e58db358d7df2ddbcd2087df6d51239f526e838c` (v0.7.4, 2026-08-21) |
| `FaceDeer/calibre_full_mcp_server` | `f46192bf7f87ef34b36124877220e403fd452eeb` (2026-03-05) |
| `trieloff/calibre-mcp` | `1e96572a9f0e323b53ad60e777bf442ce922d4f5` |
| `THeK3nger/calibre-mcp` | `2257e4b0789045573a7cf3bb00ae4f76fe3624af` |
| `gustavofsousa/calibre-mcp` | `031ca1ef5a3fc5b941f6e947e81426e7aa45acb3` |
| `Xpresi/calibre-mcp` | `c808555be977fc9c538044c9a872ff39b2aa2b86` (v0.3.0) |
| `xmkevinchen/calibre-mcp` | `aa3cbe512744cfbef9696e41fdf02f5f0ff10292` |
| `ZehuiTIAN/calibre-mcp` | `0dbb4b842b0261231a3b7c5c74949afc4e9d9e61` |
| `2b3pro/calibre-mcp` | `931fb2d4388d2026824ada97a0b6f00a252a9ad2` |
| `benoute/calibre-mcp` | `d982a8df084ff6c6ed3e7d4a87084c3845b219d3` |
| `Quentinbest/calibre_mcp` | `9aa2f4b3ea94c814e1ac8aa0b72ab7d753ad259a` |
| `ni-c/calibreweb-mcp` | `0cc87cbeda32bc718469b7942aa124c5d1577067` |

Clone roots: `.research-tmp/clones/caelum29/`, `…/facedeer/`, and `…/scan-a/`, `…/scan-b/`
(the scan directories use owner-prefixed names, because several of these repos share the
basename `calibre-mcp` and collide otherwise).

### Notes on claims that appear in docs but not in code

Recorded separately because they are findings, not oversights in this document.

| Claim | Where | Status |
|---|---|---|
| caelum29: "all writes route through the Content Server" | README:41–42 | Effectively true; the mechanism is a `calibredb` subprocess, not an HTTP write call. |
| caelum29: `calibre_remove_book` "Permanently delete books (records + files)" | README:259 | **Overstated in the README.** The code deliberately never passes `--permanent`, so removals go to Calibre's Trash and are restorable (`calibre_remove_book.ts:1–5,20–22`). The tool's own MCP description says "go to Calibre's Trash" (`:20–22`), contradicting the README table. |
| caelum29: "Tested against Calibre 9.x" | README:47 | No version check in source; not enforceable. |
| caelum29: direct `/cdb/set-fields` HTTP client | `CLAUDE.md` (internal note) | **Not in shipped code.** `grep -r 'cdb/' src/` → no matches. Future work only. |
| FaceDeer: worker "Imports `calibre.library.db.cache`" | `doc/Architecture.md:41` | **Import path is wrong.** `worker.py:11` is `from calibre.library import db`; `Cache` is reached via `.new_api` (`worker.py:244–245`). The "accesses `metadata.db` safely" part holds — there is no SQL. |
| **`Xpresi`: "Writes \| Via `calibredb` CLI (handles files, folders, and triggers correctly)"** | README:25–27; also `tools/write.py:1` and `backend.py:1` docstrings | **Materially understates the source.** Single-book `set_metadata` and `remove_book` write and delete **directly via SQLite** (`tools/write.py:50–301`, `:304–396`); `write.py` has zero `run_calibredb` calls for set/remove. The README does acknowledge the Calibre-closed check in prose (lines 15, 197). |
| `Xpresi`: `dry_run_by_default` config setting | `config.py:25`, logged at `server.py:1078` | **Dead config — read nowhere.** Actual defaults come from the tool schemas. Ironic, since `CHANGELOG.md` 0.3.0 fixed the identical bug for `backup_before_bulk_ops`. |
| `THeK3nger`: "Exposes two main tools" | `CLAUDE.md` | **Stale.** Source has six `@mcp.tool()` functions, including the undocumented write tool `setCustomColumn` (`server.py:288`). |
