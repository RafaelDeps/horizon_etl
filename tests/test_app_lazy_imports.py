"""Verify that importing app.py does NOT pull in Playwright.

The ``lattes_projects`` phase subprocess (``python app.py ingest_lattes_projects``)
crashes with SIGSEGV on CI because eager top-level imports of
``src/flows/cnpq/groups.py`` and ``src/flows/sigpesq/all.py`` transitively load
Playwright's native stack, which conflicts with psycopg2/libpq under
multi-threading.  The fix defers those imports into ``main()`` so they are
only loaded when the specific command that needs them is invoked.
"""

import importlib
import sys
import subprocess


def test_importing_app_does_not_load_playwright():
    """Importing the app module must not bring Playwright into sys.modules."""
    saved = {}
    for mod in list(sys.modules):
        if mod.startswith("playwright"):
            saved[mod] = sys.modules.pop(mod)

    import app as app_mod

    try:
        playwright_modules = [m for m in sys.modules if m.startswith("playwright")]
        assert not playwright_modules, (
            f"app.py transitively loaded Playwright modules: {playwright_modules}"
        )
    finally:
        sys.modules.update(saved)
        importlib.reload(app_mod)
        for mod in list(sys.modules):
            if mod.startswith("playwright") and mod not in saved:
                sys.modules.pop(mod, None)


def test_ingest_lattes_projects_subprocess_does_not_load_playwright():
    """The subprocess invoked by the weekly orchestrator must not load Playwright.

    Spawns ``python app.py ingest_lattes_projects`` with a custom preamble
    that prints every loaded ``playwright*`` module after app startup, then
    checks the output.
    """
    code = (
        "import sys; "
        "sys.argv = ['app.py', 'ingest_lattes_projects']; "
        "import app; "  # noqa: trigger app module import
        "playwright = [m for m in sys.modules if m.startswith('playwright')]; "
        "print('PLAYWRIGHT_LOADED' if playwright else 'PLAYWRIGHT_CLEAN'); "
        "print(playwright)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert "PLAYWRIGHT_CLEAN" in result.stdout, (
        f"Playwright was loaded during ingest_lattes_projects startup.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
