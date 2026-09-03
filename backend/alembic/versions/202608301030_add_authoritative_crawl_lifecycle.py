"""add authoritative crawl lifecycle

Revision ID: 202608301030
Revises: 202608131000
Create Date: 2026-08-30 10:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "202608301030"
down_revision: str | None = "202608131000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _preflight() -> None:
    # Deployments stop legacy crawl admission/workers before this revision. The
    # crawl table lock closes the remaining admission race without blocking
    # unrelated uploads and background jobs.
    op.execute("LOCK TABLE crawl_runs IN SHARE ROW EXCLUSIVE MODE")
    op.execute(
        """
        SELECT j.id
        FROM jobs AS j
        JOIN crawl_runs AS cr ON cr.job_id = j.id
        ORDER BY j.id
        FOR UPDATE OF j
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM crawl_runs cr
                JOIN jobs j ON j.id = cr.job_id
                WHERE j.task <> 'crawl'
            ) THEN
                RAISE EXCEPTION 'crawl_runs references a non-crawl legacy job';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM crawl_runs
                WHERE job_id IS NOT NULL
                GROUP BY job_id
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION 'multiple crawl_runs reference the same legacy job';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM crawl_runs cr
                JOIN jobs j ON j.id = cr.job_id
                WHERE j.status NOT IN ('queued', 'in progress', 'complete', 'failed')
            ) THEN
                RAISE EXCEPTION 'crawl_runs contains an unknown legacy job status';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM crawl_runs
                WHERE pages_crawled < 0
                   OR files_downloaded < 0
                   OR pages_failed < 0
                   OR files_failed < 0
            ) THEN
                RAISE EXCEPTION 'crawl_runs contains negative counters';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM crawl_runs
                WHERE failure_summary IS NOT NULL
                  AND jsonb_typeof(failure_summary) <> 'object'
            ) THEN
                RAISE EXCEPTION 'crawl_runs contains a malformed failure_summary';
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    _preflight()

    op.add_column("crawl_runs", sa.Column("phase", sa.String(32), nullable=True))
    op.add_column("crawl_runs", sa.Column("outcome", sa.String(32), nullable=True))
    op.add_column("crawl_runs", sa.Column("origin", sa.String(16), nullable=True))
    op.add_column("crawl_runs", sa.Column("result_location", sa.Text(), nullable=True))
    op.add_column(
        "crawl_runs",
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column("crawl_runs", sa.Column("failure_code", sa.String(64), nullable=True))
    op.add_column("crawl_runs", sa.Column("failure_detail", sa.Text(), nullable=True))
    op.add_column(
        "crawl_runs",
        sa.Column("cancel_requested_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "crawl_runs",
        sa.Column("attempt_count", sa.Integer(), nullable=True),
    )

    op.execute(
        """
        UPDATE crawl_runs AS cr
        SET phase = 'terminal',
            outcome = CASE
                WHEN j.status = 'complete'
                     AND (COALESCE(cr.pages_failed, 0) > 0
                          OR COALESCE(cr.files_failed, 0) > 0)
                    THEN 'partial'
                WHEN j.status = 'complete'
                     AND cr.pages_crawled = 0
                     AND COALESCE(cr.files_downloaded, 0) = 0
                    THEN 'empty'
                WHEN j.status = 'complete' THEN 'succeeded'
                WHEN j.status = 'failed' THEN 'failed'
                ELSE 'interrupted'
            END,
            origin = 'legacy',
            result_location = j.result_location,
            finished_at = CASE
                WHEN j.status IN ('queued', 'in progress') THEN now()
                ELSE j.finished_at
            END,
            failure_code = CASE
                WHEN j.status = 'failed' THEN 'processing_failed'
                WHEN j.status = 'complete'
                     AND (COALESCE(cr.pages_failed, 0) > 0
                          OR COALESCE(cr.files_failed, 0) > 0)
                    THEN 'processing_failed'
                WHEN j.status IN ('queued', 'in progress') THEN 'worker_interrupted'
                ELSE NULL
            END,
            failure_detail = CASE
                WHEN j.status IN ('failed', 'queued', 'in progress')
                    THEN left(j.result_location, 512)
                WHEN j.status = 'complete'
                     AND (COALESCE(cr.pages_failed, 0) > 0
                          OR COALESCE(cr.files_failed, 0) > 0)
                    THEN 'Legacy crawl completed with failed resources'
                ELSE NULL
            END,
            attempt_count = 0
        FROM jobs AS j
        WHERE cr.job_id = j.id
        """
    )
    op.execute(
        """
        UPDATE crawl_runs
        SET phase = 'terminal',
            outcome = 'interrupted',
            origin = 'legacy',
            finished_at = now(),
            failure_code = 'dispatch_failed',
            failure_detail = 'Legacy crawl run has no job projection',
            attempt_count = 0
        WHERE phase IS NULL
        """
    )
    op.execute(
        """
        UPDATE jobs AS j
        SET status = 'failed',
            failure_code = 'worker_interrupted',
            finished_at = cr.finished_at
        FROM crawl_runs AS cr
        WHERE cr.job_id = j.id
          AND cr.outcome = 'interrupted'
          AND j.status IN ('queued', 'in progress')
        """
    )

    op.alter_column(
        "crawl_runs",
        "phase",
        existing_type=sa.String(32),
        nullable=False,
        server_default="pending_dispatch",
    )
    op.alter_column(
        "crawl_runs",
        "origin",
        existing_type=sa.String(16),
        nullable=False,
        server_default="manual",
    )
    op.alter_column(
        "crawl_runs",
        "attempt_count",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="0",
    )

    op.create_check_constraint(
        "ck_crawl_runs_phase",
        "crawl_runs",
        "phase IN ('pending_dispatch', 'queued', 'running', 'finalizing', "
        "'stopping', 'terminal')",
    )
    op.create_check_constraint(
        "ck_crawl_runs_outcome",
        "crawl_runs",
        "outcome IS NULL OR outcome IN ('succeeded', 'unchanged', 'empty', "
        "'partial', 'failed', 'cancelled', 'interrupted')",
    )
    op.create_check_constraint(
        "ck_crawl_runs_origin",
        "crawl_runs",
        "origin IN ('manual', 'scheduled', 'legacy')",
    )
    op.create_check_constraint(
        "ck_crawl_runs_terminal_outcome",
        "crawl_runs",
        "(phase = 'terminal') = (outcome IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_crawl_runs_nonterminal_unfinished",
        "crawl_runs",
        "phase = 'terminal' OR finished_at IS NULL",
    )
    op.create_check_constraint(
        "ck_crawl_runs_terminal_finished_at",
        "crawl_runs",
        "phase <> 'terminal' OR origin = 'legacy' OR finished_at IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_crawl_runs_outcome_failure",
        "crawl_runs",
        "(outcome IS NULL AND failure_code IS NULL AND failure_detail IS NULL) OR "
        "(outcome IN ('succeeded', 'unchanged', 'empty') "
        "AND failure_code IS NULL AND failure_detail IS NULL) OR "
        "(outcome IN ('partial', 'failed', 'cancelled', 'interrupted') "
        "AND failure_code IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_crawl_runs_attempt_count",
        "crawl_runs",
        "attempt_count >= 0",
    )
    for column in (
        "pages_crawled",
        "files_downloaded",
        "pages_failed",
        "files_failed",
    ):
        op.create_check_constraint(
            f"ck_crawl_runs_{column}",
            "crawl_runs",
            f"{column} IS NULL OR {column} >= 0",
        )
    op.create_check_constraint(
        "ck_crawl_runs_failure_code",
        "crawl_runs",
        "failure_code IS NULL OR failure_code IN ("
        "'dispatch_failed', 'invalid_dispatch', 'worker_interrupted', "
        "'lease_expired', 'remote_unreachable', 'remote_blocked', "
        "'timed_out', 'processing_failed', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_crawl_runs_failure_detail_length",
        "crawl_runs",
        "failure_detail IS NULL OR char_length(failure_detail) <= 512",
    )
    op.create_unique_constraint(
        "uq_crawl_runs_job_id",
        "crawl_runs",
        ["job_id"],
    )
    op.create_index(
        "uq_crawl_runs_active_website",
        "crawl_runs",
        ["website_id"],
        unique=True,
        postgresql_where=sa.text("phase <> 'terminal'"),
    )
    op.create_index(
        "ix_crawl_runs_pending_dispatch",
        "crawl_runs",
        ["created_at", "id"],
        postgresql_where=sa.text("phase = 'pending_dispatch'"),
    )
    op.create_index(
        "ix_crawl_runs_tenant_phase",
        "crawl_runs",
        ["tenant_id", "phase"],
    )
    op.create_index(
        "ix_crawl_runs_website_created",
        "crawl_runs",
        ["website_id", "created_at", "id"],
    )

    op.create_table(
        "crawl_attempts",
        sa.Column("crawl_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("dispatch_id", UUID(as_uuid=True), nullable=False),
        sa.Column("dispatch_payload", JSONB(), nullable=False),
        sa.Column("dispatch_attempted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(255), nullable=True),
        sa.Column("lease_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("transport_cleaned_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name="ck_crawl_attempts_attempt_number",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(dispatch_payload) = 'object'",
            name="ck_crawl_attempts_dispatch_payload_object",
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name="ck_crawl_attempts_lease_pair",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR lease_owner IS NULL",
            name="ck_crawl_attempts_finished_without_lease",
        ),
        sa.CheckConstraint(
            "lease_owner IS NULL OR started_at IS NOT NULL",
            name="ck_crawl_attempts_lease_requires_start",
        ),
        sa.CheckConstraint(
            "dispatched_at IS NULL OR dispatch_attempted_at IS NOT NULL",
            name="ck_crawl_attempts_dispatch_order",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR dispatched_at IS NOT NULL",
            name="ck_crawl_attempts_start_requires_dispatch",
        ),
        sa.CheckConstraint(
            "finished_at IS NOT NULL OR "
            "(failure_code IS NULL AND failure_detail IS NULL)",
            name="ck_crawl_attempts_terminal_failure",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            "'dispatch_failed', 'invalid_dispatch', 'worker_interrupted', "
            "'lease_expired', 'remote_unreachable', 'remote_blocked', "
            "'timed_out', 'processing_failed', 'cancelled')",
            name="ck_crawl_attempts_failure_code",
        ),
        sa.CheckConstraint(
            "failure_detail IS NULL OR char_length(failure_detail) <= 512",
            name="ck_crawl_attempts_failure_detail_length",
        ),
        sa.CheckConstraint(
            "transport_cleaned_at IS NULL OR failure_code = 'lease_expired'",
            name="ck_crawl_attempts_transport_cleanup",
        ),
        sa.ForeignKeyConstraint(
            ["crawl_run_id"],
            ["crawl_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "crawl_run_id",
            "attempt_number",
            name="uq_crawl_attempts_run_number",
        ),
        sa.UniqueConstraint(
            "dispatch_id",
            name="uq_crawl_attempts_dispatch_id",
        ),
    )
    op.create_index(
        "uq_crawl_attempts_active_run",
        "crawl_attempts",
        ["crawl_run_id"],
        unique=True,
        postgresql_where=sa.text("finished_at IS NULL"),
    )
    op.create_index(
        "ix_crawl_attempts_dispatch_candidates",
        "crawl_attempts",
        ["dispatch_attempted_at", "created_at", "id"],
        postgresql_where=sa.text("dispatched_at IS NULL AND finished_at IS NULL"),
    )
    op.create_index(
        "ix_crawl_attempts_redelivery_candidates",
        "crawl_attempts",
        ["dispatched_at", "dispatch_attempted_at", "created_at", "id"],
        postgresql_where=sa.text(
            "dispatched_at IS NOT NULL AND started_at IS NULL AND finished_at IS NULL"
        ),
    )
    op.create_index(
        "ix_crawl_attempts_expired_lease",
        "crawl_attempts",
        ["lease_expires_at"],
        postgresql_where=sa.text(
            "lease_expires_at IS NOT NULL AND finished_at IS NULL"
        ),
    )
    op.create_index(
        "ix_crawl_attempts_pending_transport_cleanup",
        "crawl_attempts",
        ["finished_at", "id"],
        postgresql_where=sa.text(
            "failure_code = 'lease_expired' AND transport_cleaned_at IS NULL"
        ),
    )
    op.execute(
        """
        CREATE FUNCTION enforce_crawl_run_current_attempt()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            affected_run_ids uuid[];
        BEGIN
            IF TG_TABLE_NAME = 'crawl_runs' THEN
                IF TG_OP = 'DELETE' THEN
                    affected_run_ids := ARRAY[OLD.id];
                ELSE
                    affected_run_ids := ARRAY[NEW.id];
                END IF;
            ELSIF TG_OP = 'DELETE' THEN
                affected_run_ids := ARRAY[OLD.crawl_run_id];
            ELSIF TG_OP = 'INSERT' THEN
                affected_run_ids := ARRAY[NEW.crawl_run_id];
            ELSE
                affected_run_ids := ARRAY[OLD.crawl_run_id, NEW.crawl_run_id];
            END IF;

            IF EXISTS (
                SELECT 1
                FROM crawl_runs AS cr
                WHERE cr.id = ANY(affected_run_ids)
                  AND cr.phase <> 'terminal'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM crawl_attempts AS ca
                      WHERE ca.crawl_run_id = cr.id
                        AND ca.attempt_number = cr.attempt_count
                        AND ca.finished_at IS NULL
                  )
            ) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'active crawl run requires a current unfinished attempt',
                    CONSTRAINT = 'ck_crawl_runs_current_attempt';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER crawl_runs_require_current_attempt
        AFTER INSERT OR UPDATE OR DELETE ON crawl_runs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_crawl_run_current_attempt()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER crawl_attempts_preserve_current_attempt
        AFTER INSERT OR UPDATE OR DELETE ON crawl_attempts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_crawl_run_current_attempt()
        """
    )


def downgrade() -> None:
    op.execute("LOCK TABLE crawl_runs, crawl_attempts IN SHARE ROW EXCLUSIVE MODE")
    op.execute(
        """
        SELECT j.id
        FROM jobs AS j
        JOIN crawl_runs AS cr ON cr.job_id = j.id
        ORDER BY j.id
        FOR UPDATE OF j
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM crawl_runs
                WHERE phase <> 'terminal'
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'crawler lifecycle downgrade requires drained crawl runs',
                    HINT = 'Pause crawl admission and terminalize active crawl runs before retrying.';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM crawl_runs
                WHERE phase = 'terminal'
                  AND job_id IS NULL
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'crawler lifecycle downgrade cannot project runs without jobs',
                    HINT = 'Restore a compatible job projection or retain this migration.';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        UPDATE jobs AS j
        SET status = CASE
                WHEN cr.outcome IN ('succeeded', 'unchanged', 'empty', 'partial')
                    THEN 'complete'
                ELSE 'failed'
            END,
            result_location = CASE
                WHEN cr.outcome IN ('succeeded', 'unchanged', 'empty', 'partial')
                    THEN cr.result_location
                ELSE COALESCE(cr.failure_detail, cr.result_location)
            END,
            failure_code = cr.failure_code,
            finished_at = cr.finished_at
        FROM crawl_runs AS cr
        WHERE cr.job_id = j.id
          AND cr.phase = 'terminal'
        """
    )

    op.execute("DROP TRIGGER crawl_attempts_preserve_current_attempt ON crawl_attempts")
    op.execute("DROP TRIGGER crawl_runs_require_current_attempt ON crawl_runs")
    op.execute("DROP FUNCTION enforce_crawl_run_current_attempt()")

    op.drop_index(
        "ix_crawl_attempts_pending_transport_cleanup",
        table_name="crawl_attempts",
    )
    op.drop_index("ix_crawl_attempts_expired_lease", table_name="crawl_attempts")
    op.drop_index(
        "ix_crawl_attempts_redelivery_candidates",
        table_name="crawl_attempts",
    )
    op.drop_index("ix_crawl_attempts_dispatch_candidates", table_name="crawl_attempts")
    op.drop_index("uq_crawl_attempts_active_run", table_name="crawl_attempts")
    op.drop_table("crawl_attempts")

    op.drop_index("ix_crawl_runs_website_created", table_name="crawl_runs")
    op.drop_index("ix_crawl_runs_tenant_phase", table_name="crawl_runs")
    op.drop_index("ix_crawl_runs_pending_dispatch", table_name="crawl_runs")
    op.drop_index("uq_crawl_runs_active_website", table_name="crawl_runs")
    op.drop_constraint("uq_crawl_runs_job_id", "crawl_runs", type_="unique")
    for constraint in (
        "ck_crawl_runs_failure_detail_length",
        "ck_crawl_runs_failure_code",
        "ck_crawl_runs_files_failed",
        "ck_crawl_runs_pages_failed",
        "ck_crawl_runs_files_downloaded",
        "ck_crawl_runs_pages_crawled",
        "ck_crawl_runs_attempt_count",
        "ck_crawl_runs_outcome_failure",
        "ck_crawl_runs_terminal_finished_at",
        "ck_crawl_runs_nonterminal_unfinished",
        "ck_crawl_runs_terminal_outcome",
        "ck_crawl_runs_origin",
        "ck_crawl_runs_outcome",
        "ck_crawl_runs_phase",
    ):
        op.drop_constraint(constraint, "crawl_runs", type_="check")

    for column in (
        "attempt_count",
        "cancel_requested_at",
        "failure_detail",
        "failure_code",
        "finished_at",
        "result_location",
        "origin",
        "outcome",
        "phase",
    ):
        op.drop_column("crawl_runs", column)
