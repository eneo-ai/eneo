"""Revision 202610041000 renders as offline SQL (`alembic upgrade --sql`) without a database."""

from __future__ import annotations

import io
from pathlib import Path

from alembic import command
from alembic.config import Config


def _offline_sql(revision_range: str, *, downgrade: bool = False) -> str:
    backend = Path(__file__).resolve().parents[3]
    output = io.StringIO()
    config = Config(str(backend / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", "postgresql://offline@localhost/offline")
    if downgrade:
        command.downgrade(config, revision_range, sql=True)
    else:
        command.upgrade(config, revision_range, sql=True)
    return output.getvalue()


def test_upgrade_renders_the_table_indexes_and_the_admin_role_grant() -> None:
    sql = _offline_sql("202610021015:202610041000")

    assert "SET LOCAL lock_timeout = '5s'" in sql
    assert "CREATE TABLE flow_retention_holds (" in sql
    assert (
        "CONSTRAINT fk_flow_retention_holds_flow_tenant FOREIGN KEY(flow_id, tenant_id) "
        "REFERENCES flows (id, tenant_id) ON DELETE CASCADE"
    ) in sql
    for name in (
        "ck_flow_retention_holds_reason_length",
        "ck_flow_retention_holds_ends_after_created",
        "ck_flow_retention_holds_release_complete",
    ):
        assert f"CONSTRAINT {name} CHECK" in sql
    assert (
        "CREATE INDEX ix_flow_retention_holds_active_flow_id ON flow_retention_holds "
        "(flow_id) WHERE released_at IS NULL"
    ) in sql
    assert (
        "CREATE INDEX ix_flow_retention_holds_active_flow_run_id ON flow_retention_holds "
        "(flow_run_id) WHERE released_at IS NULL AND flow_run_id IS NOT NULL"
    ) in sql
    assert (
        "CREATE INDEX ix_flow_retention_holds_flow_id_tenant_id ON flow_retention_holds "
        "(flow_id, tenant_id)"
    ) in sql
    assert "release_reason IS NOT NULL AND char_length(release_reason)" in sql
    for column in ("created_by_user_id", "released_by_user_id"):
        assert (
            f"CREATE INDEX ix_flow_retention_holds_{column} ON flow_retention_holds "
            f"({column}) WHERE {column} IS NOT NULL"
        ) in sql
    for permission in ("retention_manage", "retention_holds"):
        assert (
            "UPDATE roles SET permissions = "
            f"array_append(permissions, '{permission}') "
            "WHERE 'admin' = ANY(permissions) "
            f"AND NOT ('{permission}' = ANY(permissions))"
        ) in sql
    assert "review_by TIMESTAMP WITH TIME ZONE NOT NULL" in sql
    assert "UPDATE alembic_version SET version_num='202610041000'" in sql


def test_downgrade_renders_the_table_drop() -> None:
    sql = _offline_sql("202610041000:202610021015", downgrade=True)

    assert "DROP TABLE flow_retention_holds" in sql
    assert "array_remove(permissions, 'retention_manage')" in sql
    assert "array_remove(permissions, 'retention_holds')" in sql
    assert "UPDATE alembic_version SET version_num='202610021015'" in sql
