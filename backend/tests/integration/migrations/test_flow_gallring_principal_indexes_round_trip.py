"""Round-trip the gallring and principal-deletion indexes (202610021030).

The ORM metadata declares the indexes; the revision creates them concurrently.
The drift check reflects the database and compares each ORM-declared index of the
flows-owned tables: after the revision there is no difference, and before it the
only differences are the new indexes. Indexes later revisions add are absent here
and checked by their own revision's test. The new indexes are also compared by their
normalized DDL text (columns, expressions and predicate), so a wrong column in an
IS NOT NULL predicate fails.

The revision also indexes builder_client_errors.user_id. That table left the ORM
with the AI Builder (202610212200 drops it), so its index is compared with the
definition the revision creates instead.
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import at_revision
from tests.integration.migrations.flow_index_drift import (
    ddl_text,
    flow_owned_tables,
    index_drift,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202610021000"
REVISION = "202610021030"
# The principal indexes are ix_<table>_<column>, partial on <column> IS NOT NULL.
_PRINCIPAL_COLUMNS = {
    "flows": ("created_by_user_id", "owner_user_id"),
    "flow_template_assets": ("created_by_user_id", "updated_by_user_id"),
    "flow_package_imports": ("created_by_user_id",),
    "flow_runtime_uploaded_files": ("owner_user_id", "owner_service_id"),
    "flow_runs": ("principal_user_id", "principal_service_id", "created_by_api_key_id"),
    "flow_run_review_checkpoints": (
        "requester_user_id",
        "requester_service_id",
        "decided_by_user_id",
        "decided_by_service_id",
    ),
    "flow_transcript_corrections": ("edited_by_user_id", "edited_by_service_id"),
    "flow_transcript_correction_revisions": (
        "edited_by_user_id",
        "edited_by_service_id",
    ),
    "flow_run_review_checkpoint_edits": ("edited_by_user_id", "edited_by_service_id"),
}
ORM_INDEX_NAMES = frozenset(
    {
        "ix_flow_provider_calls_resolved_inputs_attempt_id",
        "ix_flow_runtime_uploaded_files_created_at_file_id",
        *(
            f"ix_{table}_{column}"
            for table, columns in _PRINCIPAL_COLUMNS.items()
            for column in columns
        ),
    }
)
# New indexes of tables a later revision drops, so the ORM no longer declares them.
_RETIRED_TABLE_INDEXES = {
    "ix_builder_client_errors_user_id": (
        "CREATE INDEX ix_builder_client_errors_user_id ON builder_client_errors "
        "(user_id) WHERE user_id IS NOT NULL"
    ),
}
NEW_INDEX_NAMES = ORM_INDEX_NAMES | _RETIRED_TABLE_INDEXES.keys()
# ORM-declared indexes that later revisions add, absent at REVISION and checked by
# their own revision's test (202610241000: test_flow_run_listing_indexes_round_trip).
_LATER_INDEX_NAMES = frozenset(
    {
        "ix_flow_runs_flow_listing",
        "ix_flow_runs_flow_user_listing",
        "ix_flow_runs_flow_service_listing",
    }
)


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


@pytest.fixture
def round_trip_db(test_settings):
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True
    engine = sa.create_engine(test_settings.sync_database_url)
    try:
        with at_revision(cfg, REVISION):
            yield {"conn": conn, "cfg": cfg, "engine": engine}
    finally:
        engine.dispose()
        conn.close()


def _index_drift_at_revision(engine: sa.Engine) -> dict[str, str]:
    return index_drift(engine, introduced_later=_LATER_INDEX_NAMES)


def _definition_drift(conn) -> dict[str, tuple[str, str]]:
    """New indexes whose database definition text differs from the ORM declaration."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE indexname = ANY(%s)",
            (sorted(NEW_INDEX_NAMES),),
        )
        actual = dict(cursor.fetchall())
    declared = {
        index.name: str(
            CreateIndex(index).compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        for table in flow_owned_tables()
        for index in table.indexes
        if index.name in ORM_INDEX_NAMES
    }
    assert set(declared) == ORM_INDEX_NAMES, (
        "every live-table index must be ORM-declared"
    )
    declared.update(_RETIRED_TABLE_INDEXES)
    return {
        name: (declared[name], actual.get(name, "<missing>"))
        for name in declared
        if ddl_text(declared[name]) != ddl_text(actual.get(name, "<missing>"))
    }


def _index_oid(conn, name: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT %s::regclass::oid", (name,))
        return cursor.fetchone()[0]


def _invalid_index_count(conn) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_index WHERE NOT indisvalid")
        return cursor.fetchone()[0]


def test_upgrade_matches_the_orm_metadata_and_leaves_no_invalid_index(round_trip_db):
    assert _index_drift_at_revision(round_trip_db["engine"]) == {}
    assert _definition_drift(round_trip_db["conn"]) == {}
    assert _invalid_index_count(round_trip_db["conn"]) == 0


def test_downgrade_removes_exactly_the_new_indexes_and_upgrade_restores_them(
    round_trip_db,
):
    conn, cfg, engine = (
        round_trip_db["conn"],
        round_trip_db["cfg"],
        round_trip_db["engine"],
    )

    command.downgrade(cfg, PRE_REVISION)
    drift = _index_drift_at_revision(engine)
    assert set(drift.values()) == {"missing"}
    assert set(drift) == ORM_INDEX_NAMES
    assert {
        name
        for name, (_, actual) in _definition_drift(conn).items()
        if actual == "<missing>"
    } == NEW_INDEX_NAMES

    command.upgrade(cfg, REVISION)
    assert _index_drift_at_revision(engine) == {}
    assert _definition_drift(conn) == {}
    assert _invalid_index_count(conn) == 0


def test_rerun_after_a_failed_concurrent_build_replaces_the_invalid_index(
    round_trip_db,
):
    conn, cfg = round_trip_db["conn"], round_trip_db["cfg"]
    name = "ix_flow_runtime_uploaded_files_created_at_file_id"
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE pg_index SET indisvalid = false WHERE indexrelid = %s::regclass",
            (name,),
        )
    assert _invalid_index_count(conn) == 1
    valid_oid = _index_oid(conn, "ix_flow_runs_principal_user_id")

    # Rewind the version stamp only: the revision runs again over the leftovers.
    command.stamp(cfg, PRE_REVISION)
    command.upgrade(cfg, REVISION)
    assert _invalid_index_count(conn) == 0
    assert _index_drift_at_revision(round_trip_db["engine"]) == {}
    # Only the invalid leftover is rebuilt; a valid index is left alone.
    assert _index_oid(conn, "ix_flow_runs_principal_user_id") == valid_oid
