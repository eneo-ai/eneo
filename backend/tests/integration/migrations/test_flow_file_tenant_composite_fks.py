"""PostgreSQL contract for tenant-scoped Flow file relationships."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest
import sqlalchemy as sa
from psycopg2.extensions import connection as PsycopgConnection

from alembic import command
from alembic.config import Config
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    BuilderSessionFiles,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowRuntimeUploadedFiles,
    FlowTemplateAssets,
)
from tests.integration.migrations.alembic_test_utils import (
    current_revisions,
    reset_public_schema,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "202607081035_compose_text"
MIGRATION_REVISION = "202607111200_file_tenant_fks"


@dataclass(frozen=True)
class _GraphIds:
    tenant_a: UUID
    user_a: UUID
    tenant_b: UUID
    user_b: UUID
    space_b: UUID
    flow_b: UUID
    run_b: UUID
    step_id: UUID
    step_result_id: UUID
    session_b: UUID


@dataclass(frozen=True)
class _RelationshipFiles:
    template: UUID
    runtime_upload: UUID
    result: UUID
    builder: UUID


@dataclass(frozen=True)
class _MigrationDb:
    conn: PsycopgConnection
    cfg: Config


_RELATIONSHIP_CONSTRAINTS = (
    (
        "flow_template_assets",
        "fk_flow_template_assets_file_tenant",
        "flow_template_assets_file_id_fkey",
        "RESTRICT",
    ),
    (
        "flow_runtime_uploaded_files",
        "fk_flow_runtime_uploaded_files_file_tenant",
        "fk_flow_runtime_uploaded_files_file_id_files",
        "CASCADE",
    ),
    (
        "flow_run_step_result_files",
        "fk_flow_run_step_result_files_file_tenant",
        "fk_flow_run_step_result_files_file_id_files",
        "RESTRICT",
    ),
    (
        "builder_session_files",
        "fk_builder_session_files_file_tenant",
        "builder_session_files_file_id_fkey",
        "CASCADE",
    ),
)


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parents[3]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database() -> Iterator[None]:
    yield


@pytest.fixture(autouse=True)
def seed_default_models() -> Iterator[None]:
    yield


@pytest.fixture
def migration_db(test_settings) -> Iterator[_MigrationDb]:
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True

    reset_public_schema(conn)
    command.upgrade(cfg, PRIOR_REVISION)
    try:
        yield _MigrationDb(conn=conn, cfg=cfg)
    finally:
        reset_public_schema(conn)
        command.upgrade(cfg, "head")
        conn.close()


def _seed_relationship_graph(conn: PsycopgConnection) -> _GraphIds:
    ids = _GraphIds(
        tenant_a=uuid4(),
        user_a=uuid4(),
        tenant_b=uuid4(),
        user_b=uuid4(),
        space_b=uuid4(),
        flow_b=uuid4(),
        run_b=uuid4(),
        step_id=uuid4(),
        step_result_id=uuid4(),
        session_b=uuid4(),
    )
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (%s, %s, 1000000, 'active')
            """,
            (
                (ids.tenant_a, f"file-tenant-a-{ids.tenant_a}"),
                (ids.tenant_b, f"file-tenant-b-{ids.tenant_b}"),
            ),
        )
        cur.executemany(
            """
            INSERT INTO users (
                id,
                email,
                state,
                tenant_id,
                quota_limit,
                used_tokens
            )
            VALUES (%s, %s, 'active', %s, NULL, 0)
            """,
            (
                (ids.user_a, f"{ids.user_a}@example.invalid", ids.tenant_a),
                (ids.user_b, f"{ids.user_b}@example.invalid", ids.tenant_b),
            ),
        )
        cur.execute(
            """
            INSERT INTO spaces (id, name, tenant_id, user_id)
            VALUES (%s, 'Flow file tenant migration', %s, NULL)
            """,
            (ids.space_b, ids.tenant_b),
        )
        cur.execute(
            """
            INSERT INTO flows (
                id,
                name,
                tenant_id,
                space_id,
                created_by_user_id,
                owner_user_id
            )
            VALUES (%s, 'Flow file tenant migration', %s, %s, %s, %s)
            """,
            (ids.flow_b, ids.tenant_b, ids.space_b, ids.user_b, ids.user_b),
        )
        cur.execute(
            """
            INSERT INTO flow_versions (
                flow_id,
                version,
                tenant_id,
                definition_checksum,
                definition_json
            )
            VALUES (%s, 1, %s, 'file-tenant-migration', '{}'::jsonb)
            """,
            (ids.flow_b, ids.tenant_b),
        )
        cur.execute(
            """
            INSERT INTO flow_runs (
                id,
                flow_id,
                flow_version,
                principal_type,
                principal_user_id,
                tenant_id,
                trace_id,
                status
            )
            VALUES (%s, %s, 1, 'user', %s, %s, %s, 'completed')
            """,
            (ids.run_b, ids.flow_b, ids.user_b, ids.tenant_b, uuid4()),
        )
        cur.execute(
            """
            INSERT INTO flow_step_results (
                id,
                flow_run_id,
                flow_id,
                tenant_id,
                step_id,
                step_order,
                status,
                current_attempt_no
            )
            VALUES (%s, %s, %s, %s, %s, 1, 'completed', 1)
            """,
            (
                ids.step_result_id,
                ids.run_b,
                ids.flow_b,
                ids.tenant_b,
                ids.step_id,
            ),
        )
        cur.execute(
            """
            INSERT INTO flow_step_attempts (
                id,
                flow_run_id,
                flow_id,
                tenant_id,
                step_id,
                step_order,
                attempt_no,
                status,
                started_at
            )
            VALUES (%s, %s, %s, %s, %s, 1, 1, 'completed', now())
            """,
            (uuid4(), ids.run_b, ids.flow_b, ids.tenant_b, ids.step_id),
        )
        cur.execute(
            """
            INSERT INTO builder_sessions (
                id,
                tenant_id,
                space_id,
                target_kind,
                status,
                actor_user_id,
                conversation
            )
            VALUES (%s, %s, %s, 'create', 'chatting', %s, '[]'::jsonb)
            """,
            (ids.session_b, ids.tenant_b, ids.space_b, ids.user_b),
        )
    return ids


def _insert_relationship_files(
    conn: PsycopgConnection,
    *,
    tenant_id: UUID,
    user_id: UUID,
) -> _RelationshipFiles:
    files = _RelationshipFiles(
        template=uuid4(),
        runtime_upload=uuid4(),
        result=uuid4(),
        builder=uuid4(),
    )
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO files (
                id,
                name,
                checksum,
                size,
                mimetype,
                file_type,
                owner_type,
                owner_user_id,
                tenant_id
            )
            VALUES (%s, %s, %s, 8, 'text/plain', 'text', 'user', %s, %s)
            """,
            tuple(
                (
                    file_id,
                    f"{relationship}.txt",
                    f"{relationship}-{file_id}",
                    user_id,
                    tenant_id,
                )
                for relationship, file_id in (
                    ("template", files.template),
                    ("runtime-upload", files.runtime_upload),
                    ("result", files.result),
                    ("builder", files.builder),
                )
            ),
        )
    return files


def _insert_relationship_rows(
    conn: PsycopgConnection,
    *,
    graph: _GraphIds,
    files: _RelationshipFiles,
    result_ordinal: int = 0,
) -> None:
    _insert_template_asset(conn, graph=graph, file_id=files.template)
    _insert_runtime_upload(conn, graph=graph, file_id=files.runtime_upload)
    _insert_result_file(
        conn,
        graph=graph,
        file_id=files.result,
        ordinal=result_ordinal,
    )
    _insert_builder_file(conn, graph=graph, file_id=files.builder)


def _insert_template_asset(
    conn: PsycopgConnection,
    *,
    graph: _GraphIds,
    file_id: UUID,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO flow_template_assets (
                flow_id,
                space_id,
                tenant_id,
                file_id,
                name,
                checksum
            )
            VALUES (%s, %s, %s, %s, 'template.docx', 'template-checksum')
            """,
            (graph.flow_b, graph.space_b, graph.tenant_b, file_id),
        )


def _insert_runtime_upload(
    conn: PsycopgConnection,
    *,
    graph: _GraphIds,
    file_id: UUID,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO flow_runtime_uploaded_files (
                file_id,
                flow_id,
                tenant_id,
                uploaded_for_step_id,
                owner_type,
                owner_user_id
            )
            VALUES (%s, %s, %s, %s, 'user', %s)
            """,
            (
                file_id,
                graph.flow_b,
                graph.tenant_b,
                graph.step_id,
                graph.user_b,
            ),
        )


def _insert_result_file(
    conn: PsycopgConnection,
    *,
    graph: _GraphIds,
    file_id: UUID,
    ordinal: int,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO flow_run_step_result_files (
                flow_run_id,
                flow_id,
                tenant_id,
                step_result_id,
                step_id,
                step_order,
                attempt_no,
                file_id,
                ordinal,
                source
            )
            VALUES (%s, %s, %s, %s, %s, 1, 1, %s, %s, 'generated_output')
            """,
            (
                graph.run_b,
                graph.flow_b,
                graph.tenant_b,
                graph.step_result_id,
                graph.step_id,
                file_id,
                ordinal,
            ),
        )


def _insert_builder_file(
    conn: PsycopgConnection,
    *,
    graph: _GraphIds,
    file_id: UUID,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO builder_session_files (session_id, file_id, tenant_id)
            VALUES (%s, %s, %s)
            """,
            (graph.session_b, file_id, graph.tenant_b),
        )


def _foreign_key(table: sa.Table, name: str) -> sa.ForeignKeyConstraint:
    for constraint in table.foreign_key_constraints:
        if constraint.name == name:
            return constraint
    raise AssertionError(f"Foreign key constraint {name} was not found")


def _constraint_state(
    conn: PsycopgConnection,
    table_name: str,
    constraint_name: str,
) -> tuple[str, bool] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_constraintdef(constraint_row.oid), constraint_row.convalidated
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS table_row ON table_row.oid = constraint_row.conrelid
            JOIN pg_namespace AS namespace_row
              ON namespace_row.oid = table_row.relnamespace
            WHERE namespace_row.nspname = 'public'
              AND table_row.relname = %s
              AND constraint_row.conname = %s
            """,
            (table_name, constraint_name),
        )
        row = cur.fetchone()
    return (str(row[0]), bool(row[1])) if row else None


def _index_state(
    conn: PsycopgConnection,
    index_name: str,
) -> tuple[tuple[str, ...], bool, bool] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                array_agg(attribute_row.attname ORDER BY index_key.ordinality),
                index_metadata.indisunique,
                index_metadata.indisvalid
            FROM pg_class AS index_row
            JOIN pg_namespace AS namespace_row
              ON namespace_row.oid = index_row.relnamespace
            JOIN pg_index AS index_metadata
              ON index_metadata.indexrelid = index_row.oid
            JOIN pg_class AS table_row
              ON table_row.oid = index_metadata.indrelid
            JOIN unnest(index_metadata.indkey)
              WITH ORDINALITY AS index_key(attnum, ordinality)
              ON true
            JOIN pg_attribute AS attribute_row
              ON attribute_row.attrelid = table_row.oid
             AND attribute_row.attnum = index_key.attnum
            WHERE namespace_row.nspname = 'public'
              AND index_row.relname = %s
            GROUP BY index_metadata.indisunique, index_metadata.indisvalid
            """,
            (index_name,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return tuple(row[0]), bool(row[1]), bool(row[2])


def _assert_runtime_provenance_constraint(conn: PsycopgConnection) -> None:
    state = _constraint_state(
        conn,
        "flow_run_step_input_files",
        "fk_flow_run_step_input_files_runtime_upload",
    )
    assert state is not None
    definition, validated = state
    assert validated is True
    assert "FOREIGN KEY (file_id, flow_id, tenant_id)" in definition
    assert (
        "REFERENCES flow_runtime_uploaded_files(file_id, flow_id, tenant_id)"
        in definition
    )
    assert "ON DELETE RESTRICT" in definition


def _assert_upgraded_schema(conn: PsycopgConnection) -> None:
    assert current_revisions(conn) == {MIGRATION_REVISION}
    unique_state = _constraint_state(conn, "files", "uq_files_id_tenant_id")
    assert unique_state == ("UNIQUE (id, tenant_id)", True)
    assert _index_state(conn, "ix_files_id_tenant_id_unique") is None
    assert _index_state(conn, "uq_files_id_tenant_id") == (
        ("id", "tenant_id"),
        True,
        True,
    )
    assert _index_state(conn, "ix_builder_session_files_file_id") == (
        ("file_id",),
        False,
        True,
    )

    for (
        table,
        composite_constraint,
        legacy_constraint,
        ondelete,
    ) in _RELATIONSHIP_CONSTRAINTS:
        state = _constraint_state(conn, table, composite_constraint)
        assert state is not None
        definition, validated = state
        assert validated is True
        assert "FOREIGN KEY (file_id, tenant_id)" in definition
        assert "REFERENCES files(id, tenant_id)" in definition
        assert f"ON DELETE {ondelete}" in definition
        assert _constraint_state(conn, table, legacy_constraint) is None

    _assert_runtime_provenance_constraint(conn)


def _assert_prior_schema(conn: PsycopgConnection) -> None:
    assert current_revisions(conn) == {PRIOR_REVISION}
    assert _constraint_state(conn, "files", "uq_files_id_tenant_id") is None
    assert _index_state(conn, "uq_files_id_tenant_id") is None
    assert _index_state(conn, "ix_files_id_tenant_id_unique") is None
    assert _index_state(conn, "ix_builder_session_files_file_id") is None

    for (
        table,
        composite_constraint,
        legacy_constraint,
        ondelete,
    ) in _RELATIONSHIP_CONSTRAINTS:
        assert _constraint_state(conn, table, composite_constraint) is None
        state = _constraint_state(conn, table, legacy_constraint)
        assert state is not None
        definition, validated = state
        assert validated is True
        assert "FOREIGN KEY (file_id)" in definition
        assert "REFERENCES files(id)" in definition
        assert f"ON DELETE {ondelete}" in definition

    _assert_runtime_provenance_constraint(conn)


def test_models_declare_composite_file_tenant_identity() -> None:
    file_identity = next(
        (
            constraint
            for constraint in Files.__table__.constraints
            if isinstance(constraint, sa.UniqueConstraint)
            and constraint.name == "uq_files_id_tenant_id"
        ),
        None,
    )
    assert file_identity is not None
    assert tuple(column.name for column in file_identity.columns) == (
        "id",
        "tenant_id",
    )

    expected_relationships = (
        (
            FlowTemplateAssets.__table__,
            "fk_flow_template_assets_file_tenant",
            "RESTRICT",
        ),
        (
            FlowRuntimeUploadedFiles.__table__,
            "fk_flow_runtime_uploaded_files_file_tenant",
            "CASCADE",
        ),
        (
            FlowRunStepResultFiles.__table__,
            "fk_flow_run_step_result_files_file_tenant",
            "RESTRICT",
        ),
        (
            BuilderSessionFiles.__table__,
            "fk_builder_session_files_file_tenant",
            "CASCADE",
        ),
    )
    for table, constraint_name, ondelete in expected_relationships:
        constraint = _foreign_key(table, constraint_name)
        assert tuple(column.name for column in constraint.columns) == (
            "file_id",
            "tenant_id",
        )
        assert tuple(element.column.table.name for element in constraint.elements) == (
            "files",
            "files",
        )
        assert tuple(element.column.name for element in constraint.elements) == (
            "id",
            "tenant_id",
        )
        assert constraint.ondelete == ondelete
        file_constraints = tuple(
            candidate
            for candidate in table.foreign_key_constraints
            if candidate.elements
            and all(
                element.column.table.name == "files" for element in candidate.elements
            )
        )
        assert file_constraints == (constraint,)

    runtime_provenance = _foreign_key(
        FlowRunStepInputFiles.__table__,
        "fk_flow_run_step_input_files_runtime_upload",
    )
    assert tuple(column.name for column in runtime_provenance.columns) == (
        "file_id",
        "flow_id",
        "tenant_id",
    )
    assert tuple(
        (element.column.table.name, element.column.name)
        for element in runtime_provenance.elements
    ) == (
        ("flow_runtime_uploaded_files", "file_id"),
        ("flow_runtime_uploaded_files", "flow_id"),
        ("flow_runtime_uploaded_files", "tenant_id"),
    )
    assert runtime_provenance.ondelete == "RESTRICT"

    builder_file_index = next(
        (
            index
            for index in BuilderSessionFiles.__table__.indexes
            if index.name == "ix_builder_session_files_file_id"
        ),
        None,
    )
    assert builder_file_index is not None
    assert tuple(column.name for column in builder_file_index.columns) == ("file_id",)

    assert any(
        index.name == "ix_flow_template_assets_file_id"
        and tuple(column.name for column in index.columns) == ("file_id",)
        for index in FlowTemplateAssets.__table__.indexes
    )
    assert tuple(
        column.name for column in FlowRuntimeUploadedFiles.__table__.primary_key.columns
    ) == ("file_id",)
    assert any(
        index.name == "ix_flow_run_step_result_files_file_id"
        and tuple(column.name for column in index.columns) == ("file_id",)
        for index in FlowRunStepResultFiles.__table__.indexes
    )
    for table, _, _ in expected_relationships:
        assert all(
            tuple(column.name for column in index.columns) != ("file_id", "tenant_id")
            for index in table.indexes
        )


def test_upgrade_reports_all_tenant_mismatches_before_ddl(
    migration_db: _MigrationDb,
) -> None:
    conn = migration_db.conn
    cfg = migration_db.cfg
    graph = _seed_relationship_graph(conn)
    mismatched_files = _insert_relationship_files(
        conn,
        tenant_id=graph.tenant_a,
        user_id=graph.user_a,
    )
    _insert_relationship_rows(conn, graph=graph, files=mismatched_files)

    with pytest.raises(RuntimeError) as exc:
        command.upgrade(cfg, MIGRATION_REVISION)

    message = str(exc.value)
    for table_name, file_id in (
        ("flow_template_assets", mismatched_files.template),
        ("flow_runtime_uploaded_files", mismatched_files.runtime_upload),
        ("flow_run_step_result_files", mismatched_files.result),
        ("builder_session_files", mismatched_files.builder),
    ):
        assert f"1 tenant-mismatched file relationship in {table_name}" in message
        assert str(file_id) in message
    assert "Repair or delete the mismatched rows" in message
    _assert_prior_schema(conn)


def test_clean_upgrade_enforces_all_file_tenant_relationships(
    migration_db: _MigrationDb,
) -> None:
    conn = migration_db.conn
    cfg = migration_db.cfg
    graph = _seed_relationship_graph(conn)

    command.upgrade(cfg, MIGRATION_REVISION)
    _assert_upgraded_schema(conn)

    same_tenant_files = _insert_relationship_files(
        conn,
        tenant_id=graph.tenant_b,
        user_id=graph.user_b,
    )
    _insert_relationship_rows(conn, graph=graph, files=same_tenant_files)

    cross_tenant_files = _insert_relationship_files(
        conn,
        tenant_id=graph.tenant_a,
        user_id=graph.user_a,
    )
    with pytest.raises(psycopg2.errors.ForeignKeyViolation) as template_exc:
        _insert_template_asset(
            conn,
            graph=graph,
            file_id=cross_tenant_files.template,
        )
    assert (
        template_exc.value.diag.constraint_name == "fk_flow_template_assets_file_tenant"
    )

    with pytest.raises(psycopg2.errors.ForeignKeyViolation) as runtime_exc:
        _insert_runtime_upload(
            conn,
            graph=graph,
            file_id=cross_tenant_files.runtime_upload,
        )
    assert (
        runtime_exc.value.diag.constraint_name
        == "fk_flow_runtime_uploaded_files_file_tenant"
    )

    with pytest.raises(psycopg2.errors.ForeignKeyViolation) as result_exc:
        _insert_result_file(
            conn,
            graph=graph,
            file_id=cross_tenant_files.result,
            ordinal=1,
        )
    assert (
        result_exc.value.diag.constraint_name
        == "fk_flow_run_step_result_files_file_tenant"
    )

    with pytest.raises(psycopg2.errors.ForeignKeyViolation) as builder_exc:
        _insert_builder_file(
            conn,
            graph=graph,
            file_id=cross_tenant_files.builder,
        )
    assert (
        builder_exc.value.diag.constraint_name == "fk_builder_session_files_file_tenant"
    )


def test_downgrade_restores_legacy_fks_and_replays_to_head(
    migration_db: _MigrationDb,
) -> None:
    conn = migration_db.conn
    cfg = migration_db.cfg
    graph = _seed_relationship_graph(conn)
    same_tenant_files = _insert_relationship_files(
        conn,
        tenant_id=graph.tenant_b,
        user_id=graph.user_b,
    )
    _insert_relationship_rows(conn, graph=graph, files=same_tenant_files)

    command.upgrade(cfg, MIGRATION_REVISION)
    _assert_upgraded_schema(conn)

    command.downgrade(cfg, PRIOR_REVISION)
    _assert_prior_schema(conn)
    with conn.cursor() as cur:
        for table_name in (
            "flow_template_assets",
            "flow_runtime_uploaded_files",
            "flow_run_step_result_files",
            "builder_session_files",
        ):
            cur.execute(f"SELECT count(*) FROM {table_name}")
            assert cur.fetchone()[0] == 1

    command.upgrade(cfg, "head")
    _assert_upgraded_schema(conn)


def test_upgrade_resumes_after_committed_constraint_handoff_phase(
    migration_db: _MigrationDb,
) -> None:
    conn = migration_db.conn
    cfg = migration_db.cfg

    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE UNIQUE INDEX CONCURRENTLY ix_files_id_tenant_id_unique
            ON files (id, tenant_id)
            """
        )
        cur.execute(
            """
            CREATE INDEX CONCURRENTLY ix_builder_session_files_file_id
            ON builder_session_files (file_id)
            """
        )
        cur.execute(
            """
            ALTER TABLE files
            ADD CONSTRAINT uq_files_id_tenant_id
            UNIQUE USING INDEX ix_files_id_tenant_id_unique
            """
        )
        for table, composite_constraint, _, ondelete in _RELATIONSHIP_CONSTRAINTS:
            cur.execute(
                f"""
                ALTER TABLE {table}
                ADD CONSTRAINT {composite_constraint}
                FOREIGN KEY (file_id, tenant_id)
                REFERENCES files (id, tenant_id)
                ON DELETE {ondelete}
                NOT VALID
                """
            )
            cur.execute(
                f"ALTER TABLE {table} VALIDATE CONSTRAINT {composite_constraint}"
            )
        cur.execute(
            """
            ALTER TABLE flow_template_assets
            DROP CONSTRAINT flow_template_assets_file_id_fkey
            """
        )

    assert current_revisions(conn) == {PRIOR_REVISION}
    command.upgrade(cfg, MIGRATION_REVISION)
    _assert_upgraded_schema(conn)


def test_migration_orders_online_constraint_handoff() -> None:
    migration_path = (
        Path(__file__).parents[3]
        / "alembic"
        / "versions"
        / "202607111200_flow_file_tenant_fks.py"
    )
    source = migration_path.read_text(encoding="utf-8")
    upgrade_source, downgrade_source = source.split("def downgrade() -> None:", 1)
    upgrade_source = upgrade_source.split("def upgrade() -> None:", 1)[1]
    phase_marker = "with op.get_context().autocommit_block():"

    assert upgrade_source.index(
        "_assert_existing_relationships_are_tenant_consistent()"
    ) < upgrade_source.index("autocommit_block()")
    assert upgrade_source.count(phase_marker) >= 5
    assert "CREATE UNIQUE INDEX CONCURRENTLY" in upgrade_source
    assert "CREATE INDEX CONCURRENTLY" in upgrade_source
    assert "UNIQUE USING INDEX" in upgrade_source
    add_composites = upgrade_source.index(
        "for table, composite_constraint, _, ondelete"
    )
    validate_composites = upgrade_source.index("for table, composite_constraint, _, _")
    drop_legacy = upgrade_source.index("for table, _, legacy_constraint, _")
    assert add_composites < validate_composites < drop_legacy
    assert "NOT VALID" in upgrade_source[add_composites:validate_composites]
    upgrade_phase_starts = {
        upgrade_source.rfind(phase_marker, 0, operation)
        for operation in (
            upgrade_source.index("CREATE UNIQUE INDEX CONCURRENTLY"),
            upgrade_source.index("UNIQUE USING INDEX"),
            add_composites,
            validate_composites,
            drop_legacy,
        )
    }
    assert -1 not in upgrade_phase_starts
    assert len(upgrade_phase_starts) == 5

    assert downgrade_source.count(phase_marker) >= 5
    restore_legacy = downgrade_source.index("for table, _, legacy_constraint, ondelete")
    validate_legacy = downgrade_source.index("for table, _, legacy_constraint, _")
    drop_composites = downgrade_source.index("for table, composite_constraint, _, _")
    drop_parent_unique = downgrade_source.index(
        "ALTER TABLE files DROP CONSTRAINT IF EXISTS"
    )
    drop_builder_index = downgrade_source.index(
        "DROP INDEX CONCURRENTLY IF EXISTS {_BUILDER_FILE_INDEX}"
    )
    assert (
        restore_legacy
        < validate_legacy
        < drop_composites
        < drop_parent_unique
        < drop_builder_index
    )
    downgrade_phase_starts = {
        downgrade_source.rfind(phase_marker, 0, operation)
        for operation in (
            restore_legacy,
            validate_legacy,
            drop_composites,
            drop_parent_unique,
            drop_builder_index,
        )
    }
    assert -1 not in downgrade_phase_starts
    assert len(downgrade_phase_starts) == 5
    assert "NOT VALID" in downgrade_source[restore_legacy:validate_legacy]
    assert "DROP INDEX CONCURRENTLY" in downgrade_source
