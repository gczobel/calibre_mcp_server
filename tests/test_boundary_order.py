"""The boundary modules must pass whatever order they import the server in.

``server`` reads ``CALIBRE_LIBRARY_PATH`` while it is being imported, and the
module is then cached process-wide, so whichever boundary test imports it first
fixes the library for the whole session. ``bound_server`` in ``conftest`` undoes
that by rebinding ``calibre_db`` per test. The coupling has already been
reintroduced silently once: a new boundary module kept passing *for the wrong
reason*, against the module that imported first, because both fixtures happened
to contain a book with the same id and no read column.

That rebind is now asserted where it happens, so losing it fails every boundary
test with the reason spelled out — which is the guard that covers each module
automatically. This module carries the two checks a per-test assertion cannot.

The first says the rule out loud: bind the module elsewhere, then assert
``bound_server`` corrects it. That stale state is otherwise unreachable, because
the test that imports the server first is the one that wins the race — so the
assertion written the obvious way passes by winning the race it is meant to
check.

The second is the property no single test can cover: the modules pass in any
order, not merely each against its own library. It is slower than the first, so
it is confined to the modules that need it, and it catches coupling between them
that has nothing to do with the seam.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# What it means for a module to drive the server through the in-memory client.
# Found by scanning rather than listed, because the module that would need adding
# to a list is the one nobody has a reason to open: a boundary module left out of
# the run below is a coverage gap with no symptom.
DRIVES_THE_SERVER = re.compile(r"\b(bound_server|call_tool)\b")

# Generous: the modules below take well under a second between them, and the
# point of the limit is only that a hung child cannot hang CI instead.
REVERSE_RUN_TIMEOUT = 120


def boundary_modules() -> list[str]:
    """Every test module that drives the server, this one excepted.

    This module drives it too, and is skipped because running it would spawn
    another run of itself.
    """
    return sorted(
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "tests").glob("test_*.py")
        if path.name != Path(__file__).name
        and DRIVES_THE_SERVER.search(path.read_text())
    )


def test_bound_server_rebinds_the_module_to_this_tests_library(
    library, server_bound_elsewhere, request
):
    """The rebind is the rule, so assert the rule rather than its symptom.

    The module is imported once and cached, so it arrives already pointed at
    whichever library was in the environment at that moment. Without the rebind a
    boundary test asserts against some other test's library — while the test that
    imported the module first goes on passing, because the stale binding is its
    own.

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
    every module that drives it, in the reverse of the order pytest collects them
    in.
    """
    modules = boundary_modules()
    # Fail closed. A run that collected nothing is green, and a renamed binding
    # fixture would empty this without saying so.
    assert modules, "no boundary module found; the run below would prove nothing"

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *reversed(modules)],
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
