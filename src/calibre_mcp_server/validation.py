"""
Validation schemas and utilities for Calibre MCP Server.

This module provides Pydantic models and validation functions for
input parameters and data structures used in the Calibre MCP Server.
"""

from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


class SearchParameters(BaseModel):
    """Base model for search parameters with common validations."""

    pattern: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Search pattern (supports % wildcards)"
    )

    @field_validator('pattern')
    def validate_pattern_not_empty(cls, v: str) -> str:
        """Ensure pattern is not just whitespace."""
        if not v or not v.strip():
            raise ValueError("Search pattern cannot be empty or whitespace")
        return v.strip()


class TitleSearchParameters(SearchParameters):
    """Validation schema for title search parameters."""

    pattern: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description=(
            "Title pattern to search for (use % for wildcards, "
            "e.g., 'Python%' or '%Django%')"
        )
    )


class AuthorSearchParameters(SearchParameters):
    """Validation schema for author search parameters."""

    pattern: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description=(
            "Author name pattern to search for (use % for wildcards, "
            "e.g., 'Stephen%' or '%King%')"
        )
    )


class TagSearchParameters(SearchParameters):
    """Validation schema for tag search parameters."""

    pattern: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description=(
            "Tag pattern to search for (use % for wildcards, "
            "e.g., 'sci%' or '%fiction%')"
        )
    )


class BookIdParameters(BaseModel):
    """Validation schema for book ID parameters."""

    book_id: int = Field(
        ...,
        gt=0,
        description="Unique ID of the book in the Calibre database"
    )


class AuthorIdParameters(BaseModel):
    """Validation schema for author ID parameters."""

    author_id: int = Field(
        ...,
        gt=0,
        description="Unique ID of the author in the Calibre database"
    )


class ExactNameParameters(BaseModel):
    """Base model for exact name parameters."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Exact name to search for"
    )

    @field_validator('name')
    def validate_name_not_empty(cls, v: str) -> str:
        """Ensure name is not just whitespace."""
        if not v or not v.strip():
            raise ValueError("Name cannot be empty or whitespace")
        return v.strip()


class AuthorNameParameters(ExactNameParameters):
    """Validation schema for exact author name parameters."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Exact name of the author to search for"
    )


class SeriesNameParameters(ExactNameParameters):
    """Validation schema for exact series name parameters."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Exact name of the series to search for"
    )


class TagNameParameters(ExactNameParameters):
    """Validation schema for exact tag name parameters."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Exact name of the tag to search for"
    )


class BookResponse(BaseModel):
    """Response model for book information."""

    id: int
    title: str
    authors: Optional[str] = None
    publication_date: Optional[str] = None
    series_info: Optional[str] = None
    series_name: Optional[str] = None
    series_index: Optional[float] = None
    tag: Optional[str] = None
    author: Optional[str] = None
    author_id: Optional[int] = None
    matching_tag_pattern: Optional[str] = None


class AuthorResponse(BaseModel):
    """Response model for author information."""

    id: int
    name: str


class TagResponse(BaseModel):
    """Response model for tag information."""

    id: int
    name: str


class LibraryStatsResponse(BaseModel):
    """Response model for library statistics."""

    db_path: str
    books_count: int
    authors_count: int
    series_count: int
    publishers_count: int
    tags_count: int
    languages_count: int


class BookDetailResponse(BaseModel):
    """Response model for detailed book information."""

    id: int
    title: str
    title_sort: str
    date: str
    author: str
    author_sort: str
    series: str
    series_sort: str
    series_idx: float
    publisher: str
    identifiers: str
    language: str
    tags: str
    synopsis: str


def validate_search_parameters(
    pattern: str,
    max_length: int = 200
) -> str:
    """
    Validate search pattern parameters.

    Parameters
    ----------
    pattern : str
        The search pattern to validate.
    max_length : int, optional
        Maximum allowed length for the pattern, by default 200.

    Returns
    -------
    str
        The validated and cleaned pattern.

    Raises
    ------
    ValueError
        If the pattern is invalid.
    """
    if not pattern or not isinstance(pattern, str):
        raise ValueError("Pattern must be a non-empty string")

    cleaned_pattern = pattern.strip()
    if not cleaned_pattern:
        raise ValueError("Pattern cannot be empty or whitespace")

    if len(cleaned_pattern) > max_length:
        raise ValueError(
            f"Pattern length ({len(cleaned_pattern)}) exceeds maximum "
            f"allowed length ({max_length})"
        )

    return cleaned_pattern


def validate_positive_integer(value: Any, name: str = "value") -> int:
    """
    Validate that a value is a positive integer.

    Parameters
    ----------
    value : Any
        The value to validate.
    name : str, optional
        The name of the parameter for error messages, by default "value".

    Returns
    -------
    int
        The validated integer.

    Raises
    ------
    ValueError
        If the value is not a positive integer.
    """
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")

    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")

    return value


def validate_rating_stars(value: Any, allow_zero: bool = False) -> int:
    """
    Validate that a value is a whole number of stars between 1 and 5.

    Parameters
    ----------
    value : Any
        The candidate star count.
    allow_zero : bool, optional
        Accept ``0`` as well, for callers where zero means "no rating" rather
        than "invalid". Rating bounds never allow it.

    Returns
    -------
    int
        The validated star count.

    Raises
    ------
    ValueError
        If the value is not an integer in the allowed range.
    """
    lowest = 0 if allow_zero else 1
    message = f"stars must be a whole number between {lowest} and 5"

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(message)

    if value < lowest or value > 5:
        raise ValueError(message)

    return value
