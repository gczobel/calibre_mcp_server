"""The boundary modules must pass whatever order they import the server in.

``server`` reads ``CALIBRE_LIBRARY_PATH`` while it is being imported, and the
module is then cached process-wide, so whichever boundary test imports it first
fixes the library for the whole session. ``bound_server`` in ``conftest`` undoes
that by rebinding ``calibre_db`` per test — a rule nothing pinned. It holds by
construction, and the coupling has already been reintroduced silently once: a new
boundary module kept passing *for the wrong reason*, against the module that
imported first, because both fixtures happened to contain a book with the same id
and no read column.

Two guards, because they fail differently. The first names the reason outright,
so a lost rebind reads as itself rather than as four unrelated failures. The
second is the property that actually matters — no module may depend on which one
imported first — and it is the one that cannot be satisfied by a fixture that
merely happens to do the right thing for the libraries the other tests build.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Every module that drives the server through an in-memory client. Named here so
# the run below is explicit about what it covers: a boundary module missing from
# this tuple would otherwise go unpinned.
BOUNDARY_MODULES = (
    "tests/test_find_books_boundary.py",
    "tests/test_rating_boundary.py",
    "tests/test_tool_boundary.py",
)

# Generous: three modules of in-memory MCP calls take well under a second, and
# the point of the limit is only that a hung child cannot hang CI instead.
REVERSE_RUN_TIMEOUT = 120


def test_bound_server_rebinds_the_module_to_this_tests_library(
    library, server_bound_elsewhere, request
):
    """The rebind is the rule, so assert the rule rather than its symptom.

    The module is imported once and cached, so it arrives already pointed at
    whichever library was in the environment at that moment. Without the rebind a
    boundary test asserts against some other test's library, which is how four
    tests once failed without saying why — while the test that imported the
    module first went on passing, because the stale binding was its own.

    ``server_bound_elsewhere`` supplies that stale state on purpose, and
    ``bound_server`` is asked for by name rather than as an argument: the stale
    binding has to be in place before the fixture corrects it, and as two
    arguments pytest would be free to set them up in either order.
    """
    bound_server = request.getfixturevalue("bound_server")

    # The premise, asserted rather than assumed: the two libraries differ, so a
    # rebind that did not happen cannot pass this test by accident.
    assert str(server_bound_elsewhere.db_path) != str(library.db_path)
    assert bound_server.calibre_db.db_path == str(library.db_path)


def test_boundary_modules_pass_in_reverse_order():
    """No boundary module may depend on which one imported the server first.

    A module run on its own passes even with a broken rebind, because the one
    that imports the server is the one that wins the race. So the run below is
    the whole set, in the reverse of the order pytest collects it in.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *reversed(BOUNDARY_MODULES)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=REVERSE_RUN_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"the reverse-order run did not finish within {REVERSE_RUN_TIMEOUT}s"
        )

    assert result.returncode == 0, result.stdout + result.stderr
