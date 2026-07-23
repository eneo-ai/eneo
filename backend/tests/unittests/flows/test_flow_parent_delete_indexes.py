from __future__ import annotations

from pathlib import Path
from runpy import run_path

from sqlalchemy import Index
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from eneo.database.tables.flow_tables import FlowRuns

INDEX_NAME = "ix_flow_runs_job_id"
TABLE_NAME = "flow_runs"
INDEX_COLUMNS = ("job_id",)
MIGRATION_REVISION = "202607232300_flow_run_job_index"
PRIOR_REVISION = "202607230130_review_actor_delete"


def _index_by_name(index_name: str) -> Index:
    for index in FlowRuns.__table__.indexes:
        if index.name == index_name:
            return index
    raise AssertionError(f"Index {index_name} was not found.")


def test_flow_runs_job_parent_delete_index_and_fk_contract() -> None:
    index = _index_by_name(INDEX_NAME)
    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))

    assert tuple(column.name for column in index.columns) == INDEX_COLUMNS
    assert index.unique is False
    assert ddl == f"CREATE INDEX {INDEX_NAME} ON {TABLE_NAME} (job_id)"

    job_foreign_keys = FlowRuns.__table__.c.job_id.foreign_keys
    assert len(job_foreign_keys) == 1
    job_foreign_key = next(iter(job_foreign_keys))
    assert job_foreign_key.target_fullname == "jobs.id"
    assert job_foreign_key.ondelete == "SET NULL"


def test_flow_run_job_index_migration_matches_metadata_contract() -> None:
    migration_path = (
        Path(__file__).parents[3]
        / "alembic"
        / "versions"
        / "202607232300_flow_run_job_index.py"
    )
    migration = run_path(str(migration_path))
    source = migration_path.read_text()

    assert migration["revision"] == MIGRATION_REVISION
    assert migration["down_revision"] == PRIOR_REVISION
    assert migration["_INDEX_NAME"] == INDEX_NAME
    assert migration["_TABLE_NAME"] == TABLE_NAME
    assert migration["_INDEX_COLUMNS"] == INDEX_COLUMNS
    assert source.count("CREATE INDEX CONCURRENTLY IF NOT EXISTS") == 1
    assert source.count("DROP INDEX CONCURRENTLY IF EXISTS") == 1
    assert source.count("autocommit_block()") == 2
