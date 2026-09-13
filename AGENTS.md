## Agent skills

### Issue tracker

Issues live as GitHub issues on the fork, `gczobel/calibre_mcp_server`. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical roles: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` plus `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Worktrees

Do the work in a linked worktree under `.worktree/`, one per task, and leave the primary checkout on
`main` for other agents:

```bash
git worktree add .worktree/<task> -b <branch> main
git worktree remove .worktree/<task>   # once the branch is merged
```

`.worktree/` is gitignored: a worktree is a branch, not repo source.

## CI

What `test`, `publish` and CodeQL run on, where the image is published from, and what a pull request
that reports no checks at all means. See `docs/ci.md`.
