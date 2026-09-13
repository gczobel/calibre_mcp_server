# The legacy list tools are bounded, and an empty result is not an error

Status: accepted

Extends [ADR-0003](0003-find-books-returns-a-count-alongside-its-books.md), which made `find_books` wrap
its result so an empty match stays visible, and recorded that the older tools "still carry the bug it
fixed". They no longer do.

Seven tools predate `find_books` and now behave like it:

`search_books_by_title`, `search_authors_by_name`, `search_books_by_tag_pattern`, `get_books_by_author`,
`get_books_by_author_id`, `get_books_by_series`, `get_books_by_tag`.

Each one now returns `{"count": n, "<items>": [...]}` — `books` for the book searches, `authors` for the
author search — caps its results at `limit` (default `DEFAULT_SEARCH_LIMIT`), and returns an empty result
instead of raising when nothing matches.

## Why

Two measurements against a real library, not supposition:

- `search_books_by_tag_pattern("Ciencia%")` returned **every matching book in one response**, because
  the number of matches was unbounded. `find_books` has a small default `limit` precisely so that an omitted parameter
  cannot return a library; the tools that predate it never got one.
- Every one of them turned "no matches" into a tool error — `No books found with tag name: '...'` —
  while `find_books` returned `{"count": 0, "books": []}`. Answering "does this library have X?" then
  means catching and classifying an error rather than reading a result.

## Considered options

- **Leave the older tools as they are.** Rejected: ADR-0003 already names the invisible empty result as a
  live bug in them, and an unbounded response is a failure mode rather than a matter of taste.
- **Cap with a SQL `LIMIT`.** Rejected: these searches filter in Python so that matching can be
  accent-insensitive. A SQL `LIMIT` truncates the candidate rows *before* that filtering, which would
  return the wrong set — it would look like a cap and behave like a sample.
- **Return a bare empty list and document the caveat.** Rejected, for the reason ADR-0003 gives:
  documentation cannot make an invisible result visible.

## Consequences

- The surface is consistent: every list-returning tool wraps, counts and caps. ADR-0003's claim that
  `find_books` is the only one that wraps no longer holds.
- A caller must read `.books` or `.authors`, not the result itself. This is a breaking change for the
  seven tools, deliberately, and the wrapper is the part not to "normalise" away.
- These tools gained a defaulted `ctx: Optional[Context] = None`, because a parameter with a default
  cannot precede a required one. `find_books` already did this.
- `limit` is validated at both layers: the tool's field has `gt=0`, and `CalibreDB` validates again so the
  seam cannot be called with a nonsensical cap.
- `get_all_tags` was left as a bare list here, reasoning that it is a dictionary listing with no entity
  filter and a bounded 160 rows, so neither defect applied. That reasoning weighed size and missed
  rendering: an empty dictionary produced an empty response, which is the #19 symptom ADR-0003
  describes. It wraps now too (#57).
