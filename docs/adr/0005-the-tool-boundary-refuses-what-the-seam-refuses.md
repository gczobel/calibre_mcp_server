# The tool boundary refuses what the CalibreDB seam refuses

Status: accepted

`stars` is declared strict at the tool boundary, so `false` and `"4"` are refused rather than coerced.
The rule is that the boundary refuses everything the seam refuses; it does not get to be more permissive
because it sits closer to the caller.

The coercion was the whole bug. With lax typing, `false` became `0` *before* the seam was called, so the
seam never saw the boolean it is written to reject — it saw a valid zero, and cleared the rating.

## Considered options

- **Let the seam's validation produce the error.** Rejected because it cannot. The boundary coerces
  first, so the seam is handed `0` and never sees `false`. Validation that never runs on the invalid
  value is not validation.
- **Keep the lax coercion and tighten the range instead.** Rejected because the range was never the
  problem. `0` is a legal argument, which is precisely what let the coerced `false` land inside it.

## Consequences

- `"4"` is refused as well as `false`, which is stricter than an MCP client may expect. That is
  deliberate: the seam refuses a string, so the boundary does too.
- The two layers have to stay in step by hand. Any future parameter whose seam validation is stricter
  than its schema must be declared strict as well, or the gap reopens silently.
- This is a consequence of [ADR-0004](0004-clearing-a-rating-is-zero-stars.md) — zero had to become
  meaningful for clearing to work — but the rule it states is general, which is why it is recorded
  separately.
