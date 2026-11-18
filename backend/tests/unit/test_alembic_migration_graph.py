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
