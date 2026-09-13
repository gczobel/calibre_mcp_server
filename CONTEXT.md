# Calibre MCP Server

An MCP server over a Calibre library. It reports book metadata, and writes read state and ratings back
into the library, which is what makes it a writer to a library Calibre owns. This fork adds read
tracking and rating to a surface that was previously read-only.

## Language

### The library

**Library**:
A Calibre library: one directory of books with a single metadata database. It is the unit the server
is pointed at, and the unit Calibre and Calibre-Web also open.
_Avoid_: collection, catalog

**Custom column**:
A user-defined Calibre field, held apart from Calibre's built-in fields. Read state is one; so is any
other user data the server reports.
_Avoid_: user column, extra field, custom field

**Direct layout**:
The custom-column storage in which a book has at most one value, held on the column itself. Used by
`bool`, `int`, `float`, `datetime`, `comments` and `composite` columns.
_Avoid_: non-link layout, non-normalized layout, direct table

**Link layout**:
The custom-column storage in which values live in a shared dictionary and are linked to books, so
several books can share one value and one book can hold several. Used by `text`, `rating`,
`enumeration` and `series` columns.
_Avoid_: normalized layout, dictionary + link layout, link-table layout

### Read state and rating

**Read state**:
Whether a book has been read. It has three values: read, unread, or no read tracking at all.
_Avoid_: read status, the read field

**Read column**:
The bool custom column that holds read state, found by its lookup label. A library without one has no
read tracking.
_Avoid_: read field, status column

**No read tracking**:
The state of a library that has no read column. It is deliberately not the same as unread, and is
reported as `null` rather than `false`.
_Avoid_: using unread as a synonym

**Rating**:
A book's score, 1 to 5 whole stars at the tool surface. Calibre holds the same score doubled, 0 to 10.
_Avoid_: score, stars out of ten

**Unrated**:
A book with no rating. Calibre's unrated state is the absence of a rating rather than a stored zero,
and tools report it as `null`. Clearing a rating is the action that produces it.
_Avoid_: no rating, rating is zero

### Seams and surfaces

**Tool surface**:
The MCP tools this server exposes, together with each tool's arguments and the shape of its result.
Documented in `docs/tool-surface.md`.
_Avoid_: API, endpoints

**Tool boundary**:
Where a tool's arguments arrive from a caller and its result renders back. Argument validation and
result shaping live here, and a result that renders nothing is invisible to the caller.
_Avoid_: API seam, MCP layer

**CalibreDB seam**:
The boundary between the server and the library database. It is the layer that speaks Calibre's own
storage — ratings doubled, read state in a custom column — and it refuses what that storage cannot
represent.
_Avoid_: API seam, database layer

### Deployment

**Read-write mount**:
The operator's decision to give the server write access to the library. The three write tools require
it; on a read-only mount they fail rather than silently doing nothing.
_Avoid_: write-enabled mount
