"""Shared fixtures for API-seam tests.

Tests exercise ``Book(book_id, library_path)`` and ``CalibreDB(library_path)``
against a minimal Calibre-like ``metadata.db`` built in a temp directory. The
schema mirrors the tables the server actually queries, so a test never depends
on a real Calibre install.

Both seams take a library path plus configuration of their own, so a test that
builds one asks for ``db`` or ``book`` here rather than repeating the
construction — the same argument as the tool-boundary fixtures below.

Boundary tests need more: they drive the server module through an in-memory MCP
client, so this module also owns how a server gets bound to a fixture library.
"""

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from fastmcp import Client

from calibre_mcp_server.calibre_api import Book, CalibreDB


# The subset of Calibre's schema the server touches. Custom-column tables are
# created on demand by ``CalibreLibrary.add_custom_column``.
SCHEMA_SQL = """
CREATE TABLE books (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'Unknown',
    sort TEXT,
    pubdate TEXT,
    series_index REAL,
    path TEXT
);

CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT, sort TEXT);
CREATE TABLE books_authors_link (book INTEGER, author INTEGER);

CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT, sort TEXT);
CREATE TABLE books_series_link (book INTEGER, series INTEGER);

CREATE TABLE publishers (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE books_publishers_link (book INTEGER, publisher INTEGER);

CREATE TABLE identifiers (id INTEGER PRIMARY KEY, type TEXT, val TEXT, book INTEGER);

CREATE TABLE languages (id INTEGER PRIMARY KEY, lang_code TEXT);
CREATE TABLE books_languages_link (book INTEGER, lang_code INTEGER);

CREATE TABLE comments (id INTEGER PRIMARY KEY, book INTEGER, text TEXT);

CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE books_tags_link (book INTEGER, tag INTEGER);

CREATE TABLE ratings (id INTEGER PRIMARY KEY, rating INTEGER NOT NULL UNIQUE);
CREATE TABLE books_ratings_link (
    book INTEGER NOT NULL,
    rating INTEGER NOT NULL,
    PRIMARY KEY (book, rating)
);

CREATE TABLE custom_columns (
    id INTEGER PRIMARY KEY,
    label TEXT,
    name TEXT,
    datatype TEXT,
    mark_for_delete INTEGER,
    editable INTEGER,
    display TEXT,
    is_multiple INTEGER,
    normalized INTEGER
);
"""


# Datatypes that store their value directly in ``custom_column_<id>(book, value)``.
DIRECT_DATATYPES = {"bool", "int", "float", "datetime", "comments", "composite"}
# Datatypes that use a dictionary table plus a link table.
LINK_DATATYPES = {"text", "rating", "enumeration", "series"}


class CalibreLibrary:
    """A minimal Calibre library database used to build test fixtures."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.db_path = self.path / "metadata.db"
        self._execute_script(SCHEMA_SQL)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _execute_script(self, sql: str) -> None:
        with self._connect() as conn:
            conn.executescript(sql)

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        """Run a statement in its own committed transaction."""
        conn = self._connect()
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur
        finally:
            conn.close()

    def query(self, sql: str, params=()) -> list:
        conn = self._connect()
        try:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    # -- books -----------------------------------------------------------

    def add_book(self, title: str, path: str | None = None) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO books (title, sort, path) VALUES (?, ?, ?)",
                (title, title, path or title),
            )
            return cur.lastrowid

    def add_author(self, name: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO authors (name, sort) VALUES (?, ?)", (name, name)
            )
            return cur.lastrowid

    def link_author(self, book_id: int, author_id: int) -> None:
        self.execute(
            "INSERT INTO books_authors_link (book, author) VALUES (?, ?)",
            (book_id, author_id),
        )

    def add_series(self, name: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO series (name, sort) VALUES (?, ?)", (name, name)
            )
            return cur.lastrowid

    def link_series(self, book_id: int, series_id: int, index: float = 1.0) -> None:
        self.execute(
            "INSERT INTO books_series_link (book, series) VALUES (?, ?)",
            (book_id, series_id),
        )
        self.execute(
            "UPDATE books SET series_index = ? WHERE id = ?", (index, book_id)
        )

    def add_tag(self, name: str) -> int:
        with self._connect() as conn:
            cur = conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
            return cur.lastrowid

    def link_tag(self, book_id: int, tag_id: int) -> None:
        self.execute(
            "INSERT INTO books_tags_link (book, tag) VALUES (?, ?)",
            (book_id, tag_id),
        )

    # -- ratings ---------------------------------------------------------

    def set_rating(self, book_id: int, stars: int) -> None:
        """Store a star rating (1-5) the way Calibre does: doubled, in the link table."""
        doubled = stars * 2
        rating_id = self.query(
            "SELECT id FROM ratings WHERE rating = ?", (doubled,)
        )
        if not rating_id:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO ratings (rating) VALUES (?)", (doubled,)
                )
                rating_id = cur.lastrowid
        else:
            rating_id = rating_id[0]["id"]
        # A book has exactly one rating: replace the link, don't accumulate.
        self.execute(
            "DELETE FROM books_ratings_link WHERE book = ?", (book_id,)
        )
        self.execute(
            "INSERT INTO books_ratings_link (book, rating) VALUES (?, ?)",
            (book_id, rating_id),
        )

    # -- custom columns --------------------------------------------------

    def add_custom_column(
        self, label: str, datatype: str, name: str | None = None
    ) -> int:
        """Register a custom column and create its backing table(s)."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO custom_columns (label, name, datatype, mark_for_delete, "
                "editable, display, is_multiple, normalized) "
                "VALUES (?, ?, ?, 0, 1, '{}', 0, ?)",
                (label, name or label, datatype, 0 if datatype in DIRECT_DATATYPES else 1),
            )
            column_id = cur.lastrowid

        if datatype in DIRECT_DATATYPES:
            value_type = (
                "REAL" if datatype == "float"
                else "TEXT" if datatype in ("datetime", "comments", "composite")
                else "INTEGER"
            )
            self._execute_script(
                f"CREATE TABLE custom_column_{column_id} "
                f"(book INTEGER NOT NULL UNIQUE, value {value_type})"
            )
        elif datatype in LINK_DATATYPES:
            self._execute_script(
                f"CREATE TABLE custom_column_{column_id} "
                f"(id INTEGER PRIMARY KEY, value TEXT)"
            )
            self._execute_script(
                f"CREATE TABLE books_custom_column_{column_id}_link "
                f"(book INTEGER, value INTEGER)"
            )
        # A datatype in neither set gets no backing table, matching Calibre,
        # where every supported datatype falls in exactly one of the two sets.
        return column_id

    def set_direct_value(self, column_id: int, book_id: int, value) -> None:
        self.execute(
            f"INSERT OR REPLACE INTO custom_column_{column_id} (book, value) "
            f"VALUES (?, ?)",
            (book_id, value),
        )

    def add_link_value(self, column_id: int, book_id: int, value: str) -> None:
        """Add a link-layout value (dictionary + link row) for a book."""
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO custom_column_{column_id} (value) VALUES (?)", (value,)
            )
            dict_id = cur.lastrowid
            conn.execute(
                f"INSERT INTO books_custom_column_{column_id}_link (book, value) "
                f"VALUES (?, ?)",
                (book_id, dict_id),
            )


@pytest.fixture
def library(tmp_path):
    """A fresh, empty Calibre-like library per test."""
    return CalibreLibrary(tmp_path / "lib")


# -- CalibreDB seam ------------------------------------------------------
#
# The two classes under test both take a library path plus configuration of
# their own, and the per-test data (which book) is an argument rather than a
# fixture, so each is a factory. ``db()`` and ``book(book_id)`` are the
# unconfigured cases.
#
# The plain helpers below are here for the same reason as the factories: a
# module that needs one should find it already written, not write a sixth copy.


@pytest.fixture
def db(library):
    """The ``CalibreDB`` seam over this test's fixture library.

    ``read_column_label`` is the configuration a test varies; everything else
    keeps the defaults the server itself would construct with.
    """
    def _db(**kwargs):
        return CalibreDB(str(library.path), **kwargs)

    return _db


@pytest.fixture
def book(library):
    """A ``Book`` over this test's fixture library, for the given book id."""
    def _book(book_id, **kwargs):
        return Book(book_id, str(library.path), **kwargs)

    return _book


@pytest.fixture
def add_book(library):
    """Insert a book, link the metadata given, and return its id.

    ``CalibreLibrary.add_book`` writes the row; this also links the author,
    series and tags that ``find_books`` criteria match on.
    """
    def _add_book(title, author=None, series=None, tags=None):
        book_id = library.add_book(title)
        if author:
            library.link_author(book_id, library.add_author(author))
        if series:
            library.link_series(book_id, library.add_series(series))
        for tag in tags or []:
            library.link_tag(book_id, library.add_tag(tag))
        return book_id

    return _add_book


@pytest.fixture
def ids():
    """The book ids of ``find_books`` rows, sorted, for comparing to a list."""
    return lambda rows: sorted(row["id"] for row in rows)


@pytest.fixture
def direct_column_value(library):
    """The stored value of a direct-layout custom column, read by raw SQL.

    Below the reader on purpose: an assertion about what a write stored must not
    go through the reader it is meant to be checking.
    """
    def _value(column_id, book_id):
        rows = library.query(
            f"SELECT value FROM custom_column_{column_id} WHERE book = ?",
            (book_id,),
        )
        return rows[0]["value"] if rows else None

    return _value


# -- tool boundary -------------------------------------------------------


@pytest.fixture
def bound_server(library, db, monkeypatch):
    """The server module, bound to this test's fixture library.

    ``config`` validates at import time, so the environment variable has to be
    set before the first import. The module is then cached process-wide, which
    means whichever test imports it first fixes the library path for the whole
    session — so ``calibre_db`` is rebound outright here. That is what makes a
    boundary test independent of import order, instead of depending on two
    modules' fixtures happening to look alike.
    """
    monkeypatch.setenv("CALIBRE_LIBRARY_PATH", str(library.path))

    import calibre_mcp_server.server as server

    monkeypatch.setattr(server, "calibre_db", db())
    return server


@pytest.fixture
def call_tool(bound_server):
    """Call one tool, returning the raw result for assertions on its content.

    One client session per call. A test that needs ``list_tools``, or several
    operations sharing a session, opens its own from ``bound_server.mcp`` —
    which is what ``test_tool_boundary`` does for the tool list.
    """
    def _call(name, arguments=None):
        async def run():
            async with Client(bound_server.mcp) as client:
                return await client.call_tool(name, arguments or {})

        return asyncio.run(run())

    return _call


@pytest.fixture
def parse_payload():
    """Parse the JSON a tool returned, from the text block it rendered."""
    return lambda result: json.loads(result.content[0].text)
