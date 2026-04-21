"""Boundary contract: flows engine must not import AI Builder.

Phase A of the architecture rewrite un-inverts the two existing violations
(`flow_validators.py:15`, `api/flow_router.py:3`) by hoisting the shared
primitives into the engine. Until then the `.importlinter` contract locks
the boundary so no _new_ direct imports from the engine into the plugin
slip in.

`allow_indirect_imports = true` scopes the check to direct, textual imports:
lazy in-function imports that transitively reach `ai_builder` via
`intric.tenants.tenant` (see `tenant.py:301`) are intentionally out of scope
here. They are legitimate sibling reuse, not an engine-layer coupling.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

CONTRACT_NAME = "Flows engine must not import AI Builder (Phase A un-inverts)"


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _expected_source_modules() -> set[str]:
    """Enumerate everything under `intric/flows/` except `ai_builder/` and
    dunder/cache artefacts. Returns the set of dotted module names we
    expect to appear in `.importlinter`'s `source_modules` list.
    """
    flows_dir = _backend_root() / "src" / "intric" / "flows"
    expected: set[str] = set()
    for entry in flows_dir.iterdir():
        if entry.name in {"ai_builder", "__pycache__"}:
            continue
        if entry.is_dir():
            expected.add(f"intric.flows.{entry.name}")
        elif entry.suffix == ".py" and entry.name != "__init__.py":
            expected.add(f"intric.flows.{entry.stem}")
    return expected


def _configured_source_modules() -> set[str]:
    """Parse the `source_modules` list out of the forbidden contract."""
    import configparser

    parser = configparser.ConfigParser()
    parser.read(_backend_root() / ".importlinter", encoding="utf-8")
    raw = parser.get(
        "importlinter:contract:flows-engine-no-ai-builder", "source_modules"
    )
    return {line.strip() for line in raw.splitlines() if line.strip()}


def test_source_modules_cover_every_flows_sibling() -> None:
    """Drift guard. `import-linter`'s `forbidden` contract cannot express
    'all of `intric.flows` except `intric.flows.ai_builder`' natively, so
    `.importlinter` enumerates every sibling. If someone adds a new
    top-level module/package under `intric/flows/` without updating the
    config, that module would silently fall outside the boundary rule —
    fail here instead of discovering it in production.
    """
    expected = _expected_source_modules()
    configured = _configured_source_modules()
    missing = expected - configured
    stale = configured - expected
    assert not missing and not stale, (
        "`.importlinter` `source_modules` is out of sync with the filesystem.\n"
        f"Missing from config (add these): {sorted(missing)}\n"
        f"No longer present on disk (remove these): {sorted(stale)}"
    )


def test_flows_engine_has_no_new_imports_into_ai_builder() -> None:
    backend_root = _backend_root()
    config = backend_root / ".importlinter"
    assert config.is_file(), f"{config} not found — boundary rule missing"

    result = subprocess.run(
        ["uv", "run", "lint-imports", "--no-cache"],
        cwd=backend_root,
        capture_output=True,
        text=True,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        "Flows engine → AI Builder boundary broken.\n"
        "Either un-invert the dependency (preferred) or, if it is a temporary "
        "refactor step, add an explicit line to `.importlinter`'s "
        "`ignore_imports` with a FIXME linking back to the next cleanup task.\n\n"
        f"lint-imports output:\n{combined}"
    )
    assert "0 broken" in combined, (
        "lint-imports exited 0 but did not report '0 broken' — unexpected output shape.\n"
        f"lint-imports output:\n{combined}"
    )
    assert CONTRACT_NAME in combined, (
        f"Expected contract '{CONTRACT_NAME}' to be evaluated.\n"
        f"lint-imports output:\n{combined}"
    )
