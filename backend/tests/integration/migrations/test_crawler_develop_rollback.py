"""Rehearse the crawler branch rollback without removing develop migrations."""

from collections.abc import Generator
from dataclasses import dataclass
from uuid import UUID, uuid4

import psycopg2
import pytest
from sqlalchemy import MetaData, Table, create_engine, null
from sqlalchemy.exc import InternalError
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from tests.integration.migrations.test_crawl_lifecycle_round_trip import (
    _alembic_config,
    _insert_crawl_owner,
    _sync_url,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]
_DEVELOP_HEAD = "202609071000"
_CRAWLER_HEAD = "202609091830"
# The qualifier keeps the other side of both merge revisions at develop's head.
_CRAWLER_ROLLBACK = "202608311430@202608121500"


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


@dataclass
class RollbackDatabase:
    url: str
    config: Config
    postgres: PostgresContainer

    def schema(self) -> str:
        result = self.postgres.get_wrapped_container().exec_run(
            [
                "pg_dump",
                "--schema-only",
                "--no-owner",
                "--no-privileges",
                "-U",
                "crawler_rollback",
                "crawler_rollback",
            ]
        )
        assert result.exit_code == 0, result.output.decode()
        # New pg_dump versions put a random psql restriction key around the dump.
        return "\n".join(
            line
            for line in result.output.decode().splitlines()
            if not line.startswith(("\\restrict ", "\\unrestrict "))
        )

    def revisions(self) -> set[str]:
        with psycopg2.connect(self.url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            return {row[0] for row in cursor.fetchall()}


@pytest.fixture
def rollback_database() -> Generator[RollbackDatabase, None, None]:
    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="crawler_rollback",
        password="crawler_rollback_password",
        dbname="crawler_rollback",
    ) as postgres:
        url = _sync_url(postgres.get_connection_url())
        yield RollbackDatabase(url, _alembic_config(url), postgres)


def test_legacy_failure_summaries_survive_upgrade_and_rollback(
    rollback_database: RollbackDatabase,
) -> None:
    database = rollback_database
    command.upgrade(database.config, _DEVELOP_HEAD)
    with psycopg2.connect(database.url) as connection, connection.cursor() as cursor:
        tenant_id, _, website_id = _insert_crawl_owner(cursor, label="Legacy summaries")

    engine = create_engine(database.url)
    try:
        legacy_runs = Table("crawl_runs", MetaData(), autoload_with=engine)
        with engine.begin() as connection:
            # JSONB's default binding stores Python None as JSON null.
            for summary in (None, null(), {"processing_failed": 2}):
                connection.execute(
                    legacy_runs.insert().values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        website_id=website_id,
                        failure_summary=summary,
                    )
                )
    finally:
        engine.dispose()

    def summaries() -> list[tuple[str, str | None, bool]]:
        with (
            psycopg2.connect(database.url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "SELECT id::text, failure_summary::text, failure_summary IS NULL "
                "FROM crawl_runs ORDER BY id"
            )
            return cursor.fetchall()

    original = summaries()
    assert {(summary, is_null) for _, summary, is_null in original} == {
        ("null", False),
        (None, True),
        ('{"processing_failed": 2}', False),
    }
    command.upgrade(database.config, _CRAWLER_HEAD)
    assert summaries() == original
    command.downgrade(database.config, _CRAWLER_ROLLBACK)
    assert summaries() == original
    command.upgrade(database.config, _CRAWLER_HEAD)
    assert summaries() == original


def test_quota_failures_remain_readable_after_downgrade(
    rollback_database: RollbackDatabase,
) -> None:
    database = rollback_database
    command.upgrade(database.config, _CRAWLER_HEAD)
    with psycopg2.connect(database.url) as connection, connection.cursor() as cursor:
        tenant_id, user_id, website_id = _insert_crawl_owner(
            cursor, label="Quota history"
        )
        for code in ("tenant_quota_exceeded", "user_quota_exceeded"):
            run_id, job_id = uuid4(), uuid4()
            cursor.execute(
                "INSERT INTO jobs (id, user_id, task, status, failure_code) "
                "VALUES (%s, %s, 'crawl', 'failed', %s)",
                (str(job_id), str(user_id), code),
            )
            cursor.execute(
                "INSERT INTO crawl_runs (id, tenant_id, website_id, job_id, phase, "
                "origin, outcome, failure_code, failure_detail, failure_summary, "
                "finished_at, attempt_count) VALUES (%s, %s, %s, %s, 'terminal', "
                "'manual', 'failed', %s, 'Storage quota is full', %s::jsonb, now(), 1)",
                (
                    str(run_id),
                    str(tenant_id),
                    str(website_id),
                    str(job_id),
                    code,
                    '{"' + code.upper() + '": 2}',
                ),
            )
            cursor.execute(
                "INSERT INTO crawl_attempts (crawl_run_id, attempt_number, dispatch_id, "
                "dispatch_payload, finished_at, failure_code) "
                "VALUES (%s, 1, %s, '{}'::jsonb, now(), %s)",
                (str(run_id), str(job_id), code),
            )

    command.downgrade(database.config, "202609071200")
    with psycopg2.connect(database.url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT cr.failure_code, ca.failure_code, j.failure_code, "
            "cr.failure_detail, cr.failure_summary FROM crawl_runs cr "
            "JOIN crawl_attempts ca ON ca.crawl_run_id = cr.id "
            "JOIN jobs j ON j.id = cr.job_id"
        )
        rows = cursor.fetchall()
        assert len(rows) == 2
        for run_code, attempt_code, job_code, detail, summary in rows:
            assert (run_code, attempt_code, job_code) == (
                "processing_failed",
                "processing_failed",
                "quota_exceeded",
            )
            assert detail == "Storage quota is full"
            assert summary in ({"TENANT_QUOTA_EXCEEDED": 2}, {"USER_QUOTA_EXCEEDED": 2})
    command.upgrade(database.config, _CRAWLER_HEAD)
    assert database.revisions() == {_CRAWLER_HEAD}


def test_indexing_timestamps_use_recorded_history_and_failure_details_block_lossy_downgrade(
    rollback_database: RollbackDatabase,
) -> None:
    database = rollback_database
    command.upgrade(database.config, "202609091230")
    run_id = uuid4()
    with psycopg2.connect(database.url) as connection, connection.cursor() as cursor:
        tenant_id, _, website_id = _insert_crawl_owner(
            cursor, label="Indexing timestamp"
        )
        _, _, unknown_website_id = _insert_crawl_owner(
            cursor, label="Unknown timestamp"
        )
        for outcome, finished_at in (
            ("partial", "2026-09-08 10:00 UTC"),
            ("failed", "2026-09-09 10:00 UTC"),
        ):
            cursor.execute(
                "INSERT INTO crawl_runs (id, website_id, tenant_id, phase, outcome, "
                "origin, finished_at, failure_code) VALUES (%s, %s, %s, 'terminal', %s, "
                "'manual', %s, 'processing_failed')",
                (
                    str(run_id if outcome == "partial" else uuid4()),
                    str(website_id),
                    str(tenant_id),
                    outcome,
                    finished_at,
                ),
            )
    command.upgrade(database.config, _CRAWLER_HEAD)
    with psycopg2.connect(database.url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT last_indexed_at = '2026-09-08 10:00 UTC'::timestamptz FROM websites WHERE id = %s",
            (str(website_id),),
        )
        assert cursor.fetchone() == (True,)
        cursor.execute(
            "SELECT last_indexed_at FROM websites WHERE id = %s",
            (str(unknown_website_id),),
        )
        assert cursor.fetchone() == (None,)
        cursor.execute(
            "SELECT failure_details_available FROM crawl_runs WHERE id = %s",
            (str(run_id),),
        )
        assert cursor.fetchone() == (False,)
        cursor.execute(
            "INSERT INTO crawl_run_failures (crawl_run_id, url, reason, kind) VALUES (%s, 'https://example.test/missing', 'http_404', 'page')",
            (str(run_id),),
        )
    schema = database.schema()
    with pytest.raises(InternalError, match="recorded crawl failure addresses exist"):
        command.downgrade(database.config, "202609091230")
    assert database.revisions() == {_CRAWLER_HEAD}
    assert database.schema() == schema
    with psycopg2.connect(database.url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM crawl_run_failures")
        assert cursor.fetchone() == (1,)
        cursor.execute("DELETE FROM crawl_run_failures")
    command.downgrade(database.config, "202609091230")
    command.upgrade(database.config, _CRAWLER_HEAD)
    assert database.revisions() == {_CRAWLER_HEAD}


def test_malformed_failure_summaries_block_upgrade_without_changing_legacy_data(
    rollback_database: RollbackDatabase,
) -> None:
    database = rollback_database
    command.upgrade(database.config, _DEVELOP_HEAD)
    run_id = uuid4()
    with psycopg2.connect(database.url) as connection, connection.cursor() as cursor:
        tenant_id, _, website_id = _insert_crawl_owner(
            cursor, label="Malformed summary"
        )
        cursor.execute(
            "INSERT INTO crawl_runs (id, tenant_id, website_id) VALUES (%s, %s, %s)",
            (str(run_id), str(tenant_id), str(website_id)),
        )
    schema = database.schema()

    for malformed in ("[]", '"failure"', "true", "2"):
        with (
            psycopg2.connect(database.url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE crawl_runs SET failure_summary = %s::jsonb WHERE id = %s",
                (malformed, str(run_id)),
            )

        with pytest.raises(InternalError, match="malformed failure_summary"):
            command.upgrade(database.config, _CRAWLER_HEAD)

        assert database.revisions() == {_DEVELOP_HEAD}
        assert database.schema() == schema
        with (
            psycopg2.connect(database.url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "SELECT failure_summary::text FROM crawl_runs WHERE id = %s",
                (str(run_id),),
            )
            assert cursor.fetchone() == (malformed,)


@pytest.mark.parametrize("blocker", ["active_run", "transport_cleanup"])
def test_rollback_checks_live_work_before_changing_the_schema(
    rollback_database: RollbackDatabase,
    blocker: str,
) -> None:
    database = rollback_database
    command.upgrade(database.config, _CRAWLER_HEAD)
    with psycopg2.connect(database.url) as connection, connection.cursor() as cursor:
        tenant_id, _, website_id = _insert_crawl_owner(cursor, label="Rollback guard")
        run_id = uuid4()
        if blocker == "active_run":
            cursor.execute(
                "INSERT INTO crawl_runs (id, tenant_id, website_id, phase, origin, attempt_count) "
                "VALUES (%s, %s, %s, 'pending_dispatch', 'manual', 1)",
                (str(run_id), str(tenant_id), str(website_id)),
            )
            cursor.execute(
                "INSERT INTO crawl_attempts (crawl_run_id, attempt_number, dispatch_id, "
                "dispatch_payload) VALUES (%s, 1, %s, '{}'::jsonb)",
                (str(run_id), str(uuid4())),
            )
        else:
            cursor.execute(
                "INSERT INTO crawl_runs (id, tenant_id, website_id, phase, origin, "
                "outcome, failure_code, finished_at, attempt_count) "
                "VALUES (%s, %s, %s, 'terminal', 'manual', 'interrupted', "
                "'lease_expired', now(), 1)",
                (str(run_id), str(tenant_id), str(website_id)),
            )
            cursor.execute(
                "INSERT INTO crawl_attempts (crawl_run_id, attempt_number, dispatch_id, "
                "dispatch_payload, finished_at, failure_code) "
                "VALUES (%s, 1, %s, '{}'::jsonb, now(), 'lease_expired')",
                (str(run_id), str(uuid4())),
            )
    schema = database.schema()

    with pytest.raises(InternalError, match="downgrade requires"):
        command.downgrade(database.config, _CRAWLER_ROLLBACK)

    assert database.revisions() == {_CRAWLER_HEAD}
    assert database.schema() == schema


def test_used_crawler_database_returns_to_develop_and_can_upgrade_again(
    rollback_database: RollbackDatabase,
) -> None:
    database = rollback_database
    command.upgrade(database.config, _DEVELOP_HEAD)
    develop_schema = database.schema()
    legacy_run, legacy_job, source_id, question_id = (uuid4() for _ in range(4))
    active_blob, cited_blob = uuid4(), uuid4()
    with psycopg2.connect(database.url) as connection, connection.cursor() as cursor:
        tenant_id, user_id, website_id = _insert_crawl_owner(
            cursor, label="Rollback data"
        )
        cursor.execute(
            "INSERT INTO jobs (id, user_id, task, status, name, finished_at) "
            "VALUES (%s, %s, 'crawl', 'complete', 'Existing crawl', '2026-09-01 UTC')",
            (str(legacy_job), str(user_id)),
        )
        cursor.execute(
            "INSERT INTO crawl_runs (id, tenant_id, website_id, job_id, "
            "pages_crawled, pages_failed, files_downloaded, files_failed) "
            "VALUES (%s, %s, %s, %s, 7, 2, 3, 1)",
            (str(legacy_run), str(tenant_id), str(website_id), str(legacy_job)),
        )
        for blob_id, state in ((active_blob, "active"), (cited_blob, "superseded")):
            cursor.execute(
                "INSERT INTO info_blobs (id, source_id, version_state, website_id, "
                "tenant_id, user_id, title, url, text, size) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'Guide.pdf', "
                "'https://EXAMPLE.test:443/guide.pdf#intro', 'Preserved knowledge', 19)",
                (
                    str(blob_id),
                    str(source_id),
                    state,
                    str(website_id),
                    str(tenant_id),
                    str(user_id),
                ),
            )
        cursor.execute(
            "INSERT INTO questions (id, tenant_id, question, answer, "
            "num_tokens_question, num_tokens_answer) VALUES (%s, %s, 'Q', 'A', 1, 1)",
            (str(question_id), str(tenant_id)),
        )
        cursor.execute(
            "INSERT INTO info_blob_references (question_id, info_blob_id) VALUES (%s, %s)",
            (str(question_id), str(cited_blob)),
        )
    command.upgrade(database.config, _CRAWLER_HEAD)

    runs: dict[str, UUID] = {}
    with psycopg2.connect(database.url) as connection, connection.cursor() as cursor:
        for outcome in (
            "partial",
            "cancelled_before_dispatch",
            "cancelled_after_dispatch",
        ):
            run_id = uuid4()
            job_id = None if outcome == "cancelled_before_dispatch" else uuid4()
            runs[outcome] = run_id
            if job_id:
                cursor.execute(
                    "INSERT INTO jobs (id, user_id, task, status, name) "
                    "VALUES (%s, %s, 'crawl', 'complete', 'Crawler branch run')",
                    (str(job_id), str(user_id)),
                )
            cursor.execute(
                "INSERT INTO crawl_runs (id, tenant_id, website_id, job_id, "
                "phase, outcome, origin, failure_code, failure_detail, "
                "created_at, finished_at, pages_crawled, pages_failed, "
                "files_downloaded, files_failed, attempt_count) "
                "VALUES (%s, %s, %s, %s, 'terminal', %s, 'manual', %s, %s, "
                "'2026-09-08 10:00 UTC', '2026-09-08 10:01 UTC', 2, 1, 1, 1, %s)",
                (
                    str(run_id),
                    str(tenant_id),
                    str(website_id),
                    str(job_id) if job_id else None,
                    "partial" if outcome == "partial" else "cancelled",
                    "timed_out" if outcome == "partial" else "cancelled",
                    outcome,
                    1 if job_id else 0,
                ),
            )
            if job_id:
                cursor.execute(
                    "INSERT INTO crawl_attempts (crawl_run_id, attempt_number, dispatch_id, "
                    "dispatch_payload, finished_at, failure_code, transport_cleaned_at) "
                    "VALUES (%s, 1, %s, '{}'::jsonb, '2026-09-08 10:01 UTC', %s, %s)",
                    (
                        str(run_id),
                        str(job_id),
                        "cancelled" if outcome == "cancelled_after_dispatch" else None,
                        "2026-09-08 10:02 UTC"
                        if outcome == "cancelled_after_dispatch"
                        else None,
                    ),
                )
        new_blob = uuid4()
        cursor.execute(
            "INSERT INTO info_blobs (id, source_id, version_state, website_id, tenant_id, user_id, title, "
            "url, website_source_url, text, size) "
            "VALUES (%s, %s, 'active', %s, %s, %s, 'Downloaded report.pdf', "
            "'https://example.test/download?id=1', 'https://example.test/download?id=1', "
            "'New knowledge', 13)",
            (
                str(new_blob),
                str(uuid4()),
                str(website_id),
                str(tenant_id),
                str(user_id),
            ),
        )
        cursor.execute(
            "SELECT id, source_id, version_state, title, url, text, size "
            "FROM info_blobs ORDER BY id"
        )
        expected_blobs = cursor.fetchall()

    command.downgrade(database.config, _CRAWLER_ROLLBACK)

    assert database.revisions() == {_DEVELOP_HEAD}
    assert database.schema() == develop_schema
    with psycopg2.connect(database.url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, source_id, version_state, title, url, text, size "
            "FROM info_blobs ORDER BY id"
        )
        assert cursor.fetchall() == expected_blobs
        cursor.execute("SELECT question_id, info_blob_id FROM info_blob_references")
        assert cursor.fetchall() == [(str(question_id), str(cited_blob))]
        cursor.execute(
            "SELECT pages_crawled, pages_failed, files_downloaded, files_failed "
            "FROM crawl_runs WHERE id = %s",
            (str(legacy_run),),
        )
        assert cursor.fetchone() == (7, 2, 3, 1)
        for outcome, run_id in runs.items():
            cursor.execute(
                "SELECT j.user_id, j.task, j.status, j.failure_code, j.result_location, "
                "cr.pages_crawled, cr.pages_failed, cr.files_downloaded, cr.files_failed, "
                "j.finished_at = '2026-09-08 10:01 UTC'::timestamptz "
                "FROM crawl_runs cr JOIN jobs j ON j.id = cr.job_id WHERE cr.id = %s",
                (str(run_id),),
            )
            assert cursor.fetchone() == (
                str(user_id),
                "crawl",
                "complete" if outcome == "partial" else "failed",
                "timed_out" if outcome == "partial" else "cancelled",
                None if outcome == "partial" else outcome,
                3,
                1,
                2,
                1,
                True,
            )

    command.upgrade(database.config, _CRAWLER_HEAD)
    assert database.revisions() == {_CRAWLER_HEAD}
    with psycopg2.connect(database.url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT website_source_url FROM info_blobs WHERE id = %s", (str(new_blob),)
        )
        assert cursor.fetchone() == ("https://example.test/download?id=1",)


@pytest.mark.parametrize(
    ("previous_revision", "index_name", "columns"),
    [
        ("202609091300", "ix_crawl_runs_tenant_finished", "tenant_id, finished_at, id"),
        (
            "202609091600",
            "ix_crawl_runs_tenant_active_created",
            "tenant_id, created_at, id",
        ),
    ],
)
def test_tenant_crawl_overview_index_round_trip(
    rollback_database: RollbackDatabase,
    previous_revision: str,
    index_name: str,
    columns: str,
) -> None:
    database = rollback_database
    command.upgrade(database.config, previous_revision)
    run_id = uuid4()
    with psycopg2.connect(database.url) as connection, connection.cursor() as cursor:
        tenant_id, _, website_id = _insert_crawl_owner(
            cursor, label="Tenant history index"
        )
        cursor.execute(
            "INSERT INTO crawl_runs (id, website_id, tenant_id, phase, outcome, origin, finished_at) "
            "VALUES (%s, %s, %s, 'terminal', 'succeeded', 'manual', now())",
            (run_id, website_id, tenant_id),
        )
    command.upgrade(database.config, _CRAWLER_HEAD)
    with psycopg2.connect(database.url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = %s", (index_name,)
        )
        row = cursor.fetchone()
        assert row is not None
        definition = row[0]
        assert f"({columns})" in definition
        assert "terminal" in definition
        cursor.execute(
            "SELECT indisvalid FROM pg_index WHERE indexrelid = %s::regclass",
            (index_name,),
        )
        assert cursor.fetchone() == (True,)
    command.downgrade(database.config, previous_revision)
    with psycopg2.connect(database.url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", (index_name,))
        assert cursor.fetchone() == (None,)
        cursor.execute("SELECT outcome FROM crawl_runs WHERE id = %s", (run_id,))
        assert cursor.fetchone() == ("succeeded",)
    command.upgrade(database.config, _CRAWLER_HEAD)
