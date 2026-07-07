from __future__ import annotations

import ast
from pathlib import Path

_ALEMBIC_VERSION_NUM_LIMIT = 32


def test_alembic_revision_ids_fit_default_version_table() -> None:
    versions_dir = Path(__file__).parents[2] / "alembic" / "versions"

    overlong_revisions: list[str] = []
    for migration_path in sorted(versions_dir.glob("*.py")):
        revision = _assigned_string(migration_path, "revision")
        if revision is not None and len(revision) > _ALEMBIC_VERSION_NUM_LIMIT:
            overlong_revisions.append(
                f"{migration_path.name}: {revision!r} ({len(revision)} chars)"
            )

    assert overlong_revisions == []


def _assigned_string(path: Path, name: str) -> str | None:
    module = ast.parse(path.read_text(), filename=str(path))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return _string_constant(node.value)
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            return _string_constant(node.value)
    return None


def _string_constant(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None
