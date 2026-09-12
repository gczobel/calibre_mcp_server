"""Shared fixtures for API-seam tests.

Tests exercise ``Book(book_id, library_path)`` and ``CalibreDB(library_path)``
against a minimal Calibre-like ``metadata.db`` built in a temp directory. The
schema mirrors the tables the server actually queries, so a test never depends
on a real Calibre install.
"""

import sqlite3
from pathlib import Path

import pytest


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
        # 'composite' and anything else have no backing table.
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
