from __future__ import annotations

from datetime import datetime, timezone
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.flows.domain.flow_run_retention_policy import (
    FlowRunRetentionMode,
    FlowRunRetentionPolicy,
    FlowRunRetentionPolicyStorageError,
    FlowRunRetentionReviewCursor,
    flow_run_retention_policy_from_storage,
    resolve_flow_run_retention_policy,
)
from eneo.flows.infrastructure.flow_run_retention_policy_repo import (
    FlowRunRetentionPolicyRepository,
)


class _EmptyRows:
    def all(self) -> list[object]:
        return []


class _RecordingSession:
    statement: sa.Select[tuple[object, ...]] | None = None

    async def execute(
        self,
        stmt: sa.Select[tuple[object, ...]],
    ) -> _EmptyRows:
        self.statement = stmt
        return _EmptyRows()


def _policy(*, mode: FlowRunRetentionMode, days: int) -> FlowRunRetentionPolicy:
    return FlowRunRetentionPolicy(mode=mode, days=days)


def test_most_specific_complete_flow_policy_can_lengthen_parent_defaults() -> None:
    organization = _policy(mode=FlowRunRetentionMode.PRESERVE, days=30)
    space = _policy(mode=FlowRunRetentionMode.REVIEW_REQUIRED, days=60)
    flow = _policy(mode=FlowRunRetentionMode.PRESERVE, days=90)

    resolved = resolve_flow_run_retention_policy(
        organization_policy=organization,
        space_policy=space,
        flow_policy=flow,
    )

    assert resolved.state == "configured"
    assert resolved.mode is FlowRunRetentionMode.PRESERVE
    assert resolved.effective_days == 90
    assert resolved.source == "flow"
    assert resolved.contributors.model_dump(mode="json") == {
        "organization": {"mode": "preserve", "days": 30},
        "space": {"mode": "review_required", "days": 60},
        "flow": {"mode": "preserve", "days": 90},
    }


def test_absent_child_policy_inherits_the_complete_parent_policy() -> None:
    organization = _policy(mode=FlowRunRetentionMode.PRESERVE, days=30)
    space = _policy(mode=FlowRunRetentionMode.REVIEW_REQUIRED, days=60)

    resolved = resolve_flow_run_retention_policy(
        organization_policy=organization,
        space_policy=space,
        flow_policy=None,
    )

    assert resolved.state == "configured"
    assert resolved.mode is FlowRunRetentionMode.REVIEW_REQUIRED
    assert resolved.effective_days == 60
    assert resolved.source == "space"


def test_no_configured_policy_has_an_explicit_off_projection() -> None:
    resolved = resolve_flow_run_retention_policy(
        organization_policy=None,
        space_policy=None,
        flow_policy=None,
    )

    assert resolved.state == "off"
    assert resolved.mode is None
    assert resolved.effective_days is None
    assert resolved.source == "none"


@pytest.mark.parametrize(
    ("mode", "days"),
    [
        (None, 30),
        (FlowRunRetentionMode.PRESERVE.value, None),
    ],
)
def test_partial_persisted_policy_is_reported_as_corrupt(
    mode: str | None,
    days: int | None,
) -> None:
    with pytest.raises(FlowRunRetentionPolicyStorageError):
        flow_run_retention_policy_from_storage(mode=mode, days=days)


def test_absent_persisted_policy_is_not_confused_with_corruption() -> None:
    assert flow_run_retention_policy_from_storage(mode=None, days=None) is None


def test_automatic_mode_cannot_be_persisted_before_safe_execution_exists() -> None:
    with pytest.raises(ValidationError):
        FlowRunRetentionPolicy.model_validate({"mode": "automatic", "days": 30})


@pytest.mark.parametrize("days", [0, 2556])
def test_policy_days_follow_the_existing_retention_bounds(days: int) -> None:
    with pytest.raises(ValidationError):
        FlowRunRetentionPolicy(mode=FlowRunRetentionMode.PRESERVE, days=days)


def test_review_cursor_round_trips_the_total_order_position() -> None:
    cursor = FlowRunRetentionReviewCursor(
        retention_anchor=datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
        run_id=UUID("00000000-0000-0000-0000-000000000123"),
    )

    assert FlowRunRetentionReviewCursor.deserialize(cursor.serialize()) == cursor


@pytest.mark.asyncio
async def test_review_queue_seeks_in_the_retention_anchor_index_order() -> None:
    session = _RecordingSession()
    repository = FlowRunRetentionPolicyRepository(cast(AsyncSession, session))
    cursor = FlowRunRetentionReviewCursor(
        retention_anchor=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        run_id=UUID("00000000-0000-0000-0000-000000000123"),
    )

    await repository.list_review_queue(
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        now=datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
        limit=50,
        cursor=cursor,
    )

    assert session.statement is not None
    compiled = str(
        session.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    anchor = "coalesce(flow_runs.finished_at, flow_runs.created_at)"
    assert f"ORDER BY {anchor} ASC, flow_runs.id ASC" in compiled
    assert f"{anchor} > '2026-08-01 12:00:00+00:00'" in compiled
    assert "ORDER BY coalesce(flow_runs.finished_at" in compiled
    assert (
        "ORDER BY coalesce(flow_runs.finished_at, flow_runs.created_at) +"
        not in compiled
    )


@pytest.mark.parametrize("value", ["", "not-versioned", "v1.not-base64!"])
def test_review_cursor_rejects_malformed_values(value: str) -> None:
    with pytest.raises(ValueError, match="Invalid Flow retention review cursor"):
        FlowRunRetentionReviewCursor.deserialize(value)
