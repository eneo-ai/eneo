from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import InternalError
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from eneo.database.tables.websites_table import CrawlAttempts, CrawlRuns

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_PREVIOUS_REVISION = "202608131000"
_LIFECYCLE_REVISION = "202608301030"
_CANCELLED_CLEANUP_REVISION = "202608311400"
_WEBSITE_BLOB_CURSOR_REVISION = "202608311430"
_WEBSITE_BLOB_CURSOR_INDEX = "ix_info_blobs_active_website_cursor"


@dataclass(frozen=True)
class LegacyRecords:
    runs: dict[str, tuple[UUID | None, UUID]]
    unrelated_job_id: UUID


@pytest.fixture(scope="session", autouse=True)
def override_settings_for_session() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def cleanup_database() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def seed_default_models() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def encryption_service() -> Generator[None, None, None]:
    yield


def _alembic_config(database_url: str) -> Config:
    backend_dir = Path(__file__).resolve().parents[3]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migration_database() -> Generator[tuple[str, Config], None, None]:
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="crawl_lifecycle",
        password="crawl_lifecycle_password",
        dbname="crawl_lifecycle",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        yield database_url, _alembic_config(database_url)


def _sync_url(database_url: str) -> str:
    return database_url.replace("+psycopg2", "")


def _current_revision(database_url: str) -> str:
    with (
        psycopg2.connect(_sync_url(database_url)) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT version_num FROM alembic_version")
        row = cursor.fetchone()
        assert row is not None
        return str(row[0])


def _inspected_names(database_url: str, table_name: str, kind: str) -> set[str]:
    engine = create_engine(database_url)
    try:
        table_inspector = inspect(engine)
        values = {
            "columns": table_inspector.get_columns,
            "indexes": table_inspector.get_indexes,
            "unique": table_inspector.get_unique_constraints,
            "checks": table_inspector.get_check_constraints,
        }[kind](table_name)
        return {str(value["name"]) for value in values}
    finally:
        engine.dispose()


def _seed_legacy_runs(database_url: str) -> LegacyRecords:
    runs: dict[str, tuple[UUID | None, UUID]] = {
        label: (None if label == "jobless" else uuid4(), uuid4())
        for label in (
            "empty",
            "partial",
            "invalid_counters",
            "unknown_counters",
            "failed",
            "failed_without_finished_at",
            "completed_without_finished_at",
            "queued",
            "in_progress",
            "jobless",
        )
    }
    unrelated_job_id = uuid4()
    historical_finished_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    with (
        psycopg2.connect(_sync_url(database_url)) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("ALTER TABLE jobs DISABLE TRIGGER ALL")
        cursor.execute("ALTER TABLE crawl_runs DISABLE TRIGGER ALL")
        try:
            for label, (job_id, run_id) in runs.items():
                tenant_id, user_id, website_id = _insert_crawl_owner(
                    cursor,
                    label=f"Legacy {label}",
                )
                if job_id is not None:
                    status = {
                        "failed": "failed",
                        "failed_without_finished_at": "failed",
                        "queued": "queued",
                        "in_progress": "in progress",
                    }.get(label, "complete")
                    finished_at = (
                        None
                        if label
                        in {
                            "completed_without_finished_at",
                            "failed_without_finished_at",
                            "queued",
                            "in_progress",
                        }
                        else historical_finished_at
                    )
                    cursor.execute(
                        """
                        INSERT INTO jobs (
                            id, user_id, task, status, name, result_location,
                            failure_code, finished_at
                        )
                        VALUES (%s, %s, 'crawl', %s, %s, %s, %s, %s)
                        """,
                        (
                            str(job_id),
                            str(user_id),
                            status,
                            f"Legacy {label} crawl",
                            (
                                "remote request failed"
                                if label in {"failed", "failed_without_finished_at"}
                                else "crawl did not finish"
                                if label in {"queued", "in_progress"}
                                else None
                            ),
                            (
                                "remote_unreachable"
                                if label in {"failed", "failed_without_finished_at"}
                                else None
                            ),
                            finished_at,
                        ),
                    )
                legacy_counts = {
                    "partial": (5, 4, 2, 1),
                    "invalid_counters": (1, 1, 2, 3),
                    "unknown_counters": (None, None, None, None),
                }.get(label, (0, 0, 0, 0))
                cursor.execute(
                    """
                    INSERT INTO crawl_runs (
                        id, tenant_id, website_id, job_id, pages_crawled,
                        files_downloaded, pages_failed, files_failed, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '2000-01-01 UTC')
                    """,
                    (
                        str(run_id),
                        str(tenant_id),
                        str(website_id),
                        str(job_id) if job_id is not None else None,
                        *legacy_counts,
                    ),
                )

            cursor.execute(
                """
                INSERT INTO jobs (id, user_id, task, status, name)
                VALUES (%s, %s, 'upload', 'queued', 'Unrelated upload')
                """,
                (str(unrelated_job_id), str(uuid4())),
            )
        finally:
            cursor.execute("ALTER TABLE crawl_runs ENABLE TRIGGER ALL")
            cursor.execute("ALTER TABLE jobs ENABLE TRIGGER ALL")
    return LegacyRecords(runs=runs, unrelated_job_id=unrelated_job_id)


def _lifecycle_rows(
    database_url: str,
) -> dict[UUID, tuple[str, str, str, datetime | None, str | None]]:
    with (
        psycopg2.connect(_sync_url(database_url)) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            SELECT id, phase, outcome, origin, finished_at, failure_code
            FROM crawl_runs
            ORDER BY id
            """
        )
        return {
            UUID(str(run_id)): (
                str(phase),
                str(outcome),
                str(origin),
                finished_at,
                str(failure_code) if failure_code is not None else None,
            )
            for run_id, phase, outcome, origin, finished_at, failure_code in cursor.fetchall()
        }


def _job_lifecycle(
    database_url: str, job_id: UUID
) -> tuple[str, str | None, datetime | None]:
    with (
        psycopg2.connect(_sync_url(database_url)) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT status, failure_code, finished_at FROM jobs WHERE id = %s",
            (str(job_id),),
        )
        row = cursor.fetchone()
        assert row is not None
        status, failure_code, finished_at = row
        return (
            str(status),
            str(failure_code) if failure_code is not None else None,
            finished_at,
        )


def _job_result_location(database_url: str, job_id: UUID) -> str | None:
    with (
        psycopg2.connect(_sync_url(database_url)) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT result_location FROM jobs WHERE id = %s",
            (str(job_id),),
        )
        row = cursor.fetchone()
        assert row is not None
        result_location = row[0]
        return str(result_location) if result_location is not None else None


def _crawl_counters_for_job(
    database_url: str,
    job_name: str,
) -> tuple[int | None, int | None, int | None, int | None]:
    with (
        psycopg2.connect(_sync_url(database_url)) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            SELECT cr.pages_crawled, cr.files_downloaded,
                   cr.pages_failed, cr.files_failed
            FROM crawl_runs AS cr
            JOIN jobs AS j ON j.id = cr.job_id
            WHERE j.name = %s
            """,
            (job_name,),
        )
        row = cursor.fetchone()
        assert row is not None
        pages_crawled, files_downloaded, pages_failed, files_failed = row
        return (
            int(pages_crawled) if pages_crawled is not None else None,
            int(files_downloaded) if files_downloaded is not None else None,
            int(pages_failed) if pages_failed is not None else None,
            int(files_failed) if files_failed is not None else None,
        )


def _insert_crawl_owner(
    cursor: psycopg2.extensions.cursor,
    *,
    label: str,
) -> tuple[UUID, UUID, UUID]:
    tenant_id = uuid4()
    user_id = uuid4()
    website_id = uuid4()
    cursor.execute("SELECT id FROM embedding_models ORDER BY id LIMIT 1")
    model_row = cursor.fetchone()
    assert model_row is not None
    embedding_model_id = UUID(str(model_row[0]))
    cursor.execute(
        """
        INSERT INTO tenants (id, name, quota_limit, state)
        VALUES (%s, %s, 1000000, 'active')
        """,
        (str(tenant_id), f"{label}-{tenant_id.hex[:8]}"),
    )
    cursor.execute(
        """
        INSERT INTO users (id, tenant_id, email, used_tokens, state)
        VALUES (%s, %s, %s, 0, 'active')
        """,
        (str(user_id), str(tenant_id), f"{user_id.hex}@example.test"),
    )
    cursor.execute(
        """
        INSERT INTO websites (
            id, name, url, download_files, crawl_type, update_interval, size,
            tenant_id, user_id, embedding_model_id
        )
        VALUES (%s, %s, %s, false, 'CRAWL', 'never', 0, %s, %s, %s)
        """,
        (
            str(website_id),
            label,
            f"https://{website_id}.example.test",
            str(tenant_id),
            str(user_id),
            str(embedding_model_id),
        ),
    )
    return tenant_id, user_id, website_id


def _assert_active_run_requires_current_attempt(database_url: str) -> None:
    job_id = uuid4()
    run_id = uuid4()
    connection = psycopg2.connect(_sync_url(database_url))
    try:
        with connection.cursor() as cursor:
            tenant_id, user_id, website_id = _insert_crawl_owner(
                cursor,
                label="Legacy late admission",
            )
            cursor.execute(
                """
                INSERT INTO jobs (id, user_id, task, status, name)
                VALUES (%s, %s, 'crawl', 'queued', 'Legacy late admission')
                """,
                (str(job_id), str(user_id)),
            )
            cursor.execute(
                """
                INSERT INTO crawl_runs (
                    id, tenant_id, website_id, job_id, pages_crawled,
                    files_downloaded, pages_failed, files_failed
                )
                VALUES (%s, %s, %s, %s, 0, 0, 0, 0)
                """,
                (str(run_id), str(tenant_id), str(website_id), str(job_id)),
            )

        with pytest.raises(
            psycopg2.errors.CheckViolation,
            match="active crawl run requires a current unfinished attempt",
        ):
            connection.commit()
    finally:
        connection.rollback()
        connection.close()


def _assert_active_run_with_current_attempt_commits(database_url: str) -> None:
    job_id = uuid4()
    run_id = uuid4()
    attempt_id = uuid4()
    with (
        psycopg2.connect(_sync_url(database_url)) as connection,
        connection.cursor() as cursor,
    ):
        tenant_id, user_id, website_id = _insert_crawl_owner(
            cursor,
            label="Current admission",
        )
        cursor.execute(
            """
            INSERT INTO jobs (id, user_id, task, status, name)
            VALUES (%s, %s, 'crawl', 'queued', 'Current admission')
            """,
            (str(job_id), str(user_id)),
        )
        cursor.execute(
            """
            INSERT INTO crawl_runs (
                id, tenant_id, website_id, job_id, pages_crawled,
                files_downloaded, pages_failed, files_failed,
                phase, origin, attempt_count
            )
            VALUES (%s, %s, %s, %s, 0, 0, 0, 0, 'pending_dispatch', 'manual', 1)
            """,
            (str(run_id), str(tenant_id), str(website_id), str(job_id)),
        )
        cursor.execute(
            """
            INSERT INTO crawl_attempts (
                id, crawl_run_id, attempt_number, dispatch_id, dispatch_payload
            )
            VALUES (%s, %s, 1, %s, '{}'::jsonb)
            """,
            (str(attempt_id), str(run_id), str(job_id)),
        )

    with (
        psycopg2.connect(_sync_url(database_url)) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM crawl_runs WHERE id = %s", (str(run_id),))
        cursor.execute("DELETE FROM jobs WHERE id = %s", (str(job_id),))
        cursor.execute("DELETE FROM websites WHERE id = %s", (str(website_id),))
        cursor.execute("DELETE FROM users WHERE id = %s", (str(user_id),))
        cursor.execute("DELETE FROM tenants WHERE id = %s", (str(tenant_id),))


def _upgrade_while_unrelated_job_is_locked(
    database_url: str,
    config: Config,
    unrelated_job_id: UUID,
) -> None:
    with psycopg2.connect(_sync_url(database_url)) as setting_connection:
        setting_connection.autocommit = True
        with setting_connection.cursor() as cursor:
            cursor.execute("ALTER ROLE CURRENT_USER SET lock_timeout = '2s'")

    lock_connection = psycopg2.connect(_sync_url(database_url))
    try:
        with lock_connection.cursor() as cursor:
            cursor.execute(
                "UPDATE jobs SET name = name WHERE id = %s",
                (str(unrelated_job_id),),
            )
        command.upgrade(config, _LIFECYCLE_REVISION)
    finally:
        lock_connection.rollback()
        lock_connection.close()


def test_crawl_lifecycle_migration_preserves_and_terminalizes_legacy_history(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database
    command.upgrade(config, _PREVIOUS_REVISION)
    records = _seed_legacy_runs(database_url)

    # A write lock on an unrelated upload job must not block crawler migration.
    migration_started_at = datetime.now(timezone.utc)
    _upgrade_while_unrelated_job_is_locked(
        database_url,
        config,
        records.unrelated_job_id,
    )
    assert _current_revision(database_url) == _LIFECYCLE_REVISION

    rows = _lifecycle_rows(database_url)
    empty = rows[records.runs["empty"][1]]
    partial = rows[records.runs["partial"][1]]
    failed = rows[records.runs["failed"][1]]
    failed_without_finished_at = rows[records.runs["failed_without_finished_at"][1]]
    missing_finished_at = rows[records.runs["completed_without_finished_at"][1]]
    queued = rows[records.runs["queued"][1]]
    in_progress = rows[records.runs["in_progress"][1]]
    jobless = rows[records.runs["jobless"][1]]

    assert empty[:3] == ("terminal", "empty", "legacy")
    assert partial[:3] == ("terminal", "partial", "legacy")
    assert partial[4] == "processing_failed"
    assert _crawl_counters_for_job(database_url, "Legacy partial crawl") == (
        3,
        3,
        2,
        1,
    )
    assert _crawl_counters_for_job(database_url, "Legacy invalid_counters crawl") == (
        0,
        0,
        2,
        3,
    )
    assert _crawl_counters_for_job(database_url, "Legacy unknown_counters crawl") == (
        None,
        None,
        None,
        None,
    )
    assert failed[:3] == ("terminal", "failed", "legacy")
    assert failed[4] == "processing_failed"
    assert failed_without_finished_at == (
        "terminal",
        "failed",
        "legacy",
        None,
        "processing_failed",
    )
    assert missing_finished_at == ("terminal", "empty", "legacy", None, None)
    assert queued[:3] == ("terminal", "interrupted", "legacy")
    assert queued[3] is not None
    assert queued[4] == "worker_interrupted"
    assert in_progress[:3] == ("terminal", "interrupted", "legacy")
    assert in_progress[3] is not None
    assert in_progress[4] == "worker_interrupted"
    assert jobless[:3] == ("terminal", "interrupted", "legacy")
    assert jobless[3] is not None
    assert jobless[3] >= migration_started_at
    assert jobless[4] == "dispatch_failed"

    for label, migrated in (("queued", queued), ("in_progress", in_progress)):
        job_id = records.runs[label][0]
        assert job_id is not None
        assert _job_lifecycle(database_url, job_id) == (
            "failed",
            "worker_interrupted",
            migrated[3],
        )

    assert _inspected_names(database_url, CrawlRuns.__tablename__, "columns") == {
        column.name for column in CrawlRuns.__table__.columns
    }
    assert _inspected_names(database_url, CrawlAttempts.__tablename__, "columns") == {
        column.name for column in CrawlAttempts.__table__.columns
    }
    assert {
        "uq_crawl_runs_active_website",
        "ix_crawl_runs_pending_dispatch",
        "ix_crawl_runs_website_created",
        "ix_crawl_runs_tenant_phase",
    } <= _inspected_names(database_url, CrawlRuns.__tablename__, "indexes")
    assert {
        "uq_crawl_attempts_active_run",
        "ix_crawl_attempts_dispatch_candidates",
        "ix_crawl_attempts_redelivery_candidates",
        "ix_crawl_attempts_expired_lease",
        "ix_crawl_attempts_pending_transport_cleanup",
    } <= _inspected_names(database_url, CrawlAttempts.__tablename__, "indexes")
    assert "uq_crawl_runs_job_id" in _inspected_names(
        database_url, CrawlRuns.__tablename__, "unique"
    )
    assert {
        "ck_crawl_runs_terminal_outcome",
        "ck_crawl_runs_nonterminal_unfinished",
        "ck_crawl_runs_terminal_finished_at",
        "ck_crawl_runs_outcome_failure",
    } <= _inspected_names(database_url, CrawlRuns.__tablename__, "checks")
    assert {
        "ck_crawl_attempts_lease_pair",
        "ck_crawl_attempts_finished_without_lease",
        "ck_crawl_attempts_dispatch_order",
        "ck_crawl_attempts_transport_cleanup",
    } <= _inspected_names(database_url, CrawlAttempts.__tablename__, "checks")
    _assert_active_run_requires_current_attempt(database_url)
    _assert_active_run_with_current_attempt_commits(database_url)


def test_crawl_lifecycle_downgrade_refuses_lossy_state_then_round_trips(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database
    active_run_id = uuid4()
    with (
        psycopg2.connect(_sync_url(database_url)) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("ALTER TABLE crawl_runs DISABLE TRIGGER ALL")
        try:
            cursor.execute(
                """
                INSERT INTO crawl_runs (
                    id, tenant_id, website_id, phase, origin, attempt_count
                )
                VALUES (%s, %s, %s, 'pending_dispatch', 'manual', 0)
                """,
                (str(active_run_id), str(uuid4()), str(uuid4())),
            )
        finally:
            cursor.execute("ALTER TABLE crawl_runs ENABLE TRIGGER ALL")

    with pytest.raises(
        InternalError,
        match="crawler lifecycle downgrade requires drained crawl runs",
    ):
        command.downgrade(config, _PREVIOUS_REVISION)
    assert _current_revision(database_url) == _LIFECYCLE_REVISION

    with (
        psycopg2.connect(_sync_url(database_url)) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM crawl_runs WHERE id = %s", (str(active_run_id),))

    with pytest.raises(
        InternalError,
        match="crawler lifecycle downgrade cannot project runs without jobs",
    ):
        command.downgrade(config, _PREVIOUS_REVISION)
    assert _current_revision(database_url) == _LIFECYCLE_REVISION

    with (
        psycopg2.connect(_sync_url(database_url)) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            SELECT id, job_id
            FROM crawl_runs
            WHERE outcome = 'failed'
              AND job_id IS NOT NULL
            ORDER BY id
            LIMIT 1
            """
        )
        failed_row = cursor.fetchone()
        assert failed_row is not None
        failed_run_id = UUID(str(failed_row[0]))
        failed_job_id = UUID(str(failed_row[1]))
        cursor.execute(
            """
            UPDATE crawl_runs
            SET result_location = NULL,
                failure_code = 'remote_blocked',
                failure_detail = 'Post-upgrade crawl failure'
            WHERE id = %s
            """,
            (str(failed_run_id),),
        )
        cursor.execute("DELETE FROM crawl_runs WHERE job_id IS NULL")

    command.downgrade(config, _PREVIOUS_REVISION)
    assert _current_revision(database_url) == _PREVIOUS_REVISION
    assert _crawl_counters_for_job(database_url, "Legacy partial crawl") == (
        5,
        4,
        2,
        1,
    )
    assert _crawl_counters_for_job(database_url, "Legacy unknown_counters crawl") == (
        None,
        None,
        None,
        None,
    )
    assert _crawl_counters_for_job(database_url, "Legacy invalid_counters crawl") == (
        2,
        3,
        2,
        3,
    )
    assert _job_result_location(database_url, failed_job_id) == (
        "Post-upgrade crawl failure"
    )
    assert "phase" not in _inspected_names(database_url, "crawl_runs", "columns")
    engine = create_engine(database_url)
    try:
        assert not inspect(engine).has_table("crawl_attempts")
    finally:
        engine.dispose()


def test_cancelled_cleanup_migration_refuses_to_lose_pending_or_acknowledged_work(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database
    command.upgrade(config, _CANCELLED_CLEANUP_REVISION)

    with (
        psycopg2.connect(_sync_url(database_url)) as connection,
        connection.cursor() as cursor,
    ):
        run_id = uuid4()
        attempt_id = uuid4()
        cursor.execute("ALTER TABLE crawl_runs DISABLE TRIGGER ALL")
        try:
            cursor.execute(
                """
                INSERT INTO crawl_runs (
                    id, tenant_id, website_id, phase, outcome, origin,
                    finished_at, failure_code, cancel_requested_at, attempt_count
                )
                VALUES (
                    %s, %s, %s, 'terminal', 'cancelled', 'manual',
                    now(), 'cancelled', now(), 1
                )
                """,
                (str(run_id), str(uuid4()), str(uuid4())),
            )
        finally:
            cursor.execute("ALTER TABLE crawl_runs ENABLE TRIGGER ALL")
        cursor.execute(
            """
            INSERT INTO crawl_attempts (
                id, crawl_run_id, attempt_number, dispatch_id,
                dispatch_payload, finished_at, failure_code
            )
            VALUES (%s, %s, %s, %s, '{}'::jsonb, now(), 'cancelled')
            """,
            (
                str(attempt_id),
                str(run_id),
                1,
                str(uuid4()),
            ),
        )

    with pytest.raises(
        InternalError,
        match="cannot downgrade cancelled crawl cleanup",
    ):
        command.downgrade(config, _LIFECYCLE_REVISION)
    assert _current_revision(database_url) == _CANCELLED_CLEANUP_REVISION

    with (
        psycopg2.connect(_sync_url(database_url)) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            UPDATE crawl_attempts
            SET transport_cleaned_at = now()
            WHERE id = %s
            """,
            (str(attempt_id),),
        )

    with pytest.raises(
        InternalError,
        match="cannot downgrade cancelled crawl cleanup",
    ):
        command.downgrade(config, _LIFECYCLE_REVISION)
    assert _current_revision(database_url) == _CANCELLED_CLEANUP_REVISION

    with (
        psycopg2.connect(_sync_url(database_url)) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            UPDATE crawl_attempts
            SET failure_code = 'lease_expired'
            WHERE id = %s
            """,
            (str(attempt_id),),
        )

    command.downgrade(config, _LIFECYCLE_REVISION)
    assert _current_revision(database_url) == _LIFECYCLE_REVISION
    command.upgrade(config, _CANCELLED_CLEANUP_REVISION)


def test_active_website_blob_cursor_index_round_trips(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database
    command.upgrade(config, _WEBSITE_BLOB_CURSOR_REVISION)

    assert _current_revision(database_url) == _WEBSITE_BLOB_CURSOR_REVISION
    assert _WEBSITE_BLOB_CURSOR_INDEX in _inspected_names(
        database_url,
        "info_blobs",
        "indexes",
    )

    command.downgrade(config, _CANCELLED_CLEANUP_REVISION)
    assert _WEBSITE_BLOB_CURSOR_INDEX not in _inspected_names(
        database_url,
        "info_blobs",
        "indexes",
    )

    command.upgrade(config, _WEBSITE_BLOB_CURSOR_REVISION)
    connection = psycopg2.connect(_sync_url(database_url))
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                f"DROP INDEX CONCURRENTLY IF EXISTS {_WEBSITE_BLOB_CURSOR_INDEX}"
            )
    finally:
        connection.close()

    command.downgrade(config, _CANCELLED_CLEANUP_REVISION)
    assert _current_revision(database_url) == _CANCELLED_CLEANUP_REVISION
    command.upgrade(config, _WEBSITE_BLOB_CURSOR_REVISION)
