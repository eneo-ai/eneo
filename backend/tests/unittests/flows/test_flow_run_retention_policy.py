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
    FlowRunRetentionWriteRules,
    flow_run_retention_change_postpones_deletion,
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


@pytest.mark.parametrize("days", [0, -1])
def test_policy_days_are_at_least_one(days: int) -> None:
    with pytest.raises(ValidationError):
        FlowRunRetentionPolicy(mode=FlowRunRetentionMode.PRESERVE, days=days)


AUTO = FlowRunRetentionMode.AUTO_DELETE
KEEP = FlowRunRetentionMode.PRESERVE
REVIEW = FlowRunRetentionMode.REVIEW_REQUIRED


@pytest.mark.parametrize(
    ("before", "after", "postpones"),
    [
        ((AUTO, 30), None, True),
        ((AUTO, 30), (KEEP, 30), True),
        ((AUTO, 30), (REVIEW, 10), True),
        ((AUTO, 30), (AUTO, 31), True),
        ((AUTO, 30), (AUTO, 30), False),
        ((AUTO, 30), (AUTO, 29), False),
        (None, (AUTO, 30), False),
        ((KEEP, 30), None, False),
        ((KEEP, 30), (KEEP, 90), False),
        ((REVIEW, 30), (KEEP, 300), False),
        (None, None, False),
    ],
)
def test_only_a_change_that_stops_or_delays_auto_delete_postpones_deletion(
    before: tuple[FlowRunRetentionMode, int] | None,
    after: tuple[FlowRunRetentionMode, int] | None,
    postpones: bool,
) -> None:
    def policy(value: tuple[FlowRunRetentionMode, int] | None):
        return None if value is None else _policy(mode=value[0], days=value[1])

    assert (
        flow_run_retention_change_postpones_deletion(
            before=policy(before), after=policy(after)
        )
        is postpones
    )


def test_review_cursor_round_trips_the_total_order_position() -> None:
    cursor = FlowRunRetentionReviewCursor(
        retention_anchor=datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
        run_id=UUID("00000000-0000-0000-0000-000000000123"),
    )

    assert FlowRunRetentionReviewCursor.deserialize(cursor.serialize()) == cursor


@pytest.mark.asyncio
async def test_review_queue_seeks_in_the_retention_anchor_index_order() -> None:
    session = _RecordingSession()
    repository = FlowRunRetentionPolicyRepository(
        cast(AsyncSession, session),
        write_rules=FlowRunRetentionWriteRules(
            max_days=36_500, auto_delete_available=False
        ),
    )
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


def test_the_deployment_maximum_stays_within_100_years() -> None:
    # Every cutoff `now - days` must stay a valid timestamp.
    from eneo.main.config import Settings

    field = Settings.model_fields["flow_retention_max_days"]
    assert [
        getattr(item, "le", None) for item in field.metadata if hasattr(item, "le")
    ] == [36_500]


@pytest.mark.parametrize(
    "present,choice", [(True, None), (True, False), (True, True), (False, None)]
)
def test_audio_after_use_requires_an_explicit_nullable_scope_choice(
    present: bool,
    choice: bool | None,
) -> None:
    """Kills G5-P01: silently reset an omitted destructive choice to inheritance."""
    from eneo.settings.settings import FlowRunRetentionPolicyReplaceRequest

    payload: dict[str, object] = {"policy": None}
    if present:
        payload["delete_transcription_audio_after_use"] = choice
        request = FlowRunRetentionPolicyReplaceRequest.model_validate(payload)
        assert request.delete_transcription_audio_after_use is choice
    else:
        with pytest.raises(ValidationError) as error:
            FlowRunRetentionPolicyReplaceRequest.model_validate(payload)
        assert error.value.errors()[0]["loc"] == (
            "delete_transcription_audio_after_use",
        )
        assert error.value.errors()[0]["type"] == "missing"


@pytest.mark.parametrize(
    "organization,space,flow,inherited,effective",
    [
        (None, None, None, False, False),
        (True, None, None, True, True),
        (True, False, None, False, False),
        (False, True, None, True, True),
        (True, True, False, True, False),
        (False, False, True, False, True),
    ],
)
def test_audio_after_use_projects_explicit_false_before_inheritance(
    organization: bool | None,
    space: bool | None,
    flow: bool | None,
    inherited: bool,
    effective: bool,
) -> None:
    """Kills G5-P02/P05: reverse precedence or lose a parent in the read projection."""
    from eneo.flows.domain.flow_run_retention_policy import (
        FlowRunRetentionScope,
        flow_run_retention_policy_settings,
    )

    settings = flow_run_retention_policy_settings(
        scope=FlowRunRetentionScope.FLOW,
        scope_id=UUID(int=1),
        write_rules=FlowRunRetentionWriteRules(
            max_days=36500, auto_delete_available=True
        ),
        organization_policy=None,
        organization_audio=organization,
        space_audio=space,
        flow_audio=flow,
    )
    assert settings.transcription_audio.model_dump() == {
        "local": flow,
        "inherited": inherited,
        "effective": effective,
    }


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_audio_after_use_nullable_migration_emits_offline_ddl(direction: str) -> None:
    """Kills missing scope DDL, eager data rewrite, or offline catalog inspection."""
    import io
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    output = io.StringIO()
    config = Config(
        str(Path(__file__).parents[3] / "alembic.ini"), output_buffer=output
    )
    config.set_main_option(
        "sqlalchemy.url", "postgresql://offline:offline@localhost/offline"
    )
    if direction == "upgrade":
        command.upgrade(config, "202610061600:202610061700", sql=True)
    else:
        command.downgrade(config, "202610061700:202610061600", sql=True)
    ddl = output.getvalue()
    for table in ("tenants", "spaces", "flows"):
        operation = "ADD COLUMN" if direction == "upgrade" else "DROP COLUMN"
        assert (
            f"ALTER TABLE {table} {operation} delete_transcription_audio_after_use"
            in ddl
        )
    assert "BOOLEAN NOT NULL" not in ddl
    assert "pg_index" not in ddl
    assert "UPDATE tenants" not in ddl
    assert "UPDATE spaces" not in ddl
    assert "UPDATE flows" not in ddl
