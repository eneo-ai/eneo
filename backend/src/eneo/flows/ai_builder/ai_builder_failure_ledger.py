"""Group persisted Flow AI Builder failures for triage.

One read-only query surface over the three stores the product already writes:
the latest-turn failure snapshot on builder sessions, failed flow runs, and
client-reported errors. Sample ids are the entry point for root-cause work — a
session id resolves to the full stored conversation, plan and error turn. No
new telemetry is collected here.

Scope, stated honestly: the builder section is a SNAPSHOT — sessions whose
*latest* turn ended in a failure state (`failed_before_provider`,
`provider_outcome_unknown`) or committed carrying a user-visible error. Turn
history is not persisted per turn, so a session that failed and then recovered
leaves this snapshot; the backend log owns full failure history. Its time
filter is the session's generic ``updated_at`` — there is no failure-occurrence
timestamp — so it reads as "current latest-turn failures on sessions updated
since the cutoff": an old standing failure resurfaces in a recent window when
any unrelated session update touches the row.

Each section returns at most ``MAX_FAMILIES`` families (largest first, ties
broken deterministically by label) with at most ``MAX_SAMPLE_IDS`` sample ids,
and reports ``total_families`` so truncation is visible, never silent.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from pydantic import BaseModel, Field, computed_field
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

MAX_FAMILIES = 20
MAX_SAMPLE_IDS = 5
# One owner for the window: the API's maximum queryable range, the CLI bound
# and the storage TTL all read this. Older rows have no consumer.
MAX_WINDOW_DAYS = 90


class FailureFamily(BaseModel):
    """One failure family: a label pair, its size, and a few entry points."""

    group: str
    detail: str
    occurrences: int = Field(ge=0)
    sample_ids: list[str] = Field(max_length=MAX_SAMPLE_IDS)


class FailureSection(BaseModel):
    """One grouping with explicit truncation accounting."""

    families: list[FailureFamily] = Field(max_length=MAX_FAMILIES)
    total_families: int = Field(ge=0)

    @computed_field
    @property
    def truncated(self) -> bool:
        return self.total_families > len(self.families)


class FailureSummary(BaseModel):
    """The whole triage report, shared by the script and the sysadmin API."""

    since: datetime
    builder_turn_failure_snapshot: FailureSection = Field(
        description=(
            "Current latest-turn failures on sessions UPDATED since the "
            "cutoff — sessions carry no failure-occurrence timestamp, so "
            "this is a present-state snapshot, not failure history."
        )
    )
    flow_run_failures: FailureSection
    client_errors: FailureSection


_BUILDER_TURN_FAILURE_SNAPSHOT = sa.text(
    f"""
    with families as (
        select case when latest_turn_state = 'committed'
                    then 'committed_with_error'
                    else latest_turn_state end as grp,
               coalesce(latest_turn_error_jsonb->>'code', 'none') as detail,
               count(*) as occurrences
        from builder_sessions
        where updated_at >= :since
          and (latest_turn_state in
                   ('failed_before_provider', 'provider_outcome_unknown')
               or latest_turn_error_jsonb is not null)
        group by 1, 2
    )
    select f.grp, f.detail, f.occurrences, count(*) over () as total_families,
           s.sample_ids
    from families f
    cross join lateral (
        select array_agg(id) as sample_ids
        from (
            select bs.id::text as id
            from builder_sessions bs
            where bs.updated_at >= :since
              and case when bs.latest_turn_state = 'committed'
                       then 'committed_with_error'
                       else bs.latest_turn_state end = f.grp
              and coalesce(bs.latest_turn_error_jsonb->>'code', 'none')
                  = f.detail
              and (bs.latest_turn_state in
                       ('failed_before_provider', 'provider_outcome_unknown')
                   or bs.latest_turn_error_jsonb is not null)
            order by bs.updated_at desc, bs.id
            limit {MAX_SAMPLE_IDS}
        ) ids
    ) s
    order by f.occurrences desc, f.grp, f.detail
    limit {MAX_FAMILIES}
    """
)

_FLOW_RUN_FAILURES = sa.text(
    f"""
    with families as (
        select status,
               coalesce(error_json->>'code', 'unknown') as error_code,
               count(*) as occurrences
        from flow_runs
        where created_at >= :since
          and status in ('failed', 'cancelled')
        group by 1, 2
    )
    select f.status as grp, f.error_code as detail, f.occurrences,
           count(*) over () as total_families,
           s.sample_ids
    from families f
    cross join lateral (
        select array_agg(id) as sample_ids
        from (
            select r.id::text as id
            from flow_runs r
            where r.created_at >= :since
              and r.status = f.status
              and coalesce(r.error_json->>'code', 'unknown') = f.error_code
            order by r.created_at desc, r.id
            limit {MAX_SAMPLE_IDS}
        ) ids
    ) s
    order by f.occurrences desc, f.status, f.error_code
    limit {MAX_FAMILIES}
    """
)

_CLIENT_ERRORS = sa.text(
    f"""
    with families as (
        select category, code, count(*) as occurrences
        from builder_client_errors
        where created_at >= :since
        group by 1, 2
    )
    select f.category as grp, f.code as detail, f.occurrences,
           count(*) over () as total_families,
           s.sample_ids
    from families f
    cross join lateral (
        select array_agg(ref) as sample_ids
        from (
            select coalesce(e.session_id::text, e.request_id, e.id::text)
                       as ref
            from builder_client_errors e
            where e.created_at >= :since
              and e.category = f.category
              and e.code = f.code
            order by e.created_at desc, e.id
            limit {MAX_SAMPLE_IDS}
        ) refs
    ) s
    order by f.occurrences desc, f.category, f.code
    limit {MAX_FAMILIES}
    """
)


async def collect_failure_summary(
    connection: AsyncSession | AsyncConnection,
    *,
    since: datetime,
) -> FailureSummary:
    """Failure families with counts and sample ids.

    ``since`` filters flow runs and client errors by their creation time; the
    builder snapshot filters by session ``updated_at`` (see the module note).
    """

    sections: dict[str, FailureSection] = {}
    for key, stmt in (
        ("builder_turn_failure_snapshot", _BUILDER_TURN_FAILURE_SNAPSHOT),
        ("flow_run_failures", _FLOW_RUN_FAILURES),
        ("client_errors", _CLIENT_ERRORS),
    ):
        result = await connection.execute(stmt, {"since": since})
        families: list[FailureFamily] = []
        total = 0
        for row in result.mappings():
            total = row["total_families"]
            families.append(
                FailureFamily(
                    group=row["grp"],
                    detail=row["detail"],
                    occurrences=row["occurrences"],
                    sample_ids=list(row["sample_ids"] or []),
                )
            )
        sections[key] = FailureSection(families=families, total_families=total)
    return FailureSummary(since=since, **sections)
