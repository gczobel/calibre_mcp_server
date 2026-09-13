# find_books returns a count alongside its books

Status: accepted

`find_books` returns `{"count": ..., "books": [...]}` rather than a bare list. A bare list that is empty
renders no content block at all at the tool boundary, so a caller could not tell "nothing matched" from
"the call failed" — and the empty case is the one a caller most needs to read correctly.

## Considered options

- **Keep the bare list and document the caveat.** Rejected: documentation cannot make an invisible
  result visible. The ambiguity lives in how the result renders, not in how carefully the caller reads.

## Consequences

- This is a deliberate breaking change to the documented tool surface.
- `find_books` is now the only tool here that wraps its result. The title, author, series and tag
  searches all still return a bare list, so the surface is inconsistent on purpose. Do not "normalise"
  `find_books` back to a list without reading this: the wrapper is what makes an empty result visible,
  and the older tools still carry the bug it fixed.
- A caller reading `find_books` must read `.books`, not the result itself.
