#!/usr/bin/env python3
"""Guard the backend test-suite layout.

The backend test standard (backend/TESTING.md) has one canonical unit root,
tests/unit/, shaped as a mirror of src/eneo/. This check enforces the rules
that keep the suite from regrowing its legacy shape:

1. tests/unittests/ is frozen: no new files. The snapshot of files that
   existed at freeze time lives in scripts/test_layout_allowlist.txt and only
   shrinks as domains migrate to tests/unit/.
2. New files under tests/unit/ must sit in a directory that mirrors an
   existing src/eneo/ package. The flat files that predate the rule are
   allow-listed until their domain migrates.
3. No @pytest.mark.asyncio (asyncio_mode=auto makes it a no-op) and no
   explicit @pytest.mark.integration (auto-applied by path) anywhere under
   backend/tests/.
4. Every directory under backend/tests/ that contains a tracked .py file has
   an __init__.py, so duplicate test basenames resolve as packages.
5. Allow-list entries must still exist; stale entries fail so the list can
   only shrink.

Run locally:  python3 scripts/check_test_layout.py
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ALLOWLIST_FILE = Path("scripts/test_layout_allowlist.txt")

UNITTESTS_PREFIX = "backend/tests/unittests/"
UNIT_PREFIX = "backend/tests/unit/"
TESTS_PREFIX = "backend/tests/"
SRC_ROOT = "backend/src/eneo"

BANNED_DECORATORS = re.compile(
    r"^\s*@pytest\.mark\.(asyncio|integration)\s*$", re.MULTILINE
)
# The integration conftest applies the marker programmatically; it is the one
# place allowed to reference it.
DECORATOR_SCAN_EXEMPT = {"backend/tests/integration/conftest.py"}


def tracked_test_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "backend/tests"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [ln for ln in result.stdout.splitlines() if ln.endswith(".py")]


def load_allowlist(repo_root: Path) -> set[str]:
    lines = (repo_root / ALLOWLIST_FILE).read_text().splitlines()
    return {ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")}


def check_frozen_unittests(files: list[str], allowlist: set[str]) -> list[str]:
    """Rule 1: no files under tests/unittests/ beyond the freeze snapshot."""
    return [
        f"{path}: tests/unittests/ is frozen legacy. New unit tests go in "
        f"backend/tests/unit/<mirror of src/eneo>/ (see backend/TESTING.md)."
        for path in files
        if path.startswith(UNITTESTS_PREFIX) and path not in allowlist
    ]


def check_unit_mirror(
    files: list[str], allowlist: set[str], src_dir_exists
) -> list[str]:
    """Rule 2: tests/unit/ files live in dirs mirroring src/eneo packages."""
    violations = []
    for path in files:
        if not path.startswith(UNIT_PREFIX):
            continue
        rel = path[len(UNIT_PREFIX) :]
        parent = str(Path(rel).parent)
        if parent == ".":
            if Path(rel).name != "__init__.py" and path not in allowlist:
                violations.append(
                    f"{path}: flat files under tests/unit/ are not allowed. "
                    f"Place the test in tests/unit/<package>/ mirroring the "
                    f"src/eneo package of the module under test."
                )
            continue
        if not src_dir_exists(parent):
            violations.append(
                f"{path}: tests/unit/{parent}/ does not mirror an existing "
                f"src/eneo package ({SRC_ROOT}/{parent} is not a directory). "
                f"Match the source layout of the module under test."
            )
    return violations


def check_banned_decorators(files: list[str], read_text) -> list[str]:
    """Rule 3: no redundant asyncio/integration marker decorations."""
    violations = []
    for path in files:
        if path in DECORATOR_SCAN_EXEMPT:
            continue
        for match in BANNED_DECORATORS.finditer(read_text(path)):
            marker = match.group(1)
            reason = (
                "asyncio_mode=auto already applies it"
                if marker == "asyncio"
                else "the integration conftest applies it by path"
            )
            violations.append(
                f"{path}: remove @pytest.mark.{marker} ({reason})."
            )
    return violations


def check_init_files(files: list[str]) -> list[str]:
    """Rule 4: every dir holding tracked .py files is a package."""
    tracked = set(files)
    dirs = {str(Path(path).parent) for path in files}
    return [
        f"{d}/: missing __init__.py (duplicate test basenames need package "
        f"resolution)."
        for d in sorted(dirs)
        if d.startswith(TESTS_PREFIX.rstrip("/")) and f"{d}/__init__.py" not in tracked
    ]


def check_stale_allowlist(files: list[str], allowlist: set[str]) -> list[str]:
    """Rule 5: the allow-list only shrinks."""
    tracked = set(files)
    return [
        f"{entry}: allow-listed but no longer tracked. Remove the entry from "
        f"{ALLOWLIST_FILE} (the list only shrinks)."
        for entry in sorted(allowlist - tracked)
    ]


def run_checks(repo_root: Path) -> list[str]:
    files = tracked_test_files(repo_root)
    allowlist = load_allowlist(repo_root)

    def src_dir_exists(rel: str) -> bool:
        return (repo_root / SRC_ROOT / rel).is_dir()

    def read_text(rel: str) -> str:
        return (repo_root / rel).read_text(encoding="utf-8", errors="replace")

    return [
        *check_frozen_unittests(files, allowlist),
        *check_unit_mirror(files, allowlist, src_dir_exists),
        *check_banned_decorators(files, read_text),
        *check_init_files(files),
        *check_stale_allowlist(files, allowlist),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", type=Path)
    args = parser.parse_args()

    violations = run_checks(args.repo_root)
    if violations:
        print("Backend test layout violations (see backend/TESTING.md):\n")
        for violation in violations:
            print(f"  {violation}")
        print(f"\n{len(violations)} violation(s).")
        return 1

    print("Backend test layout OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
