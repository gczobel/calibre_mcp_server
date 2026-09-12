# Candidate evaluation: where should read-tracking live?

Comparison of the plausible homes for a read-tracking feature (mark a book read/unread,
finish date, rating, note) and the reverse query "what haven't I read yet".

All repository figures captured **2026-09-12** via the GitHub API. Engineering figures
measured from depth-1 clones. No judgement here is inferred from marketing copy.

## 1. Repository signals

| | `caelum29/calibre-mcp` | `FaceDeer/calibre_full_mcp_server` | `ajtudela/calibre_mcp_server` (current) |
|---|---|---|---|
| Last push | 2026-08-21 | 2026-03-25 | 2025-10-05 |
| Dormancy | 3 weeks | ~6 months | **342 days** |
| Stars / forks | 14 / 3 | 20 / 3 | 0 / 2 |
| Created | 2026-07-01 | 2026-02-22 | 2025-09-21 |
| Language | TypeScript (ESM, pnpm) | Python | Python |
| License | MIT | MIT | Apache-2.0 |
| Open issues | 30 | 1 | 0 |
| Issues ever | 108 | 1 | 0 |
| **Issues authored by others** | **0** | 1 | **0** |
| Merged PRs | 23 | 2 | 0 |
| **Merged PRs authored by others** | **0** | **0** | **0** |
| Releases | yes (npm, MCP registry) | no | no |

**The decisive negative result: no external pull request has ever been merged in any of
the three.** Contribution appetite is unproven everywhere in this ecosystem.

## 2. Engineering signals

| | caelum29 | FaceDeer | ajtudela (current) |
|---|---|---|---|
| Code files | 175 | 26 | 7 |
| Code LOC | 25,380 | 3,744 | 2,669 |
| Test files | 77 | 14 | **0** |
| Test LOC | 8,810 | 1,187 | **0** |
| CI | `ci.yml`, `release.yml` | **none** | none |
| Live-Calibre test harness | **yes** (`pnpm test:calibre`, `RUN_CALIBRE_TESTS=1`) | no | no |
| Agent-facing docs | `CLAUDE.md`, `CONTEXT.md`, `docs/claude/*` | `doc/Architecture.md` | none |
| Published tool/arch docs | `docs/TOOLS.md`, `docs/SEMANTIC-SEARCH.md`, `docs/TROUBLESHOOTING.md` | `doc/Tasks.md` | README only |
| Module structure | `src/domain/{curation,distill,enrich,figures,structure}`, `src/calibre/`, `src/tools/`, `src/semantic/`, `src/ui/` | `src/logic/{library_ops,metadata_ops,permissions,text_search}.py`, `worker.py`, `worker_pool.py` | `calibre_api.py`, `server.py` |
| Existing write layer | `src/tools/write-refusal.ts`, `calibre_update_book.ts`, `calibre_bulk_update.ts`, `src/calibre/{client,metadata-fields}.ts` | `src/logic/metadata_ops.py`, `permissions.py` | **none** (zero write statements) |

`caelum29` leads on every engineering axis: ~6.8x the code, ~7.4x the tests, gated CI
(`prepublishOnly = build && test`), a domain-layer structure with named seams, and tool
and architecture documentation written explicitly for agents.

The **live-Calibre test harness is the decisive item for this particular feature**: it
means a write path can be developed and verified against a real Calibre instance rather
than reasoned about from the schema. `FaceDeer` has no CI at all.

## 3. Deployment trade-off

The three require materially different infrastructure, and this is the part that changes
what a published Docker image *is*.

| | Mechanism | Requires | Can Calibre be running? |
|---|---|---|---|
| ajtudela (current) | direct SQLite on `metadata.db` | library mounted (read-only fine) | reads only, so yes |
| caelum29 | reads via Content Server `/ajax/*`; writes via `calibredb --with-library <server>/#<lib>` | **Calibre installed + Content Server running** | **yes** — writes route through the resident process |
| FaceDeer | `calibre-debug` worker → `Cache.set_metadata()` | **Calibre installed, not running** | **no** — README warns of corruption |

Trade-off in plain terms:

- **caelum29** removes the DB mount and all schema-version coupling, and gets GUI-safety
  for free by delegating writes to the process that owns the library. Cost: a Content
  Server must be alive, and Calibre must be on `PATH` for the write CLI.
- **FaceDeer** needs no running server — lighter to operate — but demands the library be
  closed, so the agent and the desktop app can never be used at the same time.
- **ajtudela** keeps the tidy stateless read-only container, which is exactly why it
  cannot safely gain writes.

## 4. Assessment

`caelum29/calibre-mcp` is the best foundation for expansion, on evidence rather than
preference: most active, best tested, only one with CI, only one with a live-Calibre
harness, only one with an existing write layer, and its write mechanism is the one the
Calibre research independently recommends (see `calibre-write-path.md`).

The one unresolved unknown is **maintainer appetite**, which no amount of code reading
settles. Two cautions specific to `caelum29`:

1. Zero external PRs have ever been merged, and all 108 issues are self-authored —
   the tracker reads as a personal backlog (`#126`: "seed initial bundles ... for
   Artem's library").
2. It is mid-migration to the v2 SDK packages (`#123`), so a PR opened now risks
   colliding with in-flight refactoring.

## 5. Decision (2026-09-12)

**This fork, `gczobel/calibre_mcp_server`, is the canonical home for the work.** Settled
by the repo owner; recorded here because it is expensive to reverse.

1. **Harvest concepts and tools from the better-engineered projects rather than adopting
   one wholesale.** Language is not a constraint — functionality is transliterated between
   Python and TypeScript in whichever direction makes sense. `caelum29` is the richest
   source of concepts; `FaceDeer` supplies the field-level permission model; `Xpresi`
   supplies the direct-SQLite safety apparatus (should that path ever be wanted).
2. **The read-tracking feature is implemented here**, on top of whatever is harvested.
3. **The published image builds from this fork**, not from `ajtudela/calibre_mcp_server`.
   See "Consequence" below.
4. **Upstream contribution is best-effort, not a gate.** Work does not wait on maintainer
   appetite; upstream PRs are offered where a change is independently useful.

This supersedes the "ask before building" recommendation above, which assumed upstream
acceptance was the goal. It no longer is.

### Consequence: the publishing repo must be re-pointed

`calibre-mcp/Dockerfile` currently installs upstream:

```
RUN pip install --no-cache-dir git+https://github.com/ajtudela/calibre_mcp_server.git
```

This must become `gczobel/calibre_mcp_server` (pinned to a ref, ideally a tag rather than
`main`, so an image rebuild is reproducible). Until that line changes, the published image
cannot contain any of this work regardless of what lands here.

Note: **read-tracking is implemented in none of the 12 projects surveyed** (see
`prior-art-write-implementations.md`), so this is a first implementation rather than a
duplicate of someone else's work.
