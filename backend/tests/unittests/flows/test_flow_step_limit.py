"""One authoring limit on the number of steps in a flow, enforced wherever a flow is written."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.flows.application.flow_service import FlowService
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.domain.flow_step_validation import (
    FlowGraphIssueCode,
    flow_step_validation_views_from_flow_steps,
)
from eneo.flows.flow_authoring_spec import MAX_FLOW_AUTHORING_STEPS
from eneo.flows.flow_validators import collect_step_graph_issues, validate_steps
from eneo.main.exceptions import BadRequestException

LIMIT_CODE = "flow_step_limit_exceeded"


def _chain(count: int) -> list[FlowStep]:
    """A valid chain of text steps, all served by one assistant."""
    assistant_id = uuid4()
    return [
        FlowStep(
            id=uuid4(),
            assistant_id=assistant_id,
            step_order=order,
            user_description=f"Step {order}",
            input_source="flow_input" if order == 1 else "previous_step",
            input_type="text",
            output_mode="pass_through",
            output_type="text",
        )
        for order in range(1, count + 1)
    ]


def test_the_graph_validator_reports_a_flow_with_too_many_steps_first_and_alone() -> (
    None
):
    issues = collect_step_graph_issues(
        flow_step_validation_views_from_flow_steps(_chain(MAX_FLOW_AUTHORING_STEPS + 1))
    )

    assert [issue.code for issue in issues] == [
        FlowGraphIssueCode.FLOW_STEP_LIMIT_EXCEEDED
    ]
    assert issues[0].context == {
        "step_count": MAX_FLOW_AUTHORING_STEPS + 1,
        "max_steps": MAX_FLOW_AUTHORING_STEPS,
    }
    assert str(MAX_FLOW_AUTHORING_STEPS) in issues[0].message


def test_a_flow_of_the_largest_size_passes_the_graph_validator() -> None:
    validate_steps(_chain(MAX_FLOW_AUTHORING_STEPS))


def test_the_refusal_has_the_shape_of_every_flow_validation_error() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        validate_steps(_chain(MAX_FLOW_AUTHORING_STEPS + 1))

    assert exc_info.value.code == LIMIT_CODE
    assert exc_info.value.context == {
        "issue_code": LIMIT_CODE,
        "step_count": MAX_FLOW_AUTHORING_STEPS + 1,
        "max_steps": MAX_FLOW_AUTHORING_STEPS,
    }
    assert "at most" in str(exc_info.value)


def _service(user, flow_repo) -> FlowService:
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=AsyncMock(),
        assistant_service=AsyncMock(),
        template_asset_service=AsyncMock(),
    )
    service._validate_assistant_scope_for_steps = AsyncMock()  # type: ignore[method-assign]
    return service


def _saved_flow(user, steps: list[FlowStep]) -> Flow:
    now = datetime.now(timezone.utc)
    return Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Draft",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=now,
        updated_at=now,
        steps=steps,
    )


@pytest.mark.asyncio
async def test_create_refuses_one_step_too_many_and_writes_nothing(user):
    flow_repo = AsyncMock()
    service = _service(user, flow_repo)

    with pytest.raises(BadRequestException) as exc_info:
        await service.create_flow(
            space_id=uuid4(),
            name="Big",
            steps=_chain(MAX_FLOW_AUTHORING_STEPS + 1),
        )

    assert exc_info.value.code == LIMIT_CODE
    flow_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_accepts_the_largest_flow(user):
    flow_repo = AsyncMock()
    flow_repo.create.side_effect = lambda flow, tenant_id: flow
    service = _service(user, flow_repo)

    await service.create_flow(
        space_id=uuid4(), name="Big", steps=_chain(MAX_FLOW_AUTHORING_STEPS)
    )

    flow_repo.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_refuses_one_step_too_many_and_writes_nothing(user):
    flow_repo = AsyncMock()
    stored = _chain(2)
    flow_repo.get.return_value = _saved_flow(user, stored)
    service = _service(user, flow_repo)

    with pytest.raises(BadRequestException) as exc_info:
        await service.update_flow(
            flow_id=flow_repo.get.return_value.id,
            steps=_chain(MAX_FLOW_AUTHORING_STEPS + 1),
        )

    assert exc_info.value.code == LIMIT_CODE
    flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_accepts_the_largest_flow(user):
    flow_repo = AsyncMock()
    stored = _chain(MAX_FLOW_AUTHORING_STEPS)
    flow = _saved_flow(user, stored)
    flow_repo.get.return_value = flow
    flow_repo.update.side_effect = lambda flow, tenant_id, expected_revision=None: flow
    service = _service(user, flow_repo)

    await service.update_flow(flow_id=flow.id, steps=stored)

    flow_repo.update.assert_awaited_once()
