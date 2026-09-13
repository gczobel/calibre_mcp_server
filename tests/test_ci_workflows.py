"""Contracts for the workflow files, which nothing else in the suite can check.

Both misbehaviours pinned here are silent, and that is what makes a test the only
durable guard. GitHub reports nothing at all when a ``pull_request`` workflow is
filtered out by its trigger, so a stacked pull request has no failed check to
notice, only a required ``test`` check that never reports. And nothing fails when
a run builds without publishing, so a publish gate keyed on the event rather
than the ref only shows up as ``:latest`` quietly moving.

The publish gate is exercised as a truth table over ``(event_name, ref)`` rather
than by matching the expression's text, so the gate stays free to be respelled —
while still failing if it stops meaning "only ``main`` and ``v*`` tags publish".
"""

import ast
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# PyYAML resolves an unquoted `on:` key to the boolean True (YAML 1.1).
ON = True


def workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def trigger(loaded: dict, event: str):
    """One event's entry under ``on:``, or None when the entry is empty.

    An empty entry (``pull_request:`` with nothing under it) means every branch,
    which is what a test should read as "no filter".
    """
    return (loaded[ON] or {}).get(event)


@pytest.mark.parametrize("name", ["ci.yml", "codeql.yml"])
def test_a_pull_request_targeting_any_branch_runs(name):
    """A stacked pull request targets another pull request's branch, not main.

    Filtering the trigger to `main` left such a pull request with no run at all,
    and `test` is the required check, so it waited on a status that was never
    coming. Testing each layer on its own is the point of stacking.
    """
    branches = (trigger(workflow(name), "pull_request") or {}).get("branches")
    assert not branches, (
        f"{name} filters its pull_request trigger to {branches}, so a pull "
        "request based on a feature branch runs nothing"
    )


def test_a_push_still_targets_main_and_version_tags():
    """Removing the `pull_request` filter must not widen the push trigger.

    The push trigger is what publishes, so it keeps its main-only filter: a
    push to `main` and a `v*` tag behave exactly as before.
    """
    push = trigger(workflow("ci.yml"), "push")
    assert push["branches"] == ["main"]
    assert push["tags"] == ["v*"]


# ``(event_name, ref, publishes)``.
PUBLISH_GATE = [
    ("workflow_dispatch", "refs/heads/main", True),
    ("workflow_dispatch", "refs/heads/feature-branch", False),
    ("push", "refs/heads/main", True),
    ("push", "refs/tags/v1.2.3", True),
    ("schedule", "refs/heads/main", True),
    ("pull_request", "refs/pull/26/merge", False),
]


def github_context(event_name: str, ref: str) -> dict:
    """The parts of the `github` context the gates are read against.

    The refs are the ones GitHub reports for each event: a branch ref for a
    dispatch, `refs/tags/<tag>` for a tag push, and `refs/pull/<n>/merge` for a
    pull request.
    """
    return {"event_name": event_name, "ref": ref}


@pytest.mark.parametrize("event_name,ref,publishes", PUBLISH_GATE)
def test_the_publish_gate_follows_the_ref_not_the_event(event_name, ref, publishes):
    """A dispatch on a branch may build, but must not publish.

    The homelab pulls `:latest`, so a stray dispatch from a feature branch would
    replace the deployed server image with unreviewed code.
    """
    assert _publishes(workflow("ci.yml"), github_context(event_name, ref)) is publishes


def test_the_login_and_the_push_are_gated_alike():
    """Gates that drift mean one of them is wrong, and `latest` is the stake.

    A login without a push only wastes a step; a push without a login cannot
    publish at all. Either way the two steps are answering one question.
    """
    loaded = workflow("ci.yml")
    for event_name, ref, _ in PUBLISH_GATE:
        github = github_context(event_name, ref)
        assert _logs_in(loaded, github) is _publishes(loaded, github), (
            f"on {event_name} at {ref}, the GHCR login and the image push disagree"
        )






def test_the_build_runs_even_when_nothing_is_published():
    """The useful half of a dispatch on a branch is the build itself.

    Gating the build too would leave a broken Dockerfile for `main` to find,
    which is the one thing the dispatch was kept for.
    """
    step = _step(workflow("ci.yml"), "publish", "docker/build-push-action")
    assert "if" not in step


def test_the_image_still_carries_latest_and_the_commit():
    """What a push to `main` publishes has to stay `:latest` and `:<sha>`."""
    step = _step(workflow("ci.yml"), "publish", "docker/build-push-action")
    tags = (step.get("with") or {}).get("tags", "")
    assert "ghcr.io/${{ github.repository }}:latest" in tags
    assert "ghcr.io/${{ github.repository }}:${{ github.sha }}" in tags


def test_codeql_is_told_which_language_to_analyse():
    """`language` is not an input, so passing it analysed nothing in particular.

    `github/codeql-action/init` takes `languages`. Spelled without the `s` the
    input is ignored, the job warns, and the run stays green — which is how the
    `actions` leg went on analysing whatever autodetection picked instead of the
    workflows it exists for. A spelling, then, but a silent one with a real
    consequence, which is the pair this module is for.
    """
    step = _step(workflow("codeql.yml"), "analyze", "github/codeql-action/init")
    passed = step.get("with") or {}

    assert "language" not in passed, (
        "the input is `languages`; `language` is ignored, and the warning "
        "annotation is the only sign"
    )
    assert passed.get("languages") == "${{ matrix.language }}"


# -- reading the gate out of the workflow --------------------------------


def _step(loaded: dict, job: str, uses_prefix: str) -> dict:
    for step in loaded["jobs"][job]["steps"]:
        if str(step.get("uses", "")).startswith(uses_prefix):
            return step
    raise AssertionError(f"job {job!r} has no step using {uses_prefix}")


def _publishes(loaded: dict, github: dict) -> bool:
    step = _step(loaded, "publish", "docker/build-push-action")
    # The action's own default is to build without pushing.
    declared = (step.get("with") or {}).get("push", "false")
    return _evaluate(declared, github, loaded)


def _logs_in(loaded: dict, github: dict) -> bool:
    step = _step(loaded, "publish", "docker/login-action")
    return _evaluate(step.get("if", "true"), github, loaded)


def _evaluate(expression: object, github: dict, loaded: dict) -> bool:
    """Evaluate a gate for one event, resolving ``env`` indirection on the way.

    ``env.X`` is answered as the string GitHub would render, so a gate that
    reads ``env.PUBLISH_IMAGE == 'true'`` and one that repeats the expression
    inline are both read correctly.
    """
    source = _python_source(
        str(expression),
        lambda name: _env_value(name, github, loaded),
    )
    try:
        return bool(_node_value(ast.parse(source, mode="eval").body, github))
    except Exception as exc:
        raise AssertionError(
            f"cannot evaluate {expression!r}, rewritten as {source!r}: {exc}"
        ) from exc


def _node_value(node: ast.AST, github: dict):
    """The value of one node of the rewritten expression.

    Walking the tree rather than calling ``eval`` keeps this test free of a
    construct CodeQL rightly reports as injection — reading an expression out of
    a file and running it. Only what the rewrite produces is handled, and
    anything else raises, so a gate this test cannot read fails loudly instead
    of passing by accident.
    """
    if isinstance(node, ast.BoolOp):
        values = [_node_value(value, github) for value in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.Compare):
        if len(node.comparators) != 1 or not isinstance(
            node.ops[0], (ast.Eq, ast.NotEq)
        ):
            raise AssertionError(f"unsupported comparison: {ast.dump(node)}")
        left = _node_value(node.left, github)
        right = _node_value(node.comparators[0], github)
        return left == right if isinstance(node.ops[0], ast.Eq) else left != right
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "startswith":
            return str(_node_value(func.value, github)).startswith(
                _node_value(node.args[0], github)
            )
    if isinstance(node, ast.Name) and node.id.startswith("gh_"):
        field = node.id[len("gh_") :]
        if field not in github:
            raise AssertionError(
                f"github.{field} is not one of the fields this test supplies "
                f"({', '.join(sorted(github))})"
            )
        return github[field]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    raise AssertionError(f"unsupported construct: {ast.dump(node)}")


def _env_value(name: str, github: dict, loaded: dict) -> str:
    """The string GitHub would expose as ``env.<name>`` to the publish job.

    Job-level values win over workflow-level ones, as they do on a runner.
    """
    declared = (loaded["jobs"]["publish"].get("env") or {}).get(name)
    if declared is None:
        declared = (loaded.get("env") or {}).get(name)
    if declared is None:
        raise AssertionError(
            f"env.{name} is declared neither in the publish job nor at workflow level"
        )
    # Read as the string GitHub exposes, not as a boolean: a value fed to a
    # boolean field is a non-empty string, and `if: env.X` would read a literal
    # 'false' as true.
    return "true" if _evaluate(declared, github, loaded) else "false"


_EXPRESSION = re.compile(r"\$\{\{(?P<body>.*)\}\}", re.DOTALL)
_ENV = re.compile(r"\benv\.(?P<name>\w+)")
_GITHUB = re.compile(r"\bgithub\.(?P<field>\w+)")
_STARTS_WITH = re.compile(
    r"\bstartsWith\(\s*(?P<value>[^,]+?)\s*,\s*(?P<prefix>'[^']*')\s*\)"
)


def _python_source(expression: str, resolve_env) -> str:
    """Rewrite a GitHub Actions expression into the equivalent Python.

    Python so the stdlib can tokenize it, and a rewrite rather than a parser
    because the operators line up one for one. Only the constructs these
    workflows use are translated, and anything else fails to parse or to walk,
    which is the point: a gate this test cannot read must not pass by accident.
    """
    match = _EXPRESSION.fullmatch(expression.strip())
    source = (match.group("body") if match else expression).strip()
    source = _ENV.sub(lambda m: repr(resolve_env(m.group("name"))), source)
    source = _GITHUB.sub(lambda m: f"gh_{m.group('field')}", source)
    source = _STARTS_WITH.sub(
        lambda m: f"{m.group('value')}.startswith({m.group('prefix')})", source
    )
    return source.replace("&&", " and ").replace("||", " or ")
