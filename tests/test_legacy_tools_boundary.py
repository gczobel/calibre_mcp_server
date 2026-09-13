"""The legacy list tools at the tool boundary.

Two things only the boundary can show: a capped search that matches nothing must
still render in the response — a bare empty list renders no content block at all,
which is what #19 fixed for ``find_books`` — and the descriptions a caller
actually reads must state how the pattern is matched.
"""

import asyncio

import pytest
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


def _descriptions(bound_server):
    async def fetch():
        async with Client(bound_server.mcp) as client:
            tools = await client.list_tools()
            return {tool.name: (tool.description or "") for tool in tools}

    return asyncio.run(fetch())


PATTERN_TOOLS = (
    "search_books_by_title",
    "search_authors_by_name",
    "search_books_by_tag_pattern",
)

NAME_TOOLS = (
    "get_books_by_author",
    "get_books_by_series",
    "get_books_by_tag",
)


def test_pattern_tools_state_the_wildcard_rule(bound_server):
    """A bare pattern is an exact match — which "anchored at the start" got wrong.

    `search_books_by_title("Fundaci")` finds nothing; `"Fundaci%"` finds every
    Fundación. The `%` position chooses the mode, and its absence means exact.
    """
    text = _descriptions(bound_server)

    for name in PATTERN_TOOLS:
        description = text[name].lower()
        assert "no %" in description, name
        assert "exact" in description, name


def test_matching_rules_state_the_ñ_exception(bound_server):
    """ñ and ç are significant: "Carlos Munoz" finds nothing, "Carlos Muñoz" does.

    The normalization folds á and é but deliberately preserves ñ/Ñ/ç/Ç, so
    "accent-insensitive" without the exception is a claim a caller can act on
    and be wrong.
    """
    text = _descriptions(bound_server)

    for name in PATTERN_TOOLS + NAME_TOOLS:
        assert "ñ" in text[name], name


@pytest.mark.parametrize("tool, argument, key", [
    ("search_books_by_title", {"title_pattern": "zzzznotexist"}, "books"),
    ("search_authors_by_name", {"name_pattern": "zzzznotexist"}, "authors"),
    ("search_books_by_tag_pattern", {"tag_pattern": "zzzznotexist"}, "books"),
    ("get_books_by_author", {"author_name": "Zzzz Notan Author"}, "books"),
    ("get_books_by_author_id", {"author_id": 99999999}, "books"),
    ("get_books_by_series", {"series_name": "No Such Series"}, "books"),
    ("get_books_by_tag", {"tag_name": "zzzznotexist"}, "books"),
])
def test_an_unknown_argument_returns_count_zero(
    call_tool, parse_payload, tool, argument, key
):
    """ADR-0006's contract, pinned by behaviour rather than by wording.

    Five of these had no behavioural coverage of the empty case at all; a
    prose assertion cannot show what the tool actually returns.
    """
    assert parse_payload(call_tool(tool, argument)) == {"count": 0, key: []}


def test_all_tags_wraps_its_result(call_tool, parse_payload):
    """A bare list renders nothing when empty, which a library with no tags is.

    The `library` fixture starts with no tags, so this is the empty case.
    """
    result = call_tool("get_all_tags")

    assert result.content, "an empty tag dictionary must still render content"
    assert parse_payload(result) == {"count": 0, "tags": []}


def test_all_tags_counts_what_it_returns(library, call_tool, parse_payload):
    book_id = library.add_book("A Book")
    tag_id = library.add_tag("fiction")
    library.link_tag(book_id, tag_id)

    assert parse_payload(call_tool("get_all_tags")) == {
        "count": 1,
        "tags": [{"id": tag_id, "name": "fiction"}],
    }
