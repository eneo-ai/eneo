from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest
from psycopg2.extras import Json

from alembic import command
from alembic.config import Config
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawl_outcome_legacy_fallback import (
    LegacyCrawlOutcomeInput,
    derive_outcome_from_legacy_columns,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_BACKFILL_REVISION = "202605121445"
BACKFILL_REVISION = "202605141700"


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
def backfill_db(test_settings):
    cfg = _alembic_cfg(test_settings.sync_database_url)

    try:
        command.downgrade(cfg, PRE_BACKFILL_REVISION)
    except Exception:
        command.upgrade(cfg, PRE_BACKFILL_REVISION)

    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True

    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        conn.close()


def _seed_crawl_prerequisites(conn) -> dict[str, UUID]:
    now = datetime.now(timezone.utc)
    tenant_id = uuid4()
    user_id = uuid4()
    embedding_model_id = uuid4()
    website_id = uuid4()

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state, created_at, updated_at)
            VALUES (%s, %s, 1000000, 'active', %s, %s)
            """,
            (str(tenant_id), f"crawler-backfill-{tenant_id.hex[:8]}", now, now),
        )
        cur.execute(
            """
            INSERT INTO users (
                id, email, state, used_tokens, tenant_id, created_at, updated_at
            )
            VALUES (%s, %s, 'active', 0, %s, %s, %s)
            """,
            (
                str(user_id),
                f"crawler-backfill-{user_id.hex[:8]}@example.com",
                str(tenant_id),
                now,
                now,
            ),
        )
        cur.execute(
            """
            INSERT INTO embedding_models (
                id, name, open_source, dimensions, max_input, max_batch_size,
                family, stability, hosting, created_at, updated_at
            )
            VALUES (
                %s, %s, false, 1536, 8192, 100,
                'openai', 'stable', 'cloud', %s, %s
            )
            """,
            (
                str(embedding_model_id),
                f"crawler-backfill-embedding-{embedding_model_id.hex[:8]}",
                now,
                now,
            ),
        )
        cur.execute(
            """
            INSERT INTO websites (
                id, name, url, download_files, crawl_type, update_interval, size,
                tenant_id, user_id, embedding_model_id, created_at, updated_at
            )
            VALUES (%s, %s, %s, true, 'CRAWL', 'never', 0, %s, %s, %s, %s, %s)
            """,
            (
                str(website_id),
                "Crawler outcome backfill",
                f"https://crawler-backfill-{website_id.hex[:8]}.example.com",
                str(tenant_id),
                str(user_id),
                str(embedding_model_id),
                now,
                now,
            ),
        )

    return {"tenant_id": tenant_id, "user_id": user_id, "website_id": website_id}


def _fixture_contract_cases() -> Iterator[tuple[str, Mapping[str, object]]]:
    fixture_path = Path(__file__).parents[2] / "fixtures" / "crawl_outcome_parity.json"
    cases = json.loads(fixture_path.read_text())

    for case in cases:
        input_data = case["input"]
        if "outcome_code" in input_data:
            continue
        yield case["name"], input_data


def _insert_crawl_run(
    conn,
    *,
    ids: Mapping[str, UUID],
    input_data: Mapping[str, object],
    finished_at: datetime | None,
    outcome_code: CrawlOutcomeCode | None = None,
    crawl_run_updated_at: datetime | None = None,
) -> UUID:
    now = datetime.now(timezone.utc)
    crawl_run_timestamp = crawl_run_updated_at or now
    run_id = uuid4()
    job_id = uuid4()
    processing_summary = input_data.get("processing_summary")

    pages_crawled = 0
    files_downloaded = 0
    if isinstance(processing_summary, dict):
        pages_crawled = int(processing_summary["pages_fetched"])
        files_downloaded = int(processing_summary["files_downloaded"])

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO jobs (
                id, user_id, task, status, result_location, name,
                finished_at, created_at, updated_at
            )
            VALUES (%s, %s, 'crawl', %s, %s, 'Crawler outcome backfill test', %s, %s, %s)
            """,
            (
                str(job_id),
                str(ids["user_id"]),
                input_data["status"],
                input_data.get("result_location"),
                finished_at,
                now,
                now,
            ),
        )
        cur.execute(
            """
            INSERT INTO crawl_runs (
                id, tenant_id, website_id, job_id, pages_crawled, files_downloaded,
                pages_failed, files_failed, pages_source_retained,
                pages_hash_retained, files_hash_retained, files_too_large_skipped,
                failure_summary, outcome_code, created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s
            )
            """,
            (
                str(run_id),
                str(ids["tenant_id"]),
                str(ids["website_id"]),
                str(job_id),
                pages_crawled,
                files_downloaded,
                input_data.get("pages_failed"),
                input_data.get("files_failed"),
                input_data.get("pages_source_retained"),
                input_data.get("pages_hash_retained"),
                input_data.get("files_hash_retained"),
                input_data.get("files_too_large_skipped"),
                Json(input_data.get("failure_summary"))
                if input_data.get("failure_summary") is not None
                else None,
                outcome_code.value if outcome_code is not None else None,
                now,
                crawl_run_timestamp,
            ),
        )

    return run_id


def _expected_legacy_outcome(input_data: Mapping[str, object]) -> CrawlOutcomeCode:
    fallback = derive_outcome_from_legacy_columns(
        _legacy_input_from_fixture(input_data)
    )
    assert fallback.outcome_code is not None
    return fallback.outcome_code


def _legacy_input_from_fixture(
    input_data: Mapping[str, object],
) -> LegacyCrawlOutcomeInput:
    processing_summary = input_data.get("processing_summary")
    indexed_count: int | None = None
    if isinstance(processing_summary, dict):
        indexed_count = int(processing_summary["pages_indexed"]) + int(
            processing_summary["files_indexed"]
        )

    return LegacyCrawlOutcomeInput(
        status=_optional_str(input_data.get("status")),
        result_location=_optional_str(input_data.get("result_location")),
        failure_summary=_optional_failure_summary(input_data.get("failure_summary")),
        pages_failed=_optional_int(input_data.get("pages_failed")),
        files_failed=_optional_int(input_data.get("files_failed")),
        pages_hash_retained=_optional_int(input_data.get("pages_hash_retained")),
        files_hash_retained=_optional_int(input_data.get("files_hash_retained")),
        files_too_large_skipped=_optional_int(
            input_data.get("files_too_large_skipped")
        ),
        indexed_count=indexed_count,
    )


def _optional_str(value: object) -> str | None:
    assert value is None or isinstance(value, str)
    return value


def _optional_int(value: object) -> int | None:
    assert value is None or isinstance(value, int)
    return value


def _optional_failure_summary(value: object) -> dict[str, int] | None:
    assert value is None or isinstance(value, dict)
    if value is None:
        return None

    return {str(key): int(count) for key, count in value.items()}


def _fetch_crawl_run_rows(
    conn, run_ids: list[UUID]
) -> dict[UUID, tuple[str | None, datetime]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, outcome_code, updated_at
            FROM crawl_runs
            WHERE id = ANY(%s::uuid[])
            """,
            ([str(run_id) for run_id in run_ids],),
        )
        return {UUID(str(row[0])): (row[1], row[2]) for row in cur.fetchall()}


class TestCrawlOutcomeBackfill:
    def test_backfill_matches_legacy_fallback_contract_and_preserves_unknowns(
        self, backfill_db
    ):
        conn = backfill_db["conn"]
        cfg = backfill_db["cfg"]
        ids = _seed_crawl_prerequisites(conn)
        finished_at = datetime.now(timezone.utc)
        historical_updated_at = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        expected_by_run_id: dict[UUID, CrawlOutcomeCode] = {}
        timestamp_preservation_run_id: UUID | None = None

        for name, input_data in _fixture_contract_cases():
            should_preserve_timestamp = name == "duplicate_skipped_legacy"
            run_id = _insert_crawl_run(
                conn,
                ids=ids,
                input_data=input_data,
                finished_at=finished_at,
                crawl_run_updated_at=historical_updated_at
                if should_preserve_timestamp
                else None,
            )
            if should_preserve_timestamp:
                timestamp_preservation_run_id = run_id
            expected_by_run_id[run_id] = _expected_legacy_outcome(input_data)

        unfinished_run_id = _insert_crawl_run(
            conn,
            ids=ids,
            input_data={
                "status": "failed",
                "result_location": "Crawl failed for https://example.com: no pages returned",
                "failure_summary": None,
                "pages_failed": None,
                "files_failed": None,
                "pages_source_retained": None,
            },
            finished_at=None,
        )
        already_typed_run_id = _insert_crawl_run(
            conn,
            ids=ids,
            input_data={
                "status": "failed",
                "result_location": "Crawl failed for https://example.com: no pages returned",
                "failure_summary": None,
                "pages_failed": None,
                "files_failed": None,
                "pages_source_retained": None,
            },
            finished_at=finished_at,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
        )
        non_terminal_run_id = _insert_crawl_run(
            conn,
            ids=ids,
            input_data={
                "status": "in progress",
                "result_location": "Crawl failed for https://example.com: no pages returned",
                "failure_summary": None,
                "pages_failed": None,
                "files_failed": None,
                "pages_source_retained": None,
            },
            finished_at=finished_at,
        )

        command.upgrade(cfg, BACKFILL_REVISION)

        observed = _fetch_crawl_run_rows(
            conn,
            [
                *expected_by_run_id.keys(),
                unfinished_run_id,
                already_typed_run_id,
                non_terminal_run_id,
            ],
        )

        for run_id, expected_code in expected_by_run_id.items():
            if expected_code == CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR:
                assert observed[run_id][0] is None
            else:
                assert observed[run_id][0] == expected_code.value

        assert observed[unfinished_run_id][0] is None
        assert (
            observed[already_typed_run_id][0]
            == CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT.value
        )
        assert observed[non_terminal_run_id][0] is None
        assert timestamp_preservation_run_id is not None
        assert observed[timestamp_preservation_run_id][1] == historical_updated_at
