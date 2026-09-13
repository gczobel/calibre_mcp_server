"""
Calibre MCP Server - A Model Context Protocol server for Calibre e-book.

This server provides tools to interact with a Calibre e-book library,
allowing search and retrieval of book metadata through the MCP protocol.
"""

import logging
from typing import Dict, List, Any, Optional, NoReturn
from typing import Annotated

from .calibre_api import Book, CalibreDB, DEFAULT_SEARCH_LIMIT
from .config import config
from .exceptions import (
    DatabaseError,
    ValidationError,
    NotFoundError,
    ConfigurationError
)
from .validation import (
    validate_search_parameters,
    validate_positive_integer
)

from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError
from pydantic import Field


# Configure logging
logger = logging.getLogger(__name__)

# Initialize FastMCP server with configuration
mcp = FastMCP(name=config.server_name)

# Initialize CalibreDB instance
try:
    calibre_db = CalibreDB(
        config.calibre_library_path,
        read_column_label=config.read_column_label
    )
    logger.info(
        f"Calibre database initialized at: {config.calibre_library_path}"
    )
except Exception as e:
    logger.error(f"Failed to initialize Calibre database: {e}")
    raise


class CalibreToolHandler:
    """Handler class for Calibre MCP tools with centralized error handling."""

    @staticmethod
    async def handle_error(
        operation: str,
        error: Exception,
        search_term: Optional[str] = None,
        ctx: Optional[Context] = None
    ) -> NoReturn:
        """
        Centralized error handling for all operations.

        Parameters
        ----------
        operation : str
            The operation being performed.
        error : Exception
            The exception that was raised.
        search_term : str, optional
            The search term used, by default None.
        ctx : Context, optional
            The MCP context for logging, by default None.

        Raises
        ------
        ToolError
            Formatted error for MCP client.
        """
        error_msg = str(error)

        # Log error to context if available
        if ctx:
            if search_term:
                await ctx.error(
                    f"Error in {operation} for '{search_term}': {error_msg}"
                )
            else:
                await ctx.error(f"Error in {operation}: {error_msg}")

        # Also log to standard logger for server-side debugging
        logger.error(f"Error in {operation}: {error}")

        if isinstance(
            error, (ValueError, ValidationError, ConfigurationError)
        ):
            raise ToolError(str(error))
        elif isinstance(error, (DatabaseError, NotFoundError)):
            raise ToolError(str(error))
        else:
            if search_term:
                raise ToolError(
                    f"Database error occurred while {operation} "
                    f"for '{search_term}': {str(error)}"
                )
            else:
                raise ToolError(
                    f"Database error occurred during {operation}: "
                    f"{str(error)}"
                )

    @staticmethod
    def format_simple_results(
        results: List[tuple],
        id_key: str = "id",
        value_key: str = "name"
    ) -> List[Dict[str, Any]]:
        """
        Format simple id, value tuple results.

        Parameters
        ----------
        results : List[tuple]
            Raw database results with (id, value) structure.
        id_key : str, optional
            Key name for ID field, by default "id".
        value_key : str, optional
            Key name for value field, by default "name".

        Returns
        -------
        List[Dict[str, Any]]
            Formatted dictionaries.
        """
        return [{id_key: item[0], value_key: item[1]} for item in results]

    @staticmethod
    def format_book_search_results(
        results: List[tuple],
        context: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Format book search results with appropriate context.

        Parameters
        ----------
        results : List[tuple]
            Raw database results.
        context : str, optional
            Additional context information, by default None.

        Returns
        -------
        List[Dict[str, Any]]
            Formatted book dictionaries.
        """
        books = []
        for result in results:
            book_dict = {
                "id": result[0],
                "title": result[1],
            }

            # Handle different result formats based on length
            if len(result) == 4:  # author or tag search results
                book_dict["authors"] = result[2] or ""
                book_dict["publication_date"] = result[3] or ""
                if context:
                    book_dict["context"] = context
            elif len(result) == 3:  # series search results
                book_dict["series_index"] = result[2] or 0.0
                if context:
                    book_dict["series_name"] = context

            books.append(book_dict)
        return books


#############################################
# Search Tools
#############################################


@mcp.tool(
    name="search_books_by_title",
    description=(
        "Search books by title. A trailing % matches any ending "
        "('Python%'), a leading one any beginning ('%Django'), both "
        "match anywhere ('%Django%'); with no %, the title must match "
        "exactly. Case-insensitive, accents ignored except ñ and ç. "
        "Returns a count and up to limit books; no match returns "
        "count 0, not an error."
    ),
    tags={"search", "books", "title"},
    annotations={
        "title": "Search Books by Title",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def search_books_by_title(
    title_pattern: Annotated[str, Field(
        description=(
            "Title pattern to search for (use % for wildcards, "
            "e.g., 'Python%' or '%Django%')"
        ),
        min_length=1,
        max_length=200
    )],
    limit: Annotated[int, Field(
        description="Maximum number of results to return",
        gt=0
    )] = DEFAULT_SEARCH_LIMIT,
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Search for books by title using pattern matching.

    Parameters
    ----------
    title_pattern : str
        Pattern to search in book titles. Supports SQL LIKE wildcards (%).

    limit : int, optional
        Maximum number of results, default 50.

    Returns
    -------
    Dict[str, Any]
        ``count`` of matches and ``books``, each carrying its own
        fields. Empty when nothing matches.

    Raises
    ------
    ToolError
        If search fails or the database cannot be read.
    """
    try:
        await ctx.info(f"Searching books by title pattern: '{title_pattern}'")

        validated_pattern = validate_search_parameters(title_pattern)
        results = calibre_db.search_books_by_title(validated_pattern, limit)

        await ctx.info(f"Found {len(results)} books matching title pattern")
        formatted_results = CalibreToolHandler.format_simple_results(
            results, "id", "title"
        )

        await ctx.debug(
            f"Returning {len(formatted_results)} formatted results"
        )
        return {"count": len(formatted_results), "books": formatted_results}

    except Exception as e:
        await CalibreToolHandler.handle_error(
            "searching books by title", e, title_pattern, ctx
        )


@mcp.tool(
    name="search_authors_by_name",
    description=(
        "Search authors by stored name, under the same pattern rule: a "
        "trailing % matches any ending ('Asimov%'), a leading one any "
        "beginning, both match anywhere, and with no % the name must "
        "match exactly. Case-insensitive, accents ignored except ñ and ç. "
        "Returns a count and up to limit authors; no match returns "
        "count 0, not an error."
    ),
    tags={"search", "authors", "name"},
    annotations={
        "title": "Search Authors by Name",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def search_authors_by_name(
    name_pattern: Annotated[str, Field(
        description=(
            "Author name pattern to search for (use % for wildcards, "
            "e.g., 'Stephen%' or '%King%')"
        ),
        min_length=1,
        max_length=200
    )],
    limit: Annotated[int, Field(
        description="Maximum number of results to return",
        gt=0
    )] = DEFAULT_SEARCH_LIMIT,
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Search for authors by name using pattern matching.

    Parameters
    ----------
    name_pattern : str
        Pattern to search in author names. Supports SQL LIKE wildcards (%).

    limit : int, optional
        Maximum number of results, default 50.

    Returns
    -------
    Dict[str, Any]
        ``count`` of matches and ``authors``, each carrying its own
        fields. Empty when nothing matches.

    Raises
    ------
    ToolError
        If search fails or the database cannot be read.
    """
    try:
        await ctx.info(f"Searching authors by name pattern: '{name_pattern}'")

        validated_pattern = validate_search_parameters(name_pattern)
        results = calibre_db.search_authors_by_name(validated_pattern, limit)

        await ctx.info(f"Found {len(results)} authors matching name pattern")
        formatted_results = CalibreToolHandler.format_simple_results(results)

        await ctx.debug(
            f"Returning {len(formatted_results)} formatted results"
        )
        return {"count": len(formatted_results), "authors": formatted_results}

    except Exception as e:
        await CalibreToolHandler.handle_error(
            "searching authors by name", e, name_pattern, ctx
        )


@mcp.tool(
    name="get_books_by_author",
    description=(
        "Get books by an exact author name, matched case-insensitively; "
        "accents are ignored except ñ and ç, which are significant. "
        "Capped by limit; use the author ID tool when a name is "
        "ambiguous. An unknown name returns count 0, not an error."
    ),
    tags={"search", "books", "author"},
    annotations={
        "title": "Get Books by Author",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def get_books_by_author(
    author_name: Annotated[str, Field(
        description="Exact name of the author to search for",
        min_length=1,
        max_length=200
    )],
    limit: Annotated[int, Field(
        description="Maximum number of results to return",
        gt=0
    )] = DEFAULT_SEARCH_LIMIT,
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Get detailed information about all books by a specific author.

    Parameters
    ----------
    author_name : str
        Exact name of the author.

    limit : int, optional
        Maximum number of results, default 50.

    Returns
    -------
    Dict[str, Any]
        ``count`` of matches and ``books``, each carrying its own
        fields. Empty when nothing matches.

    Raises
    ------
    ToolError
        If the database cannot be read.
    """
    try:
        await ctx.info(f"Getting books by author: '{author_name}'")

        validated_name = validate_search_parameters(author_name)
        results = calibre_db.get_books_by_author(validated_name, limit)

        if not results:
            await ctx.warning(f"No books found for author: '{validated_name}'")

        await ctx.info(f"Found {len(results)} books by author")

        books = []
        for book_id, title, pub_date, series_info in results:
            books.append({
                "id": book_id,
                "title": title,
                "publication_date": pub_date or "",
                "series_info": series_info or "",
                "author": validated_name
            })

        await ctx.debug(f"Returning {len(books)} book records")
        return {"count": len(books), "books": books}

    except Exception as e:
        await CalibreToolHandler.handle_error(
            "getting books by author", e, author_name, ctx
        )


@mcp.tool(
    name="get_books_by_author_id",
    description=(
        "Get books by author ID, capped by limit. An unknown ID returns "
        "count 0, not an error."
    ),
    tags={"search", "books", "author", "id"},
    annotations={
        "title": "Get Books by Author ID",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def get_books_by_author_id(
    author_id: Annotated[int, Field(
        description="Unique ID of the author in the Calibre database",
        gt=0
    )],
    limit: Annotated[int, Field(
        description="Maximum number of results to return",
        gt=0
    )] = DEFAULT_SEARCH_LIMIT,
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Get detailed information about all books by a specific author ID.

    Parameters
    ----------
    author_id : int
        Unique ID of the author in the database.

    limit : int, optional
        Maximum number of results, default 50.

    Returns
    -------
    Dict[str, Any]
        ``count`` of matches and ``books``, each carrying its own
        fields. Empty when nothing matches.

    Raises
    ------
    ToolError
        If the database cannot be read.
    """
    try:
        await ctx.info(f"Getting books by author ID: {author_id}")

        validated_id = validate_positive_integer(author_id, "author_id")
        results = calibre_db.get_books_by_author_id(validated_id, limit)

        await ctx.info(f"Found {len(results)} books by author ID")

        books = []
        for book_id, title, pub_date, series_info in results:
            books.append({
                "id": book_id,
                "title": title,
                "publication_date": pub_date or "",
                "series_info": series_info or "",
                "author_id": validated_id
            })

        await ctx.debug(f"Returning {len(books)} book records")
        return {"count": len(books), "books": books}

    except Exception as e:
        await CalibreToolHandler.handle_error(
            "getting books by author ID", e, str(author_id), ctx
        )


@mcp.tool(
    name="get_books_by_series",
    description=(
        "Get the books in a series, ordered by series index and capped "
        "by limit. The name is matched exactly and case-insensitively, "
        "accents ignored except ñ and ç. An unknown series returns "
        "count 0, not an error."
    ),
    tags={"search", "books", "series"},
    annotations={
        "title": "Get Books by Series",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def get_books_by_series(
    series_name: Annotated[str, Field(
        description="Exact name of the series to search for",
        min_length=1,
        max_length=200
    )],
    limit: Annotated[int, Field(
        description="Maximum number of results to return",
        gt=0
    )] = DEFAULT_SEARCH_LIMIT,
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Get all books in a specific series ordered by series index.

    Parameters
    ----------
    series_name : str
        Exact name of the series.

    limit : int, optional
        Maximum number of results, default 50.

    Returns
    -------
    Dict[str, Any]
        ``count`` of matches and ``books``, each carrying its own
        fields. Empty when nothing matches.

    Raises
    ------
    ToolError
        If the database cannot be read.
    """
    try:
        await ctx.info(f"Getting books in series: '{series_name}'")

        validated_name = validate_search_parameters(series_name)
        results = calibre_db.get_books_by_series(validated_name, limit)

        await ctx.info(f"Found {len(results)} books in series")

        books = []
        for book_id, title, series_index in results:
            books.append({
                "id": book_id,
                "title": title,
                "series_index": series_index or 0.0,
                "series_name": validated_name
            })

        await ctx.debug(f"Returning {len(books)} series books")
        return {"count": len(books), "books": books}

    except Exception as e:
        await CalibreToolHandler.handle_error(
            "getting books by series", e, series_name, ctx
        )


@mcp.tool(
    name="get_books_by_tag",
    description=(
        "Get books carrying an exact tag name, matched case-insensitively "
        "with accents ignored except ñ and ç, and capped by limit. A "
        "common tag matches thousands of books, so use find_books to "
        "combine criteria. An unknown tag returns count 0, not an error."
    ),
    tags={"search", "books", "tags"},
    annotations={
        "title": "Get Books by Tag",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def get_books_by_tag(
    tag_name: Annotated[str, Field(
        description="Exact name of the tag to search for",
        min_length=1,
        max_length=100
    )],
    limit: Annotated[int, Field(
        description="Maximum number of results to return",
        gt=0
    )] = DEFAULT_SEARCH_LIMIT,
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Get detailed information about all books with a specific tag.

    Parameters
    ----------
    tag_name : str
        Exact name of the tag.

    limit : int, optional
        Maximum number of results, default 50.

    Returns
    -------
    Dict[str, Any]
        ``count`` of matches and ``books``, each carrying its own
        fields. Empty when nothing matches.

    Raises
    ------
    ToolError
        If the database cannot be read.
    """
    try:
        await ctx.info(f"Getting books with tag: '{tag_name}'")

        validated_name = validate_search_parameters(tag_name, 100)
        results = calibre_db.get_books_by_tag(validated_name, limit)

        await ctx.info(f"Found {len(results)} books with tag")

        books = []
        for book_id, title, authors, pub_date in results:
            books.append({
                "id": book_id,
                "title": title,
                "authors": authors or "",
                "publication_date": pub_date or "",
                "tag": validated_name
            })

        await ctx.debug(f"Returning {len(books)} tagged books")
        return {"count": len(books), "books": books}

    except Exception as e:
        await CalibreToolHandler.handle_error(
            "getting books by tag", e, tag_name, ctx
        )


@mcp.tool(
    name="search_books_by_tag_pattern",
    description=(
        "Find books whose tags match a pattern: a trailing % matches any "
        "ending ('sci%'), a leading one any beginning, both match "
        "anywhere, and with no % the tag must match exactly. "
        "Case-insensitive, accents ignored except ñ and ç. A common tag "
        "matches thousands of books, so the result is capped by limit; no "
        "match returns count 0, not an error."
    ),
    tags={"search", "books", "tags", "pattern"},
    annotations={
        "title": "Search Books by Tag Pattern",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def search_books_by_tag_pattern(
    tag_pattern: Annotated[str, Field(
        description=(
            "Tag pattern to search for (use % for wildcards, "
            "e.g., 'sci%' or '%fiction%')"
        ),
        min_length=1,
        max_length=100
    )],
    limit: Annotated[int, Field(
        description="Maximum number of results to return",
        gt=0
    )] = DEFAULT_SEARCH_LIMIT,
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Search for books with tags matching a pattern.

    Parameters
    ----------
    tag_pattern : str
        Pattern to search in tag names. Supports SQL LIKE wildcards (%).

    limit : int, optional
        Maximum number of results, default 50.

    Returns
    -------
    Dict[str, Any]
        ``count`` of matches and ``books``, each carrying its own
        fields. Empty when nothing matches.

    Raises
    ------
    ToolError
        If no books found or database error occurs.
    """
    try:
        await ctx.info(f"Searching books by tag pattern: '{tag_pattern}'")

        validated_pattern = validate_search_parameters(tag_pattern, 100)
        results = calibre_db.search_books_by_tag(validated_pattern, limit)

        await ctx.info(f"Found {len(results)} books matching tag pattern")

        books = []
        for book_id, title, authors, pub_date in results:
            books.append({
                "id": book_id,
                "title": title,
                "authors": authors or "",
                "publication_date": pub_date or "",
                "matching_tag_pattern": validated_pattern
            })

        await ctx.debug(f"Returning {len(books)} pattern-matched books")
        return {"count": len(books), "books": books}

    except Exception as e:
        await CalibreToolHandler.handle_error(
            "searching books by tag pattern", e, tag_pattern, ctx
        )


#############################################
# Book Information Tools
#############################################


@mcp.tool(
    name="get_book_details",
    description="Get complete details for a specific book by ID",
    tags={"book", "details", "metadata"},
    annotations={
        "title": "Get Book Details",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def get_book_details(
    book_id: Annotated[int, Field(
        description="Unique ID of the book in the Calibre database",
        gt=0
    )],
    ctx: Context
) -> Dict[str, Any]:
    """
    Get complete metadata for a specific book.

    Parameters
    ----------
    book_id : int
        Unique ID of the book in the Calibre database.

    Returns
    -------
    Dict[str, Any]
        Complete book metadata including title, author, series, tags, etc.

    Raises
    ------
    ToolError
        If book not found or database error occurs.
    """
    try:
        await ctx.info(f"Getting details for book ID: {book_id}")

        validated_id = validate_positive_integer(book_id, "book_id")
        book = Book(
            validated_id,
            config.calibre_library_path,
            read_column_label=config.read_column_label
        )
        book_details = book.to_json()

        book_title = book_details.get('title', 'Unknown')
        await ctx.debug(f"Retrieved details for book: '{book_title}'")
        return book_details

    except Exception as e:
        await CalibreToolHandler.handle_error(
            "getting book details", e, str(book_id), ctx
        )


#############################################
# Read Status and Rating Tools
#############################################


@mcp.tool(
    name="mark_book_read",
    description=(
        "Mark a book as read by writing 1 to the #read custom column. "
        "Idempotent."
    ),
    tags={"book", "read", "write"},
    annotations={
        "title": "Mark Book Read",
        "readOnlyHint": False,
        "openWorldHint": False
    }
)
async def mark_book_read(
    book_id: Annotated[int, Field(
        description="Unique ID of the book in the Calibre database",
        gt=0
    )],
    ctx: Context
) -> Dict[str, Any]:
    """
    Mark a book as read.

    Parameters
    ----------
    book_id : int
        Unique ID of the book in the database.

    Returns
    -------
    Dict[str, Any]
        The book ID and its new read state.

    Raises
    ------
    ToolError
        If the read column is missing or the book does not exist.
    """
    try:
        await ctx.info(f"Marking book {book_id} as read")

        validated_id = validate_positive_integer(book_id, "book_id")
        result = calibre_db.mark_book_read(validated_id)

        await ctx.info(f"Marked book {validated_id} as read")
        return result

    except Exception as e:
        await CalibreToolHandler.handle_error(
            "marking book read", e, str(book_id), ctx
        )


@mcp.tool(
    name="mark_book_unread",
    description=(
        "Mark a book as unread by writing 0 to the #read custom column. "
        "Idempotent."
    ),
    tags={"book", "read", "write"},
    annotations={
        "title": "Mark Book Unread",
        "readOnlyHint": False,
        "openWorldHint": False
    }
)
async def mark_book_unread(
    book_id: Annotated[int, Field(
        description="Unique ID of the book in the Calibre database",
        gt=0
    )],
    ctx: Context
) -> Dict[str, Any]:
    """
    Mark a book as unread.

    Parameters
    ----------
    book_id : int
        Unique ID of the book in the database.

    Returns
    -------
    Dict[str, Any]
        The book ID and its new read state.

    Raises
    ------
    ToolError
        If the read column is missing or the book does not exist.
    """
    try:
        await ctx.info(f"Marking book {book_id} as unread")

        validated_id = validate_positive_integer(book_id, "book_id")
        result = calibre_db.mark_book_unread(validated_id)

        await ctx.info(f"Marked book {validated_id} as unread")
        return result

    except Exception as e:
        await CalibreToolHandler.handle_error(
            "marking book unread", e, str(book_id), ctx
        )


@mcp.tool(
    name="set_book_rating",
    description=(
        "Set a book's rating to a whole number of stars from 1 to 5, "
        "or clear it with 0"
    ),
    tags={"book", "rating", "write"},
    annotations={
        "title": "Set Book Rating",
        "readOnlyHint": False,
        "openWorldHint": False
    }
)
async def set_book_rating(
    book_id: Annotated[int, Field(
        description="Unique ID of the book in the Calibre database",
        gt=0
    )],
    stars: Annotated[int, Field(
        description="Rating in whole stars, from 1 to 5, or 0 to clear",
        ge=0,
        le=5,
        # Lax coercion reads false as 0, which would clear a rating by
        # accident. The CalibreDB seam rejects booleans too, so be strict
        # here as well rather than letting the tool accept what the domain
        # calls invalid.
        strict=True
    )],
    ctx: Context
) -> Dict[str, Any]:
    """
    Set a book's rating.

    Parameters
    ----------
    book_id : int
        Unique ID of the book in the database.
    stars : int
        Rating in whole stars, from 1 to 5, or 0 to clear the rating.

    Returns
    -------
    Dict[str, Any]
        The book ID and its new rating, or ``None`` when cleared.

    Raises
    ------
    ToolError
        If the stars are out of range or the book does not exist.
    """
    try:
        await ctx.info(f"Setting rating {stars} for book {book_id}")

        validated_id = validate_positive_integer(book_id, "book_id")
        result = calibre_db.set_book_rating(validated_id, stars)

        await ctx.info(f"Set rating {stars} for book {validated_id}")
        return result

    except Exception as e:
        await CalibreToolHandler.handle_error(
            "setting book rating", e, str(book_id), ctx
        )


#############################################
# Find Books Tool
#############################################


@mcp.tool(
    name="find_books",
    description=(
        "Find books matching optional criteria (author, tag, series, "
        "rating range, read state), combined with AND. Text criteria "
        "match as substrings, case-insensitively except for ñ and ç. "
        "Returns the number of matches alongside the matching books; no "
        "match returns count 0, not an error."
    ),
    tags={"search", "books", "filter"},
    annotations={
        "title": "Find Books",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def find_books(
    author: Annotated[Optional[str], Field(
        description=(
            "Filter by author (case- and accent-insensitive substring)"
        )
    )] = None,
    tag: Annotated[Optional[str], Field(
        description="Filter by tag (case- and accent-insensitive substring)"
    )] = None,
    series: Annotated[Optional[str], Field(
        description="Filter by series (case- and accent-insensitive substring)"
    )] = None,
    rating_min: Annotated[Optional[int], Field(
        description="Minimum rating in whole stars (1-5)",
        ge=1,
        le=5
    )] = None,
    rating_max: Annotated[Optional[int], Field(
        description="Maximum rating in whole stars (1-5)",
        ge=1,
        le=5
    )] = None,
    read: Annotated[Optional[bool], Field(
        description="True for read books only, False for unread only"
    )] = None,
    limit: Annotated[int, Field(
        description="Maximum number of books to return",
        gt=0
    )] = 20,
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Find books matching the given criteria.

    Parameters
    ----------
    author, tag, series : str, optional
        Text criteria, matched case- and accent-insensitively.
    rating_min, rating_max : int, optional
        Rating bounds in whole stars, inclusive.
    read : bool, optional
        True for read only, False for unread only.
    limit : int, optional
        Maximum number of results, default 20.

    Returns
    -------
    Dict[str, Any]
        ``count`` of matches, and ``books`` each with id, title, author,
        series, rating and read. No matches is ``{"count": 0, "books": []}``,
        so an empty result is always visible to the caller.

    Raises
    ------
    ToolError
        If the criteria are invalid or a database error occurs.
    """
    try:
        await ctx.info("Finding books with the given criteria")

        results = calibre_db.find_books(
            author=author,
            tag=tag,
            series=series,
            rating_min=rating_min,
            rating_max=rating_max,
            read=read,
            limit=limit,
        )

        await ctx.info(f"Found {len(results)} books")
        return {"count": len(results), "books": results}

    except Exception as e:
        await CalibreToolHandler.handle_error(
            "finding books", e, None, ctx
        )


#############################################
# Library Information Tools
#############################################


@mcp.tool(
    name="get_library_stats",
    description="Get comprehensive statistics about the Calibre library",
    tags={"library", "statistics", "info"},
    annotations={
        "title": "Get Library Statistics",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def get_library_stats(ctx: Context) -> Dict[str, Any]:
    """
    Get comprehensive statistics about the Calibre library.

    Returns
    -------
    Dict[str, Any]
        Dictionary containing library statistics and information.

    Raises
    ------
    ToolError
        If database error occurs.
    """
    try:
        await ctx.info("Getting library statistics")

        stats = calibre_db.get_database_info()

        total_books = stats.get('books_count', 0)
        await ctx.debug(f"Library contains {total_books} books")
        return stats

    except Exception as e:
        await CalibreToolHandler.handle_error(
            "getting library statistics", e, None, ctx
        )


@mcp.tool(
    name="get_all_tags",
    description=(
        "Get every tag in the Calibre library, with a count. Tags are "
        "ordered alphabetically."
    ),
    tags={"tags", "library", "list"},
    annotations={
        "title": "Get All Tags",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def get_all_tags(ctx: Context) -> Dict[str, Any]:
    """
    Get all available tags in the Calibre library.

    Returns
    -------
    Dict[str, Any]
        ``count`` of tags and ``tags``, each with an ID and a name,
        ordered alphabetically. Empty when the library has no tags.

    Raises
    ------
    ToolError
        If database error occurs.
    """
    try:
        await ctx.info("Getting all available tags")

        results = calibre_db.get_all_tags()
        formatted_results = CalibreToolHandler.format_simple_results(results)

        await ctx.debug(f"Found {len(formatted_results)} tags")
        return {"count": len(formatted_results), "tags": formatted_results}

    except Exception as e:
        await CalibreToolHandler.handle_error(
            "getting all tags", e, None, ctx
        )


def main() -> None:
    """
    Run the MCP server.

    The server uses the transport mode configured in the config module.
    Default is stdio for local MCP integration. HTTP mode can be used
    for network serving in container environments.
    """
    if config.transport_mode.lower() == "http":
        logger.info(
            f"Starting HTTP server on {config.http_host}:{config.http_port}"
        )
        mcp.run(
            transport="http",
            host=config.http_host,
            port=config.http_port
        )
    else:
        logger.info("Starting server with stdio transport")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
