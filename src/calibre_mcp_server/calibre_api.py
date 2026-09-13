"""
Calibre API module for database interactions.

This module provides classes and functions for interacting with Calibre's
SQLite database, including book metadata retrieval and search operations.
"""

import os
import sqlite3
import logging
import unicodedata
from typing import List, Tuple, Generator, Dict, Any, Optional
from contextlib import contextmanager
from pathlib import Path

from .exceptions import (
    DatabaseError,
    NotFoundError,
    ConfigurationError
)
from .validation import (
    validate_positive_integer,
    validate_search_parameters,
    validate_rating_stars
)


logger = logging.getLogger(__name__)

# Calibre stores custom columns in one of two layouts, keyed by ``datatype``
# (see Calibre's create_custom_column in db/backend.py). The direct layout
# stores a value in ``custom_column_<id>(book, value)``; the link layout uses
# a dictionary table plus a link table. composite is computed by Calibre from
# a template, but its backing table is still the direct layout.
DIRECT_CUSTOM_COLUMN_DATATYPES = {
    'bool', 'int', 'float', 'datetime', 'comments', 'composite'
}
LINK_CUSTOM_COLUMN_DATATYPES = {'text', 'rating', 'enumeration', 'series'}

# Seconds to retry a write while another writer holds the SQLite lock. Calibre
# libraries use journal_mode=delete, so writers exclude each other at
# whole-file granularity and a busy database surfaces as SQLITE_BUSY.
WRITE_BUSY_TIMEOUT = 5.0


def resolve_read_column_id(
    cursor: sqlite3.Cursor,
    label: str
) -> Optional[int]:
    """
    Return the id of the bool custom column with ``label``, or ``None``.

    The read column is a ``bool`` (Yes/No) custom column, identified by its
    lookup label. A non-bool column that happens to share the label is not
    the read column, and a library without the column has no read tracking.
    """
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='custom_columns'
    """)
    if not cursor.fetchone():
        return None

    cursor.execute("""
        SELECT id FROM custom_columns
        WHERE label = ? AND datatype = 'bool'
    """, (label,))
    row = cursor.fetchone()
    return row[0] if row else None


def rating_to_stars(rating_value: Optional[int]) -> Optional[int]:
    """
    Convert Calibre's doubled rating (0-10) to whole stars 1-5.

    A stored 0 (or no stored value) means unrated and returns ``None``.
    """
    if rating_value is None or rating_value <= 0:
        return None
    return rating_value // 2


def read_value_to_bool(read_value: Any, has_column: bool) -> Optional[bool]:
    """
    Convert a stored read value to a boolean.

    ``has_column`` distinguishes the two ``None`` meanings: with no read
    column the state is ``None`` (no tracking); with a column, a missing row
    is unread (``False``).
    """
    if not has_column:
        return None
    return bool(read_value) if read_value is not None else False


@contextmanager
def database_connection(
    db_path: str
) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager for SQLite database connections with error handling.

    Parameters
    ----------
    db_path : str
        Path to the SQLite database file.

    Yields
    ------
    sqlite3.Connection
        Database connection object.

    Raises
    ------
    DatabaseError
        If there is a database connection error.
    """
    if not Path(db_path).exists():
        raise DatabaseError(
            f'Database file not found: {db_path}',
            'connection'
        )

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        yield conn
    except sqlite3.Error as e:
        if conn:
            conn.rollback()
        raise DatabaseError(
            f'Database connection failed: {e}',
            'connection'
        )
    finally:
        if conn:
            conn.close()


@contextmanager
def write_connection(
    db_path: str,
    timeout: Optional[float] = None
) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager for a write transaction with a bounded busy timeout.

    ``BEGIN IMMEDIATE`` takes the SQLite write lock up front, so a concurrent
    writer surfaces as ``SQLITE_BUSY`` after ``timeout`` seconds rather than
    hanging. The lock is released by commit on a clean exit and rollback on
    error. ``timeout`` defaults to :data:`WRITE_BUSY_TIMEOUT`.
    """
    if timeout is None:
        timeout = WRITE_BUSY_TIMEOUT

    if not Path(db_path).exists():
        raise DatabaseError(
            f'Database file not found: {db_path}',
            'connection'
        )

    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=timeout)
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except sqlite3.OperationalError as e:
        if conn:
            conn.rollback()
        message = str(e).lower()
        if 'locked' in message or 'busy' in message:
            raise DatabaseError(
                'Database is locked by another writer; close Calibre or '
                'Calibre-Web and retry the operation.',
                'write'
            )
        raise DatabaseError(f'Write failed: {e}', 'write')
    except sqlite3.Error as e:
        if conn:
            conn.rollback()
        raise DatabaseError(f'Write failed: {e}', 'write')
    finally:
        if conn:
            conn.close()


class Book:
    """
    Represents a book with its metadata from the Calibre database.

    This class loads and manages all metadata for a single book,
    providing a clean interface for accessing book information.
    """

    def __init__(
        self,
        book_id: int,
        library_path: str,
        db_filename: str = 'metadata.db',
        read_column_label: str = 'read'
    ) -> None:
        """
        Initialize a Book instance with metadata from Calibre database.

        Parameters
        ----------
        book_id : int
            Book ID (must be positive).
        library_path : str
            Path to the Calibre library folder.
        db_filename : str, optional
            Name of the SQLite database file, by default 'metadata.db'.
        read_column_label : str, optional
            Lookup label of the bool custom column used for read state,
            by default 'read'.

        Raises
        ------
        ValidationError
            If book_id is not a positive integer.
        ConfigurationError
            If library_path is invalid.
        DatabaseError
            If database file is not found or there's a connection error.
        NotFoundError
            If the book ID is not found in the database.
        """
        # Validate inputs
        self.id = validate_positive_integer(book_id, 'book_id')

        if not library_path or not isinstance(library_path, str):
            raise ConfigurationError(
                'Library path must be a non-empty string',
                'library_path'
            )

        # Initialize attributes with default values
        self.library_path = library_path
        self.title = ''
        self.title_sort = ''
        self.date = ''
        self.author = ''
        self.author_sort = ''
        self.series = ''
        self.series_sort = ''
        self.series_idx = 0.0
        self.publisher = ''
        self.identifiers = ''
        self.language = ''
        self.synopsis = ''
        self.tags = ''
        self.cover = ''
        self.custom_columns: Dict[str, Any] = {}
        self.read: Optional[bool] = None
        self.rating: Optional[int] = None
        self.read_column_label = read_column_label

        # Set up database path
        self.db_path = os.path.join(library_path, db_filename)

        # Load book data
        self._load_book_data()

    def _load_book_data(self) -> None:
        """
        Load all book data from the database in a single optimized query.

        This method performs a comprehensive join to retrieve all book
        metadata in one database operation for better performance.

        Raises
        ------
        DatabaseError
            If there's a database error during data loading.
        NotFoundError
            If the book ID is not found in the database.
        """
        try:
            with database_connection(self.db_path) as conn:
                cursor = conn.cursor()

                # Comprehensive query to get all book data at once
                query = """
                    SELECT
                        b.title,
                        b.sort,
                        b.pubdate,
                        b.series_index,
                        b.path,
                        GROUP_CONCAT(DISTINCT a.name ORDER BY a.name)
                        as authors,
                        GROUP_CONCAT(DISTINCT a.sort ORDER BY a.sort)
                        as author_sorts,
                        s.name as series_name,
                        s.sort as series_sort,
                        GROUP_CONCAT(DISTINCT p.name ORDER BY p.name)
                        as publishers,
                        GROUP_CONCAT(DISTINCT i.type || ':' || i.val
                                     ORDER BY i.type) as identifiers,
                        l.lang_code as language,
                        c.text as synopsis,
                        GROUP_CONCAT(DISTINCT t.name ORDER BY t.name) as tags
                    FROM books b
                    LEFT JOIN books_authors_link bal ON b.id = bal.book
                    LEFT JOIN authors a ON bal.author = a.id
                    LEFT JOIN books_series_link bsl ON b.id = bsl.book
                    LEFT JOIN series s ON bsl.series = s.id
                    LEFT JOIN books_publishers_link bpl ON b.id = bpl.book
                    LEFT JOIN publishers p ON bpl.publisher = p.id
                    LEFT JOIN identifiers i ON b.id = i.book
                    LEFT JOIN books_languages_link bll ON b.id = bll.book
                    LEFT JOIN languages l ON bll.lang_code = l.id
                    LEFT JOIN comments c ON b.id = c.book
                    LEFT JOIN books_tags_link btl ON b.id = btl.book
                    LEFT JOIN tags t ON btl.tag = t.id
                    WHERE b.id = ?
                    GROUP BY b.id, b.title, b.sort, b.pubdate, b.series_index,
                             b.path, s.name, s.sort, l.lang_code, c.text
                """

                cursor.execute(query, (self.id,))
                result = cursor.fetchone()

                if not result:
                    raise NotFoundError('book', str(self.id), 'ID')

                # Assign values from query result
                self._assign_book_data(result)

                # Load custom columns data
                self._load_custom_columns()

                # Load read state and rating
                self._load_read_state()
                self._load_rating()

        except sqlite3.Error as e:
            raise DatabaseError(
                f'Failed to load book data for ID {self.id}: {e}',
                'book_data_loading'
            )

    def _assign_book_data(self, result: sqlite3.Row) -> None:
        """
        Assign book data from database result to instance attributes.

        Parameters
        ----------
        result : sqlite3.Row
            Database query result row.
        """
        self.title = result[0] or ''
        self.title_sort = result[1] or ''
        self.date = result[2] or ''
        self.series_idx = result[3] or 0.0
        self.author = self._clean_concatenated_string(result[5])
        self.author_sort = self._clean_concatenated_string(result[6])
        self.series = result[7] or ''
        self.series_sort = result[8] or ''
        self.publisher = self._clean_concatenated_string(result[9])
        self.identifiers = self._clean_identifiers(result[10])
        self.language = result[11] or ''
        self.synopsis = result[12] or ''
        self.tags = self._clean_concatenated_string(result[13])
        self.cover = os.path.join(self.library_path, result[4], 'cover.jpg')

    def _clean_concatenated_string(self, value: Optional[str]) -> str:
        """
        Clean concatenated string values from GROUP_CONCAT.

        Parameters
        ----------
        value : str or None
            The concatenated string value.

        Returns
        -------
        str
            Cleaned string with proper separators.
        """
        if not value:
            return ''
        return value.replace(',', ' & ')

    def _clean_identifiers(self, value: Optional[str]) -> str:
        """
        Clean identifier strings with proper formatting.

        Parameters
        ----------
        value : str or None
            The concatenated identifier string.

        Returns
        -------
        str
            Cleaned identifiers with proper separators.
        """
        if not value:
            return ''
        return value.replace(',', ', ')

    def _load_custom_columns(self) -> None:
        """
        Load custom column data for the book from Calibre database.

        Custom columns come in two layouts, chosen by ``datatype``: the
        dictionary-plus-link layout (text, rating, enumeration, series) and
        the direct ``custom_column_<id>(book, value)`` layout (bool, int,
        float, datetime, comments, composite).

        Raises
        ------
        DatabaseError
            If there's a database error during custom columns loading.
        """
        try:
            with database_connection(self.db_path) as conn:
                cursor = conn.cursor()

                # First, check if custom_columns table exists
                cursor.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='custom_columns'
                """)
                if not cursor.fetchone():
                    logger.debug(
                        f"Book {self.id}: No custom_columns table found")
                    return

                # Get all custom columns metadata
                cursor.execute("""
                    SELECT id, label, datatype
                    FROM custom_columns
                    ORDER BY label
                """)
                custom_columns_info = cursor.fetchall()

                if not custom_columns_info:
                    logger.debug(
                        f"Book {self.id}: No custom columns defined in library"
                    )
                    return

                # Process each custom column by layout
                for column_id, label, datatype in custom_columns_info:
                    if datatype in DIRECT_CUSTOM_COLUMN_DATATYPES:
                        value = self._read_direct_custom_column(
                            cursor, column_id, datatype
                        )
                    elif datatype in LINK_CUSTOM_COLUMN_DATATYPES:
                        value = self._read_link_custom_column(
                            cursor, column_id
                        )
                    else:
                        # Unknown datatype: leave it unread rather than guess.
                        value = None

                    self.custom_columns[label] = value
                    logger.debug(
                        f"Book {self.id}: Set custom_columns['{label}'] = "
                        f"'{value}'"
                    )

        except sqlite3.Error as e:
            raise DatabaseError(
                f'Failed to load custom columns for book ID {self.id}: {e}',
                'custom_columns_loading'
            )

    def _read_direct_custom_column(
        self,
        cursor: sqlite3.Cursor,
        column_id: int,
        datatype: str
    ) -> Optional[Any]:
        """
        Read a direct-layout custom column value stored in
        ``custom_column_<id>(book, value)``.

        Returns
        -------
        Optional[Any]
            The stored value in its natural type, or ``None`` when there is
            no row for this book.
        """
        direct_table = f'custom_column_{column_id}'

        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name=?
        """, (direct_table,))
        if not cursor.fetchone():
            return None

        cursor.execute(
            f"SELECT value FROM {direct_table} WHERE book = ?", (self.id,)
        )
        result = cursor.fetchone()
        if result is None:
            return None

        return self._convert_direct_custom_column_value(datatype, result[0])

    @staticmethod
    def _convert_direct_custom_column_value(
        datatype: str,
        value: Any
    ) -> Any:
        """Coerce a direct-layout value to its natural Python type."""
        if value is None:
            return None
        if datatype == 'bool':
            return bool(value)
        if datatype == 'int':
            return int(value)
        if datatype == 'float':
            return float(value)
        # datetime, comments and composite are stored as text already.
        return value

    def _read_link_custom_column(
        self,
        cursor: sqlite3.Cursor,
        column_id: int
    ) -> Optional[str]:
        """
        Read a link-layout custom column value from
        ``books_custom_column_<id>_link``, resolving each link through the
        ``custom_column_<id>`` dictionary table.
        """
        link_table = f'books_custom_column_{column_id}_link'
        direct_table = f'custom_column_{column_id}'

        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name=?
        """, (link_table,))
        if not cursor.fetchone():
            return None

        cursor.execute(
            f"SELECT value FROM {link_table} WHERE book = ?", (self.id,)
        )
        link_results = cursor.fetchall()
        if not link_results:
            return None

        values = []
        for result in link_results:
            link_value = result[0]

            # Resolve the dictionary row when the link stores a numeric id.
            resolved_value = link_value
            try:
                is_int_str = isinstance(link_value, (int, str))
                is_digit = str(link_value).isdigit()
                if is_int_str and is_digit:
                    cursor.execute("""
                        SELECT name FROM sqlite_master
                        WHERE type='table' AND name=?
                    """, (direct_table,))

                    if cursor.fetchone():
                        cursor.execute(
                            f"SELECT value FROM {direct_table} WHERE id = ?",
                            (int(link_value),)
                        )
                        direct_result = cursor.fetchone()
                        if direct_result:
                            resolved_value = direct_result[0]
            except (ValueError, TypeError):
                # Use original value if conversion fails
                pass

            values.append(str(resolved_value))

        return ' & '.join(values) if len(values) > 1 else values[0]

    def _load_read_state(self) -> None:
        """
        Load read state from the bool custom column, if it exists.

        ``read`` is True (stored 1), False (stored 0 or no row), or None
        when the library has no read column.
        """
        try:
            with database_connection(self.db_path) as conn:
                cursor = conn.cursor()
                column_id = resolve_read_column_id(
                    cursor, self.read_column_label
                )
                raw = None
                if column_id is not None:
                    cursor.execute(
                        f"SELECT value FROM custom_column_{column_id} "
                        f"WHERE book = ?",
                        (self.id,),
                    )
                    result = cursor.fetchone()
                    raw = result[0] if result is not None else None

                self.read = read_value_to_bool(
                    raw, column_id is not None
                )

        except sqlite3.Error as e:
            raise DatabaseError(
                f'Failed to load read state for book ID {self.id}: {e}',
                'read_state_loading'
            )

    def _load_rating(self) -> None:
        """
        Load the built-in rating, exposed as whole stars 1-5.

        Calibre stores ratings doubled (0-10) in ``ratings`` plus
        ``books_ratings_link``; a stored 0 means unrated.
        """
        try:
            with database_connection(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT r.rating
                    FROM books_ratings_link brl
                    JOIN ratings r ON brl.rating = r.id
                    WHERE brl.book = ?
                """, (self.id,))
                result = cursor.fetchone()
                self.rating = rating_to_stars(
                    result[0] if result is not None else None
                )

        except sqlite3.Error as e:
            raise DatabaseError(
                f'Failed to load rating for book ID {self.id}: {e}',
                'rating_loading'
            )

    def to_json(self) -> Dict[str, Any]:
        """
        Return the book as a JSON-compatible dictionary.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing all book metadata.
        """
        return {
            'id': self.id,
            'title': self.title,
            'title_sort': self.title_sort,
            'date': self.date,
            'author': self.author,
            'author_sort': self.author_sort,
            'series': self.series,
            'series_sort': self.series_sort,
            'series_idx': self.series_idx,
            'publisher': self.publisher,
            'identifiers': self.identifiers,
            'language': self.language,
            'tags': self.tags,
            'synopsis': self.synopsis,
            'cover': self.cover,
            'custom_columns': self.custom_columns,
            'read': self.read,
            'rating': self.rating
        }

    def __str__(self) -> str:
        """
        Return a string representation of the book.

        Returns
        -------
        str
            Human-readable string representation.
        """
        return (
            f"Book(id={self.id}, title='{self.title}', "
            f"author='{self.author}')"
        )

    def __repr__(self) -> str:
        """
        Return a detailed string representation for debugging.

        Returns
        -------
        str
            Detailed string representation.
        """
        return (
            f"Book(id={self.id}, title='{self.title}', "
            f"author='{self.author}', series='{self.series}')"
        )


class CalibreDB:
    """
    Class to manage SQLite operations for Calibre database.

    This class provides all database operations needed to search and
    retrieve book metadata from a Calibre library database.
    """

    def __init__(
        self,
        library_path: str,
        db_filename: str = 'metadata.db',
        read_column_label: str = 'read'
    ) -> None:
        """
        Initialize CalibreDB with the path to the Calibre library.

        Parameters
        ----------
        library_path : str
            Path to the Calibre library folder.
        db_filename : str, optional
            Name of the SQLite database file, by default 'metadata.db'.
        read_column_label : str, optional
            Lookup label of the bool custom column used for read state,
            by default 'read'.

        Raises
        ------
        ConfigurationError
            If library_path is empty or invalid.
        DatabaseError
            If the database file doesn't exist.
        """
        if not library_path or not isinstance(library_path, str):
            raise ConfigurationError(
                'Library path must be a non-empty string',
                'library_path'
            )

        self.library_path = library_path
        self.db_path = os.path.join(library_path, db_filename)
        self.read_column_label = read_column_label

        # Validate database exists
        if not os.path.exists(self.db_path):
            raise DatabaseError(
                f'Database file not found: {self.db_path}',
                'initialization'
            )

        logger.info(f'CalibreDB initialized with database: {self.db_path}')

    @staticmethod
    def _normalize_text(text: str) -> str:
        """
        Normalize text by removing diacritics (accents) for comparison.

        This function converts characters with diacritics to their base form,
        making searches accent-insensitive, while preserving special letters
        like 'ñ', 'Ñ', 'ç', and 'Ç'.

        Parameters
        ----------
        text : str
            The text to normalize.

        Returns
        -------
        str
            The normalized text without diacritics but preserving ñ/Ñ/ç/Ç.
        """
        if not text:
            return text

        # Preserve ñ, Ñ, ç, and Ç by temporarily replacing them
        text = text.replace('ñ', '\u0001')  # Placeholder for ñ
        text = text.replace('Ñ', '\u0002')  # Placeholder for Ñ
        text = text.replace('ç', '\u0003')  # Placeholder for ç
        text = text.replace('Ç', '\u0004')  # Placeholder for Ç

        # Decompose characters into base + diacritics (NFD normalization)
        # Then filter out the diacritical marks (combining characters)
        normalized = unicodedata.normalize('NFD', text)
        # Filter out combining characters (accents, tildes, etc.)
        without_accents = ''.join(
            char for char in normalized
            if unicodedata.category(char) != 'Mn'
        )

        # Restore ñ, Ñ, ç, and Ç
        without_accents = without_accents.replace('\u0001', 'ñ')
        without_accents = without_accents.replace('\u0002', 'Ñ')
        without_accents = without_accents.replace('\u0003', 'ç')
        without_accents = without_accents.replace('\u0004', 'Ç')

        return without_accents

    def _execute_search_query(
        self,
        query: str,
        params: tuple,
        operation: str
    ) -> List[tuple]:
        """
        Execute a search query with error handling.

        Parameters
        ----------
        query : str
            SQL query to execute.
        params : tuple
            Query parameters.
        operation : str
            Description of the operation for error messages.

        Returns
        -------
        List[tuple]
            Query results.

        Raises
        ------
        DatabaseError
            If there's a database error during query execution.
        """
        try:
            with database_connection(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return cursor.fetchall()

        except sqlite3.Error as e:
            raise DatabaseError(
                f'Query execution failed: {e}',
                operation
            )

    def _ensure_book_exists(
        self,
        cursor: sqlite3.Cursor,
        book_id: int
    ) -> None:
        """Raise NotFoundError when the book is not in the database."""
        cursor.execute("SELECT id FROM books WHERE id = ?", (book_id,))
        if not cursor.fetchone():
            raise NotFoundError('book', str(book_id), 'ID')

    def _write_read_status(self, book_id: int, read: bool) -> Dict[str, Any]:
        """
        Write ``read`` (1 for read, 0 for unread) into the read column.

        Idempotent: uses an upsert on the ``UNIQUE(book)`` index Calibre
        creates on the column table.
        """
        validated_id = validate_positive_integer(book_id, 'book_id')

        with write_connection(self.db_path) as conn:
            cursor = conn.cursor()
            self._ensure_book_exists(cursor, validated_id)

            column_id = resolve_read_column_id(
                cursor, self.read_column_label
            )
            if column_id is None:
                raise ConfigurationError(
                    f"Read column '#{self.read_column_label}' does not exist; "
                    f"create a Yes/No custom column with lookup name "
                    f"'{self.read_column_label}' in Calibre first.",
                    'read_column'
                )

            cursor.execute(
                f"INSERT INTO custom_column_{column_id} (book, value) "
                f"VALUES (?, ?) "
                f"ON CONFLICT(book) DO UPDATE SET value = excluded.value",
                (validated_id, int(read)),
            )

        return {'book_id': validated_id, 'read': read}

    def mark_book_read(self, book_id: int) -> Dict[str, Any]:
        """Mark a book read by writing 1 to the read column. Idempotent."""
        return self._write_read_status(book_id, True)

    def mark_book_unread(self, book_id: int) -> Dict[str, Any]:
        """Mark a book unread by writing 0 to the read column. Idempotent."""
        return self._write_read_status(book_id, False)

    def set_book_rating(self, book_id: int, stars: int) -> Dict[str, Any]:
        """
        Set a book's rating to a whole number of stars, 1 to 5, or clear it.

        ``stars=0`` clears the rating. Calibre's unrated state is an absent
        row in ``books_ratings_link``, so clearing deletes the book's link
        rather than writing a zero rating.

        Calibre stores ratings doubled (2-10) in ``ratings`` with a single
        link row per book in ``books_ratings_link``, so this finds or creates
        the doubled rating row and replaces the book's link.
        """
        validated_id = validate_positive_integer(book_id, 'book_id')
        validated_stars = validate_rating_stars(stars, allow_zero=True)

        with write_connection(self.db_path) as conn:
            cursor = conn.cursor()
            self._ensure_book_exists(cursor, validated_id)

            if validated_stars == 0:
                cursor.execute(
                    "DELETE FROM books_ratings_link WHERE book = ?",
                    (validated_id,),
                )
                return {'book_id': validated_id, 'rating': None}

            doubled = validated_stars * 2

            cursor.execute(
                "SELECT id FROM ratings WHERE rating = ?", (doubled,)
            )
            row = cursor.fetchone()
            if row:
                rating_id = row[0]
            else:
                cursor.execute(
                    "INSERT INTO ratings (rating) VALUES (?)", (doubled,)
                )
                rating_id = cursor.lastrowid

            cursor.execute(
                "DELETE FROM books_ratings_link WHERE book = ?",
                (validated_id,),
            )
            cursor.execute(
                "INSERT INTO books_ratings_link (book, rating) VALUES (?, ?)",
                (validated_id, rating_id),
            )

        return {'book_id': validated_id, 'rating': validated_stars}

    @staticmethod
    def _validate_text_criterion(
        value: Optional[str],
        name: str
    ) -> Optional[str]:
        """Return a non-empty, stripped text criterion or raise ValueError."""
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'{name} must be a non-empty string')
        return value.strip()

    def _text_criterion_matches(
        self,
        criterion: str,
        haystack: str
    ) -> bool:
        """Case- and accent-insensitive substring match."""
        return (
            self._normalize_text(criterion).lower()
            in self._normalize_text(haystack).lower()
        )

    def find_books(
        self,
        author: Optional[str] = None,
        tag: Optional[str] = None,
        series: Optional[str] = None,
        rating_min: Optional[int] = None,
        rating_max: Optional[int] = None,
        read: Optional[bool] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Find books matching optional criteria, combined with AND.

        Text criteria (author, tag, series) match case- and
        accent-insensitively as substrings. Rating bounds are whole stars.
        ``read`` filters on read state; without a read column every book's
        state is ``None``, so a read filter matches nothing.
        """
        author = self._validate_text_criterion(author, 'author')
        tag = self._validate_text_criterion(tag, 'tag')
        series = self._validate_text_criterion(series, 'series')

        if rating_min is not None:
            rating_min = validate_rating_stars(rating_min)
        if rating_max is not None:
            rating_max = validate_rating_stars(rating_max)
        if (
            rating_min is not None
            and rating_max is not None
            and rating_min > rating_max
        ):
            raise ValueError('rating_min cannot exceed rating_max')

        if read is not None and not isinstance(read, bool):
            raise ValueError('read must be a boolean')

        limit = validate_positive_integer(limit, 'limit')

        with database_connection(self.db_path) as conn:
            cursor = conn.cursor()
            read_column_id = resolve_read_column_id(
                cursor, self.read_column_label
            )

            read_join = ''
            read_select = 'NULL AS read_value'
            if read_column_id is not None:
                read_join = (
                    f"LEFT JOIN custom_column_{read_column_id} cc "
                    f"ON b.id = cc.book"
                )
                read_select = 'MAX(cc.value) AS read_value'

            query = f"""
                SELECT
                    b.id,
                    b.title,
                    COALESCE(GROUP_CONCAT(DISTINCT a.name ORDER BY a.name), '')
                        AS authors,
                    MAX(s.name) AS series_name,
                    MAX(r.rating) AS rating,
                    COALESCE(GROUP_CONCAT(DISTINCT t.name ORDER BY t.name), '')
                        AS tags,
                    {read_select}
                FROM books b
                LEFT JOIN books_authors_link bal ON b.id = bal.book
                LEFT JOIN authors a ON bal.author = a.id
                LEFT JOIN books_series_link bsl ON b.id = bsl.book
                LEFT JOIN series s ON bsl.series = s.id
                LEFT JOIN books_ratings_link brl ON b.id = brl.book
                LEFT JOIN ratings r ON brl.rating = r.id
                LEFT JOIN books_tags_link btl ON b.id = btl.book
                LEFT JOIN tags t ON btl.tag = t.id
                {read_join}
                GROUP BY b.id, b.title
                ORDER BY b.title
            """
            cursor.execute(query)
            rows = cursor.fetchall()

        results = []
        for row in rows:
            authors = (row['authors'] or '').replace(',', ' & ')
            series_name = row['series_name'] or ''
            tags = row['tags'] or ''
            rating_value = row['rating']
            read_value = row['read_value']

            read_state = read_value_to_bool(
                read_value, read_column_id is not None
            )
            rating = rating_to_stars(rating_value)

            if (
                author is not None
                and not self._text_criterion_matches(author, authors)
            ):
                continue
            if tag is not None and not self._text_criterion_matches(
                tag, tags
            ):
                continue
            if (
                series is not None
                and not self._text_criterion_matches(series, series_name)
            ):
                continue
            if rating_min is not None and (
                rating is None or rating < rating_min
            ):
                continue
            if rating_max is not None and (
                rating is None or rating > rating_max
            ):
                continue
            if read is not None and read_state != read:
                continue

            results.append({
                'id': row['id'],
                'title': row['title'],
                'author': authors,
                'series': series_name,
                'rating': rating,
                'read': read_state,
            })

            if len(results) >= limit:
                break

        return results

    def search_books_by_title(
        self,
        title_pattern: str
    ) -> List[Tuple[int, str]]:
        """
        Search for books by title matching a pattern.

        This search is accent-insensitive, meaning it will match books
        regardless of diacritical marks.

        Parameters
        ----------
        title_pattern : str
            Pattern to search for in titles (supports % wildcards).

        Returns
        -------
        List[Tuple[int, str]]
            List of (book_id, title) tuples.

        Raises
        ------
        ValidationError
            If pattern is empty or invalid.
        DatabaseError
            If there is a database error.
        """
        validated_pattern = validate_search_parameters(title_pattern)
        normalized_pattern = self._normalize_text(validated_pattern)

        try:
            with database_connection(self.db_path) as conn:
                cursor = conn.cursor()

                # Get all books and filter by normalized comparison
                query = 'SELECT id, title FROM books ORDER BY title'
                cursor.execute(query)
                all_books = cursor.fetchall()

                # Filter books by normalized title matching
                results = []
                # Remove % wildcards for pattern matching
                search_pattern = normalized_pattern.replace('%', '')

                for book in all_books:
                    book_id, book_title = book
                    normalized_title = self._normalize_text(book_title)

                    # Handle different wildcard patterns
                    starts_with_wildcard = validated_pattern.startswith('%')
                    ends_with_wildcard = validated_pattern.endswith('%')

                    if starts_with_wildcard and ends_with_wildcard:
                        # Contains search: %pattern%
                        if search_pattern.lower() in normalized_title.lower():
                            results.append((book_id, book_title))
                    elif starts_with_wildcard:
                        # Ends with search: %pattern
                        if normalized_title.lower().endswith(
                            search_pattern.lower()
                        ):
                            results.append((book_id, book_title))
                    elif ends_with_wildcard:
                        # Starts with search: pattern%
                        if normalized_title.lower().startswith(
                            search_pattern.lower()
                        ):
                            results.append((book_id, book_title))
                    else:
                        # Exact match search
                        if normalized_title.lower() == search_pattern.lower():
                            results.append((book_id, book_title))

        except sqlite3.Error as e:
            raise DatabaseError(
                f'Query execution failed: {e}',
                'title search'
            )

        if not results:
            raise NotFoundError(
                'books', validated_pattern, 'title pattern'
            )

        return results

    def search_authors_by_name(
        self,
        name_pattern: str
    ) -> List[Tuple[int, str]]:
        """
        Search for authors by name matching a pattern.

        This search is accent-insensitive, meaning it will match authors
        regardless of diacritical marks.

        Parameters
        ----------
        name_pattern : str
            Pattern to search for in names (supports % wildcards).

        Returns
        -------
        List[Tuple[int, str]]
            List of (author_id, name) tuples.

        Raises
        ------
        ValidationError
            If pattern is empty or invalid.
        DatabaseError
            If there is a database error.
        """
        validated_pattern = validate_search_parameters(name_pattern)
        normalized_pattern = self._normalize_text(validated_pattern)

        try:
            with database_connection(self.db_path) as conn:
                cursor = conn.cursor()

                # Get all authors and filter by normalized comparison
                query = 'SELECT id, name FROM authors ORDER BY name'
                cursor.execute(query)
                all_authors = cursor.fetchall()

                # Filter authors by normalized name matching
                results = []
                search_pattern = normalized_pattern.replace('%', '')

                for author in all_authors:
                    author_id, author_name = author
                    normalized_name = self._normalize_text(author_name)

                    # Handle different wildcard patterns
                    starts_with_wildcard = validated_pattern.startswith('%')
                    ends_with_wildcard = validated_pattern.endswith('%')

                    if starts_with_wildcard and ends_with_wildcard:
                        # Contains search: %pattern%
                        if search_pattern.lower() in normalized_name.lower():
                            results.append((author_id, author_name))
                    elif starts_with_wildcard:
                        # Ends with search: %pattern
                        if normalized_name.lower().endswith(
                            search_pattern.lower()
                        ):
                            results.append((author_id, author_name))
                    elif ends_with_wildcard:
                        # Starts with search: pattern%
                        if normalized_name.lower().startswith(
                            search_pattern.lower()
                        ):
                            results.append((author_id, author_name))
                    else:
                        # Exact match search
                        if normalized_name.lower() == search_pattern.lower():
                            results.append((author_id, author_name))

        except sqlite3.Error as e:
            raise DatabaseError(
                f'Query execution failed: {e}',
                'author name search'
            )

        if not results:
            raise NotFoundError(
                'authors', validated_pattern, 'name pattern'
            )

        return results

    def search_books_by_tag(
        self,
        tag_pattern: str
    ) -> List[Tuple[int, str, str, str]]:
        """
        Get detailed information about books with tags matching a pattern.

        This search is accent-insensitive, meaning it will match tags
        regardless of diacritical marks.

        Parameters
        ----------
        tag_pattern : str
            Pattern to search for in tag names (supports % wildcards).

        Returns
        -------
        List[Tuple[int, str, str, str]]
            List of (book_id, title, author_name, publication_date) tuples,
            ordered by title.

        Raises
        ------
        ValidationError
            If pattern is empty or invalid.
        DatabaseError
            If there is a database error.
        """
        validated_pattern = validate_search_parameters(tag_pattern, 100)
        normalized_pattern = self._normalize_text(validated_pattern)

        try:
            with database_connection(self.db_path) as conn:
                cursor = conn.cursor()

                # Get all tags and filter by normalized comparison
                query = 'SELECT id, name FROM tags'
                cursor.execute(query)
                all_tags = cursor.fetchall()

                # Filter tags by normalized name matching
                matching_tag_ids = []
                search_pattern = normalized_pattern.replace('%', '')

                for tag_id, tag_name_db in all_tags:
                    normalized_tag = self._normalize_text(tag_name_db)

                    # Handle different wildcard patterns
                    starts_with_wildcard = validated_pattern.startswith('%')
                    ends_with_wildcard = validated_pattern.endswith('%')

                    if starts_with_wildcard and ends_with_wildcard:
                        # Contains search: %pattern%
                        if search_pattern.lower() in normalized_tag.lower():
                            matching_tag_ids.append(tag_id)
                    elif starts_with_wildcard:
                        # Ends with search: %pattern
                        if normalized_tag.lower().endswith(
                            search_pattern.lower()
                        ):
                            matching_tag_ids.append(tag_id)
                    elif ends_with_wildcard:
                        # Starts with search: pattern%
                        if normalized_tag.lower().startswith(
                            search_pattern.lower()
                        ):
                            matching_tag_ids.append(tag_id)
                    else:
                        # Exact match search
                        if normalized_tag.lower() == search_pattern.lower():
                            matching_tag_ids.append(tag_id)

                if not matching_tag_ids:
                    raise NotFoundError(
                        'books', validated_pattern, 'tag pattern'
                    )

                # Get books for matching tags
                placeholders = ','.join('?' * len(matching_tag_ids))
                query = f"""
                    SELECT DISTINCT b.id, b.title,
                           COALESCE(GROUP_CONCAT(a.name, ' & '), '')
                           as authors,
                           b.pubdate
                    FROM books b
                    JOIN books_tags_link btl ON b.id = btl.book
                    JOIN tags t ON btl.tag = t.id
                    LEFT JOIN books_authors_link bal ON b.id = bal.book
                    LEFT JOIN authors a ON bal.author = a.id
                    WHERE t.id IN ({placeholders})
                    GROUP BY b.id, b.title, b.pubdate
                    ORDER BY b.title
                """

                cursor.execute(query, matching_tag_ids)
                results = cursor.fetchall()

        except sqlite3.Error as e:
            raise DatabaseError(
                f'Query execution failed: {e}',
                'tag pattern search'
            )

        if not results:
            raise NotFoundError(
                'books', validated_pattern, 'tag pattern'
            )

        return results

    def get_books_by_author(
        self,
        author_name: str
    ) -> List[Tuple[int, str, str, str]]:
        """
        Get detailed information about all books by a specific author.

        This search is accent-insensitive, meaning it will match authors
        regardless of diacritical marks.

        Parameters
        ----------
        author_name : str
            Name of the author.

        Returns
        -------
        List[Tuple[int, str, str, str]]
            List of (book_id, title, publication_date, series_info) tuples,
            ordered by publication date.

        Raises
        ------
        ValidationError
            If author name is empty or invalid.
        DatabaseError
            If there is a database error.
        """
        validated_name = validate_search_parameters(author_name)
        normalized_name = self._normalize_text(validated_name)

        try:
            with database_connection(self.db_path) as conn:
                cursor = conn.cursor()

                # Get all authors and find matching ones
                query = 'SELECT id, name FROM authors'
                cursor.execute(query)
                all_authors = cursor.fetchall()

                # Find authors matching the normalized name
                matching_author_ids = []
                for author_id, author_name_db in all_authors:
                    if self._normalize_text(author_name_db).lower() == \
                       normalized_name.lower():
                        matching_author_ids.append(author_id)

                if not matching_author_ids:
                    raise NotFoundError(
                        'books', validated_name, 'author name'
                    )

                # Get books for matching authors
                placeholders = ','.join('?' * len(matching_author_ids))
                query = f"""
                    SELECT DISTINCT b.id, b.title, b.pubdate,
                           CASE
                               WHEN s.name IS NOT NULL
                               THEN s.name || ' #' ||
                                    CAST(b.series_index AS TEXT)
                               ELSE ''
                           END as series_info
                    FROM books b
                    JOIN books_authors_link bal ON b.id = bal.book
                    JOIN authors a ON bal.author = a.id
                    LEFT JOIN books_series_link bsl ON b.id = bsl.book
                    LEFT JOIN series s ON bsl.series = s.id
                    WHERE a.id IN ({placeholders})
                    ORDER BY b.pubdate DESC, b.title
                """

                cursor.execute(query, matching_author_ids)
                results = cursor.fetchall()

        except sqlite3.Error as e:
            raise DatabaseError(
                f'Query execution failed: {e}',
                'author books search'
            )

        if not results:
            raise NotFoundError('books', validated_name, 'author name')

        return results

    def get_books_by_author_id(
        self,
        author_id: int
    ) -> List[Tuple[int, str, str, str]]:
        """
        Get detailed information about all books by a specific author ID.

        Parameters
        ----------
        author_id : int
            ID of the author.

        Returns
        -------
        List[Tuple[int, str, str, str]]
            List of (book_id, title, publication_date, series_info) tuples,
            ordered by publication date.

        Raises
        ------
        ValidationError
            If author_id is not a positive integer.
        DatabaseError
            If there is a database error.
        """
        validated_id = validate_positive_integer(author_id, 'author_id')

        query = """
            SELECT DISTINCT b.id, b.title, b.pubdate,
                   CASE
                       WHEN s.name IS NOT NULL
                       THEN s.name || ' #' || CAST(b.series_index AS TEXT)
                       ELSE ''
                   END as series_info
            FROM books b
            JOIN books_authors_link bal ON b.id = bal.book
            LEFT JOIN books_series_link bsl ON b.id = bsl.book
            LEFT JOIN series s ON bsl.series = s.id
            WHERE bal.author = ?
            ORDER BY b.pubdate DESC, b.title
        """

        results = self._execute_search_query(
            query,
            (validated_id,),
            'author ID books search'
        )

        if not results:
            raise NotFoundError('books', str(validated_id), 'author ID')

        return results

    def get_books_by_series(
        self,
        series_name: str
    ) -> List[Tuple[int, str, float]]:
        """
        Get all books in a specific series.

        This search is accent-insensitive, meaning it will match series
        regardless of diacritical marks.

        Parameters
        ----------
        series_name : str
            Name of the series.

        Returns
        -------
        List[Tuple[int, str, float]]
            List of (book_id, title, series_index) tuples,
            ordered by series index.

        Raises
        ------
        ValidationError
            If series name is empty or invalid.
        DatabaseError
            If there is a database error.
        """
        validated_name = validate_search_parameters(series_name)
        normalized_name = self._normalize_text(validated_name)

        try:
            with database_connection(self.db_path) as conn:
                cursor = conn.cursor()

                # Get all series and find matching ones
                query = 'SELECT id, name FROM series'
                cursor.execute(query)
                all_series = cursor.fetchall()

                # Find series matching the normalized name
                matching_series_ids = []
                for series_id, series_name_db in all_series:
                    if self._normalize_text(series_name_db).lower() == \
                       normalized_name.lower():
                        matching_series_ids.append(series_id)

                if not matching_series_ids:
                    raise NotFoundError(
                        'books', validated_name, 'series name'
                    )

                # Get books for matching series
                placeholders = ','.join('?' * len(matching_series_ids))
                query = f"""
                    SELECT b.id, b.title, b.series_index
                    FROM books b
                    JOIN books_series_link bsl ON b.id = bsl.book
                    JOIN series s ON bsl.series = s.id
                    WHERE s.id IN ({placeholders})
                    ORDER BY b.series_index
                """

                cursor.execute(query, matching_series_ids)
                results = cursor.fetchall()

        except sqlite3.Error as e:
            raise DatabaseError(
                f'Query execution failed: {e}',
                'series books search'
            )

        if not results:
            raise NotFoundError('books', validated_name, 'series name')

        return results

    def get_books_by_tag(
        self,
        tag_name: str
    ) -> List[Tuple[int, str, str, str]]:
        """
        Get detailed information about all books with a specific tag.

        This search is accent-insensitive, meaning it will match tags
        regardless of diacritical marks.

        Parameters
        ----------
        tag_name : str
            Name of the tag to search for.

        Returns
        -------
        List[Tuple[int, str, str, str]]
            List of (book_id, title, author_name, publication_date) tuples,
            ordered by title.

        Raises
        ------
        ValidationError
            If tag name is empty or invalid.
        DatabaseError
            If there is a database error.
        """
        validated_name = validate_search_parameters(tag_name, 100)
        normalized_name = self._normalize_text(validated_name)

        try:
            with database_connection(self.db_path) as conn:
                cursor = conn.cursor()

                # Get all tags and find matching ones
                query = 'SELECT id, name FROM tags'
                cursor.execute(query)
                all_tags = cursor.fetchall()

                # Find tags matching the normalized name
                matching_tag_ids = []
                for tag_id, tag_name_db in all_tags:
                    if self._normalize_text(tag_name_db).lower() == \
                       normalized_name.lower():
                        matching_tag_ids.append(tag_id)

                if not matching_tag_ids:
                    raise NotFoundError('books', validated_name, 'tag name')

                # Get books for matching tags
                placeholders = ','.join('?' * len(matching_tag_ids))
                query = f"""
                    SELECT DISTINCT b.id, b.title,
                           COALESCE(GROUP_CONCAT(a.name, ' & '), '')
                           as authors,
                           b.pubdate
                    FROM books b
                    JOIN books_tags_link btl ON b.id = btl.book
                    JOIN tags t ON btl.tag = t.id
                    LEFT JOIN books_authors_link bal ON b.id = bal.book
                    LEFT JOIN authors a ON bal.author = a.id
                    WHERE t.id IN ({placeholders})
                    GROUP BY b.id, b.title, b.pubdate
                    ORDER BY b.title
                """

                cursor.execute(query, matching_tag_ids)
                results = cursor.fetchall()

        except sqlite3.Error as e:
            raise DatabaseError(
                f'Query execution failed: {e}',
                'tag books search'
            )

        if not results:
            raise NotFoundError('books', validated_name, 'tag name')

        return results

    def get_all_tags(self) -> List[Tuple[int, str]]:
        """
        Get all available tags in the database.

        Returns
        -------
        List[Tuple[int, str]]
            List of (tag_id, tag_name) tuples, ordered alphabetically by name.

        Raises
        ------
        DatabaseError
            If there is a database error.
        """
        query = 'SELECT t.id, t.name FROM tags t ORDER BY t.name'

        return self._execute_search_query(
            query,
            (),
            'get all tags'
        )

    def get_book_count(self) -> int:
        """
        Get the total number of books in the database.

        Returns
        -------
        int
            Total number of books.

        Raises
        ------
        DatabaseError
            If there is a database error.
        """
        query = 'SELECT COUNT(*) FROM books'

        results = self._execute_search_query(
            query,
            (),
            'book count'
        )

        return int(results[0][0]) if results else 0

    def get_author_count(self) -> int:
        """
        Get the total number of authors in the database.

        Returns
        -------
        int
            Total number of authors.

        Raises
        ------
        DatabaseError
            If there is a database error.
        """
        query = 'SELECT COUNT(*) FROM authors'

        results = self._execute_search_query(
            query,
            (),
            'author count'
        )

        return int(results[0][0]) if results else 0

    def get_database_info(self) -> Dict[str, Any]:
        """
        Get comprehensive information about the database.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing database statistics and information.

        Raises
        ------
        DatabaseError
            If there is a database error.
        """
        try:
            info = {
                'db_path': self.db_path,
                'library_path': self.library_path,
                'books_count': self.get_book_count(),
                'authors_count': self.get_author_count(),
            }

            # Get additional counts in a single connection
            with database_connection(self.db_path) as conn:
                cursor = conn.cursor()

                # Get series count
                cursor.execute('SELECT COUNT(*) FROM series')
                info['series_count'] = cursor.fetchone()[0]

                # Get publishers count
                cursor.execute('SELECT COUNT(*) FROM publishers')
                info['publishers_count'] = cursor.fetchone()[0]

                # Get tags count
                cursor.execute('SELECT COUNT(*) FROM tags')
                info['tags_count'] = cursor.fetchone()[0]

                # Get languages count
                cursor.execute('SELECT COUNT(*) FROM languages')
                info['languages_count'] = cursor.fetchone()[0]

            return info

        except sqlite3.Error as e:
            raise DatabaseError(
                f'Failed to retrieve database information: {e}',
                'database info'
            )
