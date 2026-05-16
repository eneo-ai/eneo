"""backfill_heartbeat_failed_outcome

Revision ID: 202605161200
Revises: 202605152115
Create Date: 2026-05-16 12:00:00.000000

Backfills `crawl_runs.outcome_code` from `'UNKNOWN_CRAWL_ERROR'` to
`'CRAWL_HEARTBEAT_FAILED'` for historical rows whose linked
`jobs.result_location` carries the canonical heartbeat-failure
message produced by the worker when
`CrawlPreempted(cause=HEARTBEAT_FAILURE)` terminates a crawl.

Why a backfill: the forward-looking branch in
`_crawl_task_exception_outcome` already maps new heartbeat-driven
preemptions to the typed `CRAWL_HEARTBEAT_FAILED` outcome (commit
55449d4f). The backfill closes the historical gap so admin filters
land both old + new heartbeat terminations in the same bucket.

Why this WHERE predicate is safe:
- The worker raises `CrawlPreempted` with reason
  `"heartbeat failures exceeded threshold (N/M)"`; the exception
  formats that as `"Crawl preempted: heartbeat failures exceeded
  threshold (N/M)"`, and that is what
  `_record_crawl_task_exception` writes to `jobs.result_location`
  through `commit_terminal`.
- Admin aborts use `"job <uuid> preempted (external FAILED state)"`,
  so the substring `"heartbeat failures exceeded threshold"` is
  unique to heartbeat-failure CrawlPreempted and has been stable
  since `CrawlPreempted` was introduced.
- The downgrade predicate matches the same substring on
  `jobs.result_location` so we only revert what upgrade changed
  (no over-revert of rows that were already
  `CRAWL_HEARTBEAT_FAILED` at runtime but whose linked
  `jobs.result_location` does not carry the marker).
- Tenancy-safe: the heartbeat-failure message is invariant across
  tenants and the outcome code is per-row, so no `tenant_id`
  scoping is required for a correctness backfill of this kind.

Bounded SQL: single UPDATE with the `LIKE` filter joined to `jobs`;
the `outcome_code` equality + the `LIKE` filter bound the row count.
The heartbeat-failure population is small in absolute terms, so
batching is unnecessary.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "202605161200"
down_revision: Union[str, None] = "202605152115"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HEARTBEAT_MESSAGE_FRAGMENT = "%heartbeat failures exceeded threshold%"

_UPGRADE_SQL = sa.text(
    """
    UPDATE crawl_runs cr
    SET outcome_code = 'CRAWL_HEARTBEAT_FAILED'
    FROM jobs j
    WHERE cr.job_id = j.id
        AND cr.outcome_code = 'UNKNOWN_CRAWL_ERROR'
        AND j.result_location IS NOT NULL
        AND j.result_location LIKE :heartbeat_fragment
    """
)

_DOWNGRADE_SQL = sa.text(
    """
    UPDATE crawl_runs cr
    SET outcome_code = 'UNKNOWN_CRAWL_ERROR'
    FROM jobs j
    WHERE cr.job_id = j.id
        AND cr.outcome_code = 'CRAWL_HEARTBEAT_FAILED'
        AND j.result_location IS NOT NULL
        AND j.result_location LIKE :heartbeat_fragment
    """
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        _UPGRADE_SQL,
        {"heartbeat_fragment": _HEARTBEAT_MESSAGE_FRAGMENT},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        _DOWNGRADE_SQL,
        {"heartbeat_fragment": _HEARTBEAT_MESSAGE_FRAGMENT},
    )
