# CI

What runs when, and what to do when a pull request reports nothing at all.

## What runs

| workflow | triggered by | publishes |
|---|---|---|
| `ci.yml` → `test` | a push to `main` or a `v*` tag, any pull request, the weekly schedule, a manual dispatch | — |
| `ci.yml` → `publish` | behind a green `test` | `:latest` and `:<sha>` to GHCR, and only from `main` or a `v*` tag |
| `codeql.yml` → `analyze` | a push to `main`, any pull request, the weekly schedule | — |

`test` is the required check on `main`, so a pull request that never runs it can never merge.

## A pull request reports no checks

The symptom is quiet, which is what makes it worth recognising: **nothing failed.** The checks list is
empty, or the required `test` check sits at `Expected — Waiting for status to be reported` and stays
there. A check that never reports looks exactly like a stuck or misconfigured check.

Three causes, and they are easy to confuse.

### It conflicts with its base

GitHub runs `pull_request` workflows against the **merge commit**. A conflicting pull request has no
merge commit, so no run is created at all.

Neither reflex helps: closing and reopening the pull request produces no run, and force-pushing it
produces no run either, even though that is a `synchronize` event with a brand-new head SHA. Look at
the branch state instead:

```bash
gh pr view <n> --json mergeable,mergeStateStatus     # CONFLICTING / DIRTY
gh api repos/{owner}/{repo}/commits/<head-sha>/check-runs --jq .total_count   # 0
```

**Fix: rebase onto `main`.** CI starts within seconds of the conflict clearing.

### It targets a branch other than `main`: a stacked pull request

A pull request whose base is another pull request's branch runs like any other, because `ci.yml` does
not filter its `pull_request` trigger by branch. That was not always true — the trigger was filtered to
`main`, which left a stacked pull request with **no `test`, no `publish` and no CodeQL** — so a stack
whose lower layers were cut before that filter was removed still inherits it.

**Fix: rebase the stack onto current `main`, bottom layer first.** Each layer then reports its own
checks. Testing each layer on its own is the point of stacking: without it a defect in a middle layer
is first caught at the bottom of the merge sequence, which is the moment the stack exists to de-risk.

### It comes from a fork, and the contributor is new

GitHub creates the runs and holds them in `action_required` until a maintainer approves them. `gh pr
checks` reports nothing while they wait, so the symptom is identical to the two above — but the remedy
is the opposite: **the branch is fine.** What separates this one is the branch state and the run list:

```bash
gh pr view <n> --json mergeStateStatus    # BLOCKED, not CONFLICTING
gh run list --branch <head-branch>        # action_required
```

**Fix: approve the runs.** *Approve and run workflows* on the pull request, or:

```bash
gh api --method POST repos/{owner}/{repo}/actions/runs/<run-id>/approve
```

This is the default for a first contribution from a fork, not a defect. It is worth recognising because
rebasing — the fix for the two causes above — does nothing here, and the branch looks healthy the whole
time.

## Publishing is gated on the ref

`publish` pushes only when `github.ref` is `main` or a `v*` tag. A dispatch on a feature branch still
builds the image, and pushes nothing — which makes `Run workflow` a safe way to check a branch's
Dockerfile, and a way to get a branch built while a pull request is stuck for any of the reasons above.

The gate matters because the homelab pulls `:latest`. A run that published from a branch would replace
the deployed server with unreviewed code, silently. The gate used to be
`github.event_name != 'pull_request'`, which a dispatch from any branch satisfied.
