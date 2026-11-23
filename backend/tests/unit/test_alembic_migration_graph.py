from pathlib import Path

import pytest

from alembic.config import Config
from alembic.script import ScriptDirectory


@pytest.mark.filterwarnings("error:Revision .* is present more than once:UserWarning")
def test_migration_graph_has_one_head() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))

    heads = ScriptDirectory.from_config(config).get_heads()

    assert len(heads) == 1, f"Expected one Alembic head, found: {', '.join(heads)}"


@pytest.mark.parametrize(
    ("current_revision", "required_revision", "already_applied"),
    [
        ("202611091200", "202610201100", "202611081500"),
        ("202610201100", "202611081500", "202610201100"),
        ("202610221200", "202611091200", "202610221200"),
        ("202611161200", "202611190900", "202610201100"),
        ("202611190900", "202610201100", "202611091200"),
        ("202611161210", "202611190900", "202610221200"),
        ("202611201200", "202610221200", "202611190900"),
    ],
)
def test_specialist_stack_upgrade_preserves_applied_revisions(
    current_revision: str, required_revision: str, already_applied: str
) -> None:
    """Either deployed branch must run the missing migrations exactly once."""
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    pending = [
        revision.revision
        for revision in scripts.iterate_revisions(
            "heads", current_revision, implicit_base=True
        )
    ]

    assert required_revision in pending
    assert scripts.get_current_head() in pending
    assert current_revision not in pending
    assert already_applied not in pending
    assert "202610071400" not in pending
    assert len(pending) == len(set(pending))
