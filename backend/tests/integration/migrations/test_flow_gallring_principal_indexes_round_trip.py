"""Round-trip the gallring and principal-deletion indexes (202610021030).

The ORM metadata declares the indexes; the revision creates them concurrently.
The drift check reflects the database and compares each ORM-declared index of the
flows-owned tables: after the revision there is no difference, and before it the
only differences are the new indexes. The new indexes are also compared by their
normalized DDL text (columns, expressions and predicate), so a wrong column in an
IS NOT NULL predicate fails.
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

import eneo.database.tables  # noqa: F401
from alembic import command
from alembic.config import Config
from eneo.database.tables import flow_tables
from eneo.database.tables.base_class import Base

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
    "builder_client_errors": ("user_id",),
}
NEW_INDEX_NAMES = frozenset(
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
    command.upgrade(cfg, REVISION)
    engine = sa.create_engine(test_settings.sync_database_url)
    try:
        yield {"conn": conn, "cfg": cfg, "engine": engine}
    finally:
        engine.dispose()
        conn.close()


def _flow_owned_tables() -> list[sa.Table]:
    return [
        cls.__table__
        for cls in vars(flow_tables).values()
        if isinstance(cls, type)
        and cls.__module__ == flow_tables.__name__
        and issubclass(cls, Base)
        and hasattr(cls, "__table__")
    ]


def _normalized(parts: list[str]) -> list[str]:
    # Reflection reports the sort direction in dialect options, not in the column.
    return [part.lower().replace(" ", "").removesuffix("desc") for part in parts]


def _index_drift(engine: sa.Engine) -> dict[str, str]:
    """ORM-declared indexes of the flows-owned tables the database lacks or defines differently.

    Alembic's autogenerate cannot run over this metadata (the builder tables form a
    foreign-key cycle), so the declared shape is compared with the reflected one.
    """
    inspector = sa.inspect(engine)
    drift: dict[str, str] = {}
    for table in _flow_owned_tables():
        # A table a later revision adds is checked by that revision's own test.
        if not inspector.has_table(table.name):
            continue
        reflected = {
            index["name"]: index for index in inspector.get_indexes(table.name)
        }
        for index in table.indexes:
            actual = reflected.get(index.name)
            if actual is None:
                drift[index.name] = "missing"
                continue
            declared_columns = [
                expression.name
                if isinstance(expression, sa.Column)
                else str(expression)
                for expression in index.expressions
            ]
            actual_columns = actual.get("expressions") or actual["column_names"]
            declared_where = index.dialect_options["postgresql"]["where"]
            if _normalized(declared_columns) != _normalized(actual_columns):
                drift[index.name] = f"columns {actual_columns}"
            elif bool(index.unique) != bool(actual["unique"]):
                drift[index.name] = "uniqueness"
            elif (declared_where is None) != (
                "postgresql_where" not in actual["dialect_options"]
            ):
                drift[index.name] = "partial predicate"
            elif list(index.dialect_options["postgresql"]["include"] or []) != list(
                actual.get("include_columns") or []
            ):
                drift[index.name] = "include columns"
    return drift


def _ddl_text(ddl: str) -> str:
    """Comparable form of an index definition: ORM CreateIndex vs pg_indexes.indexdef."""
    text = ddl.lower().replace("public.", "").replace(" using btree", "")
    return "".join(ch for ch in text if ch not in ' ()"\n;')


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
        for table in _flow_owned_tables()
        for index in table.indexes
        if index.name in NEW_INDEX_NAMES
    }
    assert set(declared) == NEW_INDEX_NAMES, "every new index must be ORM-declared"
    return {
        name: (declared[name], actual.get(name, "<missing>"))
        for name in declared
        if _ddl_text(declared[name]) != _ddl_text(actual.get(name, "<missing>"))
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
    assert _index_drift(round_trip_db["engine"]) == {}
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
    drift = _index_drift(engine)
    assert set(drift.values()) == {"missing"}
    assert set(drift) == NEW_INDEX_NAMES

    command.upgrade(cfg, REVISION)
    assert _index_drift(engine) == {}
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
    assert _index_drift(round_trip_db["engine"]) == {}
    # Only the invalid leftover is rebuilt; a valid index is left alone.
    assert _index_oid(conn, "ix_flow_runs_principal_user_id") == valid_oid
