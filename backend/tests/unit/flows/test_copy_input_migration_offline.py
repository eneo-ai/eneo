"""The copy mode's static constraint renders without a database in both directions."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from alembic import command
from alembic.config import Config


@pytest.mark.parametrize("downgrade", [False, True])
def test_copy_input_constraint_is_static_offline_sql(downgrade):
    # Kills a historical migration edit, missing mode, online catalogue read, or
    # a validated CHECK that scans the table under the DDL lock.
    backend = Path(__file__).resolve().parents[3]
    output = io.StringIO()
    config = Config(str(backend / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", "postgresql://offline@localhost/offline")
    if downgrade:
        command.downgrade(config, "202610142100:202610121300", sql=True)
    else:
        command.upgrade(config, "202610121300:202610142100", sql=True)
    sql = output.getvalue()
    assert "SET LOCAL lock_timeout = '5s'" in sql
    assert "DROP CONSTRAINT ck_flow_steps_output_mode" in sql
    assert "ADD CONSTRAINT ck_flow_steps_output_mode CHECK" in sql
    assert "NOT VALID" in sql
    assert "VALIDATE CONSTRAINT ck_flow_steps_output_mode" in sql
    assert ("'copy_input'" in sql) is not downgrade
    assert "'speaker_mapping'" in sql
