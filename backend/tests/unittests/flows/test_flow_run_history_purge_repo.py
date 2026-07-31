from __future__ import annotations

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import eneo.database.tables  # noqa: F401
from eneo.database.tables.base_class import Base
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import FileContentReferences
from eneo.flows.infrastructure.flow_run_history_purge_repo import (
    FLOW_RUN_HISTORY_PURGE_FILE_REFERENCE_TABLE_NAMES,
    FlowRunHistoryPurgeCounts,
    FlowRunHistoryPurgeResult,
    _uuid_is_in_batch,
)


def test_flow_run_history_purge_file_reference_guard_covers_product_foreign_keys() -> (
    None
):
    product_reference_tables = frozenset(
        table.name
        for table in Base.metadata.tables.values()
        for foreign_key in table.foreign_keys
        if foreign_key.column.table.name == Files.__tablename__
        and foreign_key.column.name == "id"
        and table.name != FileContentReferences.__tablename__
    )

    assert FLOW_RUN_HISTORY_PURGE_FILE_REFERENCE_TABLE_NAMES == product_reference_tables


def test_file_content_references_cascade_through_the_content_release_fence() -> None:
    file_foreign_key = next(
        foreign_key
        for foreign_key in FileContentReferences.__table__.foreign_keys
        if foreign_key.column.table.name == Files.__tablename__
    )

    assert file_foreign_key.ondelete == "CASCADE"
    assert (
        FileContentReferences.__tablename__
        not in FLOW_RUN_HISTORY_PURGE_FILE_REFERENCE_TABLE_NAMES
    )


def test_flow_run_history_purge_result_aggregates_counts_and_identities() -> None:
    first_identity = (uuid4(), uuid4())
    second_identity = (uuid4(), uuid4())

    combined = FlowRunHistoryPurgeResult(
        counts=FlowRunHistoryPurgeCounts(
            flow_runs_considered=1,
            flow_runs_purged=1,
            flow_runtime_source_candidates=2,
            flow_runtime_source_candidate_bytes=200,
            flow_runtime_source_bindings_deleted=1,
            flow_runtime_source_files_deleted=1,
            flow_runtime_source_bytes_deleted=100,
        ),
        affected_flow_tenant_ids=frozenset({first_identity}),
    ).add(
        FlowRunHistoryPurgeResult(
            counts=FlowRunHistoryPurgeCounts(
                flow_runs_considered=2,
                flow_runs_purged=2,
                flow_runtime_source_candidates=3,
                flow_runtime_source_candidate_bytes=300,
                flow_runtime_source_bindings_deleted=2,
                flow_runtime_source_files_deleted=1,
                flow_runtime_source_bytes_deleted=125,
            ),
            affected_flow_tenant_ids=frozenset({first_identity, second_identity}),
        )
    )

    assert combined.counts.flow_runs_considered == 3
    assert combined.counts.flow_runs_lock_deferred == 0
    assert combined.counts.flow_runs_purged == 3
    assert combined.counts.flow_runtime_source_candidates == 5
    assert combined.counts.flow_runtime_source_candidate_bytes == 500
    assert combined.counts.flow_runtime_source_bindings_deleted == 3
    assert combined.counts.flow_runtime_source_files_deleted == 2
    assert combined.counts.flow_runtime_source_bytes_deleted == 225
    assert combined.affected_flow_tenant_ids == frozenset(
        {first_identity, second_identity}
    )


def test_flow_run_history_purge_uuid_batches_use_one_array_bind() -> None:
    file_ids = {UUID(int=value) for value in range(1, 40_001)}
    statement = sa.select(Files.id).where(
        _uuid_is_in_batch(
            Files.id,
            file_ids,
            parameter_name="retention_file_ids",
        )
    )

    compiled = statement.compile(dialect=postgresql.dialect())

    assert "files.id = ANY" in str(compiled)
    assert set(compiled.params) == {"retention_file_ids"}
    assert len(compiled.params["retention_file_ids"]) == 40_000
