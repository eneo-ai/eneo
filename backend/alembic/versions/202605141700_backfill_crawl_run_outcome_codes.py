"""backfill_crawl_run_outcome_codes

Revision ID: 202605141700
Revises: 202605121445
Create Date: 2026-05-14 17:00:00.000000

This intentionally leaves genuine UNKNOWN_CRAWL_ERROR rows with NULL
outcome_code so the historical fallback metric keeps measuring unexplained
legacy rows. Downgrade is a no-op because backfilled values cannot be
distinguished from later runtime-written values. The backfill preserves
historical updated_at values so crawl history does not look freshly edited.
Batching bounds individual UPDATE statements; Alembic still runs the migration
transactionally.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "202605141700"
down_revision: Union[str, None] = "202605121445"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SINGLE_STATEMENT_THRESHOLD = 100_000
BATCH_SIZE = 5_000

_DETAIL = "lower(coalesce(j.result_location, ''))"
_TRIMMED_DETAIL = "lower(btrim(coalesce(j.result_location, '')))"
_NONEMPTY_FAILURE_SUMMARY = (
    "cr.failure_summary IS NOT NULL "
    "AND jsonb_typeof(cr.failure_summary) = 'object' "
    "AND cr.failure_summary <> '{}'::jsonb"
)
_INDEXED_COUNT = (
    "GREATEST("
    "COALESCE(cr.pages_crawled, 0) "
    "- COALESCE(cr.pages_hash_retained, 0) "
    "- COALESCE(cr.pages_failed, 0), "
    "0"
    ") "
    "+ GREATEST("
    "COALESCE(cr.files_downloaded, 0) "
    "- COALESCE(cr.files_hash_retained, 0) "
    "- COALESCE(cr.files_failed, 0), "
    "0"
    ")"
)
_AFFECTED_COUNT = "COALESCE(cr.pages_failed, 0) + COALESCE(cr.files_failed, 0)"
_HASH_RETAINED_COUNT = (
    "COALESCE(cr.pages_hash_retained, 0) + COALESCE(cr.files_hash_retained, 0)"
)
_DERIVABLE_FILTER = f"""
    cr.outcome_code IS NULL
    AND cr.job_id IS NOT NULL
    AND j.finished_at IS NOT NULL
    AND j.status IN ('failed', 'not found', 'complete')
    AND (
        (j.status = 'failed' AND {_TRIMMED_DETAIL} LIKE 'skipped duplicate crawl%%')
        OR ({_NONEMPTY_FAILURE_SUMMARY})
        OR (
            j.status IN ('failed', 'not found')
            AND {_DETAIL} LIKE '%%no pages returned%%'
        )
        OR (
            j.status IN ('failed', 'not found')
            AND ({_DETAIL} LIKE '%%timeout%%' OR {_DETAIL} LIKE '%%timed out%%')
        )
        OR (
            j.status = 'complete'
            AND COALESCE(cr.files_too_large_skipped, 0) > 0
            AND ({_INDEXED_COUNT}) = 0
        )
        OR (j.status = 'complete' AND ({_AFFECTED_COUNT}) > 0)
        OR (
            j.status = 'complete'
            AND ({_HASH_RETAINED_COUNT}) > 0
            AND ({_INDEXED_COUNT}) = 0
        )
    )
"""
_OUTCOME_CASE = f"""
    CASE
        WHEN j.status = 'failed'
            AND {_TRIMMED_DETAIL} LIKE 'skipped duplicate crawl%%'
            THEN 'CRAWL_DUPLICATE_SKIPPED'
        WHEN {_NONEMPTY_FAILURE_SUMMARY}
            AND (
                cr.failure_summary ? 'NO_EMBEDDING_MODEL'
                OR cr.failure_summary ? 'MISSING_PROVIDER'
            )
            THEN 'EMBEDDING_CONFIG_MISSING'
        WHEN {_NONEMPTY_FAILURE_SUMMARY}
            THEN 'CRAWL_COMPLETED_WITH_PAGE_FAILURES'
        WHEN j.status IN ('failed', 'not found')
            AND {_DETAIL} LIKE '%%no pages returned%%'
            THEN 'CRAWL_NO_PAGES_RETURNED'
        WHEN j.status IN ('failed', 'not found')
            AND ({_DETAIL} LIKE '%%timeout%%' OR {_DETAIL} LIKE '%%timed out%%')
            THEN 'CRAWL_TIMEOUT_NO_PAGES'
        WHEN j.status = 'complete'
            AND COALESCE(cr.files_too_large_skipped, 0) > 0
            AND ({_INDEXED_COUNT}) = 0
            THEN 'CRAWL_FILES_TOO_LARGE_ONLY'
        WHEN j.status = 'complete'
            AND ({_AFFECTED_COUNT}) > 0
            THEN 'CRAWL_COMPLETED_WITH_PAGE_FAILURES'
        WHEN j.status = 'complete'
            AND ({_HASH_RETAINED_COUNT}) > 0
            AND ({_INDEXED_COUNT}) = 0
            THEN 'CRAWL_ALL_UNCHANGED'
    END
"""

_COUNT_DERIVABLE_SQL = sa.text(f"""
    SELECT count(*)
    FROM crawl_runs cr
    JOIN jobs j ON j.id = cr.job_id
    WHERE {_DERIVABLE_FILTER}
""")

_BULK_BACKFILL_SQL = sa.text(f"""
    WITH mapped AS (
        SELECT cr.id AS crawl_run_id, {_OUTCOME_CASE} AS outcome_code
        FROM crawl_runs cr
        JOIN jobs j ON j.id = cr.job_id
        WHERE {_DERIVABLE_FILTER}
    )
    UPDATE crawl_runs cr
    SET outcome_code = mapped.outcome_code
    FROM mapped
    WHERE cr.id = mapped.crawl_run_id
        AND mapped.outcome_code IS NOT NULL
""")

_BATCH_BACKFILL_SQL = sa.text(f"""
    WITH candidate AS (
        SELECT cr.id
        FROM crawl_runs cr
        JOIN jobs j ON j.id = cr.job_id
        WHERE {_DERIVABLE_FILTER}
        ORDER BY cr.created_at, cr.id
        LIMIT :batch_size
    ),
    mapped AS (
        SELECT cr.id AS crawl_run_id, {_OUTCOME_CASE} AS outcome_code
        FROM candidate
        JOIN crawl_runs cr ON cr.id = candidate.id
        JOIN jobs j ON j.id = cr.job_id
    )
    UPDATE crawl_runs cr
    SET outcome_code = mapped.outcome_code
    FROM mapped
    WHERE cr.id = mapped.crawl_run_id
        AND mapped.outcome_code IS NOT NULL
    RETURNING cr.id
""")


def upgrade() -> None:
    bind = op.get_bind()
    candidate_count = bind.scalar(_COUNT_DERIVABLE_SQL) or 0
    if candidate_count == 0:
        return

    if candidate_count <= SINGLE_STATEMENT_THRESHOLD:
        bind.execute(_BULK_BACKFILL_SQL)
        return

    while True:
        rows = bind.execute(_BATCH_BACKFILL_SQL, {"batch_size": BATCH_SIZE}).fetchall()
        if len(rows) < BATCH_SIZE:
            return


def downgrade() -> None:
    pass
