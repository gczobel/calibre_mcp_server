"""The legacy list tools at the tool boundary.

Two things only the boundary can show: a capped search that matches nothing must
still render in the response — a bare empty list renders no content block at all,
which is what #19 fixed for ``find_books`` — and the descriptions a caller
actually reads must state how the pattern is matched.
"""

import asyncio

from fastmcp import Client

from calibre_mcp_server.calibre_api import DEFAULT_SEARCH_LIMIT


def test_no_title_match_returns_a_visible_zero_count(call_tool, parse_payload):
    result = call_tool("search_books_by_title", {"title_pattern": "Nope%"})

    assert result.content, "an empty match must still render content"
    assert parse_payload(result) == {"count": 0, "books": []}


def test_no_tag_match_is_not_a_tool_error(call_tool, parse_payload):
    result = call_tool("get_books_by_tag", {"tag_name": "no-such-tag"})

    assert parse_payload(result) == {"count": 0, "books": []}


def test_no_author_match_is_not_a_tool_error(call_tool, parse_payload):
    result = call_tool(
        "get_books_by_author", {"author_name": "Nobody At All"}
    )

    assert parse_payload(result) == {"count": 0, "books": []}


def test_the_default_limit_applies_through_the_tool(
    library, call_tool, parse_payload
):
    for i in range(DEFAULT_SEARCH_LIMIT + 5):
        library.add_book(f"Python Book {i:02d}")

    payload = parse_payload(
        call_tool("search_books_by_title", {"title_pattern": "Python%"})
    )

    assert payload["count"] == DEFAULT_SEARCH_LIMIT
    assert len(payload["books"]) == DEFAULT_SEARCH_LIMIT


def test_an_explicit_limit_is_honoured_through_the_tool(
    library, call_tool, parse_payload
):
    for i in range(10):
        library.add_book(f"Python Book {i:02d}")

    payload = parse_payload(call_tool(
        "search_books_by_title", {"title_pattern": "Python%", "limit": 3}
    ))

    assert payload["count"] == 3


def test_authors_are_reported_under_authors(
    library, call_tool, parse_payload
):
    book_id = library.add_book("A Book")
    author_id = library.add_author("Jane Doe")
    library.link_author(book_id, author_id)

    payload = parse_payload(
        call_tool("search_authors_by_name", {"name_pattern": "Jane%"})
    )

    assert payload == {"count": 1, "authors": [{"id": author_id, "name": "Jane Doe"}]}


def test_descriptions_state_how_the_pattern_is_matched(bound_server):
    """The rule a caller has to know before choosing a pattern."""
    async def descriptions():
        async with Client(bound_server.mcp) as client:
            tools = await client.list_tools()
            return {tool.name: (tool.description or "") for tool in tools}

    text = asyncio.run(descriptions())

    for name in (
        "search_books_by_title",
        "search_authors_by_name",
        "search_books_by_tag_pattern",
    ):
        assert "anchored" in text[name].lower(), name
