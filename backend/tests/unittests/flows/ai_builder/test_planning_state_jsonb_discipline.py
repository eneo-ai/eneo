"""Static guards that keep `planning_state_jsonb` reads and writes
confined to the typed `save_planning_state` / `load_planning_state`
repository methods.

Any raw JSONB mutation (`jsonb_set`, `jsonb_insert`, path merges via
`||`, SET-style `column ->`) or raw read (`planning_state_jsonb ->`,
`planning_state_jsonb ->>`) elsewhere in AI Builder source would make
the full-snapshot discipline unenforceable: partial writes could
bypass Pydantic validation, and ad-hoc reads could drift from the
typed model. This file regresses such drift from reappearing.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND_SRC = Path(__file__).resolve().parents[4] / "src" / "eneo"
AI_BUILDER_DIR = BACKEND_SRC / "flows" / "ai_builder"

# Typed save/load for `planning_state_jsonb` lives here. This module is
# the only legitimate site for raw JSONB writes and path-operator reads.
_SAVE_LOAD_OWNER = AI_BUILDER_DIR / "ai_builder_repo.py"

# Pure Pydantic model that names the forbidden patterns in its module
# docstring. No SQL touches this file, so it is allow-listed for both
# checks — its mention of `jsonb_set` is documentation, not usage.
_MODEL_MODULE = AI_BUILDER_DIR / "planning_state.py"

# Patterns that mutate JSONB directly, bypassing the typed save path.
_FORBIDDEN_WRITE_PATTERNS = (
    re.compile(r"\bjsonb_set\b"),
    re.compile(r"\bjsonb_insert\b"),
    re.compile(r"planning_state_jsonb\s*\|\|"),
)

# Patterns that read JSONB via path operators, bypassing the typed load path.
_FORBIDDEN_READ_PATTERNS = (
    re.compile(r"planning_state_jsonb\s*->"),
    re.compile(r"planning_state_jsonb\s*->>"),
)


def _iter_ai_builder_python_files() -> list[Path]:
    return sorted(
        path for path in AI_BUILDER_DIR.rglob("*.py") if "__pycache__" not in path.parts
    )


def _find_forbidden_hits(
    path: Path,
    patterns: tuple[re.Pattern[str], ...],
) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for lineno, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        for pattern in patterns:
            if pattern.search(raw_line):
                hits.append((lineno, raw_line))
                break
    return hits


def test_save_load_owner_module_exists() -> None:
    """Anchor: if this module moves or is renamed, the allow-list below
    must be updated in the same commit. Failing here means the
    discipline guard has become stale.
    """
    assert _SAVE_LOAD_OWNER.is_file(), (
        f"{_SAVE_LOAD_OWNER} missing — JSONB discipline allow-list is stale."
    )


def test_no_raw_jsonb_writes_on_planning_state_jsonb() -> None:
    """No module in `backend/src/eneo/flows/ai_builder/` may use
    `jsonb_set`, `jsonb_insert`, or `||` on `planning_state_jsonb`. The
    only write path is `AIBuilderRepository.save_planning_state`, which
    replaces the full snapshot via `UPDATE ... SET planning_state_jsonb = ...`.
    """
    allow = {_SAVE_LOAD_OWNER.resolve(), _MODEL_MODULE.resolve()}
    violations: list[str] = []
    for path in _iter_ai_builder_python_files():
        if path.resolve() in allow:
            continue
        hits = _find_forbidden_hits(path, _FORBIDDEN_WRITE_PATTERNS)
        for lineno, text in hits:
            violations.append(f"{path}:{lineno}: {text.rstrip()}")

    assert not violations, (
        "Forbidden raw JSONB write on planning_state_jsonb — route through "
        "AIBuilderRepository.save_planning_state:\n  " + "\n  ".join(violations)
    )


def test_no_raw_jsonb_reads_on_planning_state_jsonb() -> None:
    """No module in `backend/src/eneo/flows/ai_builder/` may read
    `planning_state_jsonb` via `->` or `->>` path operators. The only
    read path is `AIBuilderRepository.load_planning_state`, which
    returns the typed `PlanningState` Pydantic model.
    """
    allow = {_SAVE_LOAD_OWNER.resolve(), _MODEL_MODULE.resolve()}
    violations: list[str] = []
    for path in _iter_ai_builder_python_files():
        if path.resolve() in allow:
            continue
        hits = _find_forbidden_hits(path, _FORBIDDEN_READ_PATTERNS)
        for lineno, text in hits:
            violations.append(f"{path}:{lineno}: {text.rstrip()}")

    assert not violations, (
        "Forbidden raw JSONB read on planning_state_jsonb — route through "
        "AIBuilderRepository.load_planning_state:\n  " + "\n  ".join(violations)
    )
