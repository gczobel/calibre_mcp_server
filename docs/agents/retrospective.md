# Retrospective over this repo's session logs

A prompt for a fresh session: reconstruct what happened across the sessions that worked on this repo, and
propose improvements to the **environment** rather than to any one change.

`/retro` supplies the improvement categories. This file supplies the log legwork, which is the part that
is not obvious and that a naive attempt gets wrong.

## Ask the human first

Before touching a log, ask what they already know. Their verdict is free, their memory covers sessions on
other machines and other repos, and it is the only source that can contradict the logs.

Worked example from this repo: asked which skills had helped, the maintainer named one outright. The logs
say it was **offered in every one of the seven sessions and loaded in none** — the model read its
catalogue entry, weighed it ("possibly unslop for writing README/docs … actually, let me focus") and moved
on. So the log-only answer ("never used, therefore irrelevant") would have been both wrong and
unactionable, while the maintainer's answer plus the log turns it into a concrete finding: a skill whose
description says it applies to every reply, that nothing causes to fire.

## Where the logs are

```
$DSH_HOME/sessions/--<cwd, every / replaced by -, wrapped in -->--/<session-id>/session.jsonl.zstd
```

For this repo:

```
~/.dsh/sessions/--home-gus-development-calibre_mcp_server--/
```

They are **zstd-compressed JSONL**. `zstd -dc <file>` works, as does Python's `compression.zstd`.

Measured on 2026-09-13: 26 session directories, 27 MB compressed, and the **largest single log decompresses
to 31 MB**. Extract a digest: it is the only form that fits.

## Two facts that make this tractable

**1. `delegationDepth` separates human sessions from subagents.** The first line of every log is a
`session` record:

```json
{"type":"session","id":"session-...","createdAt":1789217379595,"cwd":"/home/gus/development/calibre_mcp_server","delegationDepth":0,"agentPreset":"standard"}
```

`delegationDepth: 0` is a session a human drove; `1+` is a subagent's. Retrospect over depth 0 — there
were 7 at the date above, with 17 at depth 1 and 2 at depth 2 beneath them. The deeper logs are still
useful, but only to attribute delegated work; their reasoning appears nowhere in the parent log.

**2. About 86% of the lines are streaming deltas.** `reasoning-chunks`, `assistant/chunk`,
`tool-call-chunks` and `text-chunks` are token-by-token streams. Skip them: the semantic records are the
remaining ~14%, and skipping is what turns an unreadable log into a digest.

## The records worth extracting

| type | carries |
|---|---|
| `user/message` | `data.source.kind`, `data.content[].text` |
| `assistant/message` | `data.message.content[]`, plus `data.usage` — `inputTokens`, `outputTokens`, `cacheReadTokens`, `reasoningTokens` |
| `tool/call` | `name`, `arguments` (a JSON string), `turn`, `step` |
| `tool/result` | `isError`, `content[].content[].text`, `diffs` |
| `turn/start`, `turn/end` | turn boundaries, and `kind`/`reason` on the end record |
| `compaction/summary`, `compaction/prune` | context compaction, with `shadowedTokenCount` |
| `agent/inbox/spliced`, `plugin`, `agent-instructions`, `skill-catalog` | injected steering, not human input |

**`user/message` is not only the human.** Filter on `data.source.kind`. Measured across the seven
sessions: `user` 223, `agent-instructions` 34, `skill-invocation` 22, `subagent-settled` 15, `plugin` 14,
`skill-catalog` 11, `subagent-report` 11. Only `user` is the person; the rest is ceremony, and the ratio
between them is itself a retrospective finding.

**Offered is not used, and used is not always recorded.** Skill usage needs three separate signals:

| signal | where | means |
| --- | --- | --- |
| offered | `user/message` with `source.kind: skill-catalog` | the skill was in the catalogue |
| loaded | `user/message` with `source.kind: skill-invocation` | the model loaded it |
| considered | the skill's name in `assistant/message` or `reasoning` | it was weighed, and possibly acted on without loading |

A skill the *human* invokes with a slash command may leave no `skill-invocation` record at all, so counting
only those rows under-reports usage. Count all three, and treat "offered 7 times, loaded 0" as a finding
rather than an absence.

## Extraction recipe

Run this per log. It is deliberately simple; adapt it rather than reaching for the whole file.

```python
import subprocess, json, glob, os, collections

D = os.path.expanduser("~/.dsh/sessions/--home-gus-development-calibre_mcp_server--")
SKIP = {"reasoning-chunks", "assistant/chunk", "tool-call-chunks", "text-chunks",
        "step/start", "step/end", "session"}

def digest(path):
    out = {"id": os.path.basename(os.path.dirname(path)), "human_turns": [], "tools": collections.Counter(),
           "failures": [], "tokens": collections.Counter(), "compactions": 0, "skills": []}
    for line in subprocess.run(["zstd", "-dc", path], capture_output=True).stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        t, data = d.get("type"), d.get("data", {})
        if t in SKIP:
            continue
        if t == "user/message":
            kind = data.get("source", {}).get("kind")
            text = " ".join(c.get("text", "") for c in data.get("content", []) if c.get("type") == "text")
            if kind == "user":
                out["human_turns"].append(" ".join(text.split())[:300])
            elif kind == "skill-invocation":
                out["skills"].append(text[:60])
        elif t == "tool/call":
            out["tools"][data.get("name")] += 1
        elif t == "tool/result":
            for block in data.get("message", {}).get("content", []):
                for inner in block.get("content", []) or []:
                    text = inner.get("text", "")
                    if block.get("isError") or "[exit code: " in text[:400]:
                        out["failures"].append(text[:160].replace("\n", " "))
        elif t == "assistant/message":
            for key, value in (data.get("usage") or {}).items():
                out["tokens"][key] += value or 0
        elif t.startswith("compaction/"):
            out["compactions"] += 1
    return out
```

That yields, per session: the human's questions in order, a tool histogram, the failure signatures,
token totals, and how often the context had to be compacted.

## Fan out; do not paste

Seven logs do not fit in one context, and neither does one of the larger ones. Send **one subagent per
depth-0 session**, each running the recipe above and returning the same fixed digest, then aggregate the
digests. If the sessions are already known, `workflow` is the tool for this: it fans out by file and
collects structured results.

Tell each subagent explicitly: *extract a digest from the log, and for one specific incident query the raw
log with `zstd -dc … | grep` or `jq`.*

## What to look for

`/retro` names the categories; these are the log signals that indicate each.

| category | signal in the log |
|---|---|
| Tool economy | one tool dominating the histogram (a measured session: `bash` 71 calls against `read` 24), repeated near-identical `tool/call` arguments, tokens per human turn |
| Automated checks | clusters of `[exit code: N]` or `isError` that a lint, test or type check would have caught earlier |
| Navigation | steps before the first correct file reference; repeated failed reads of a path that does not exist |
| Coding standards / reviewer rules | claims the agent wrote that the code contradicts — this repo has two on record: "anchored at the start" and "accent-insensitive" |
| No-ops and steering size | injected messages against human turns; instructions never acted on; skills offered in the catalogue and never loaded |
| Information access | workarounds for missing information, e.g. a live check hand-rolled through HTTP because the MCP bridge held a stale session |

## Output

A ranked list of **environment** changes, each with: the change, the evidence (session id plus the record
type or pattern), and the cost it would have saved. Ranked, so the output changes the environment rather
than recounting the session.

Write it under `/writing-for-agents`, the style guide `/retro` names: a retrospective is a document agents
consume, and one will read it.

## Limits, so the result is not over-trusted

- **Token counts, no cost.** `assistant/message` carries them under `data.usage`; there is no price
  data. Note the nesting: reading `data.inputTokens` returns nothing, silently, which is how this
  recipe was wrong the first time it was run.
- **Digests truncate tool results.** For one specific incident, query the raw log for that record.
- **Logs live on this machine**, not in the repo, so a retrospective is not reproducible from a clone and
  should not be cited as if it were.
- **A subagent's reasoning is only in its own log.** The parent records its report, not its thinking.
- **Compaction destroys detail.** `compaction/summary` replaces earlier turns with a summary; once a
  session has compacted, the pre-compaction conversation is no longer in the log in full.
