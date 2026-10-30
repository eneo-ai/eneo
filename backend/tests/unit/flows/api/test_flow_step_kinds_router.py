"""The step kinds read answers the places it is asked about, judged on the
draft with its saved prompts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.flows.api import flow_step_kinds_router
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.domain.step_kinds import FlowStepKind
from eneo.main.exceptions import BadRequestException, NotFoundException


def _flow() -> Flow:
    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Flow",
        draft_revision=7,
        steps=[
            FlowStep(
                id=uuid4(),
                assistant_id=uuid4(),
                step_order=order,
                user_description=f"Step {order}",
                input_source="flow_input" if order == 1 else "previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            )
            for order in (1, 2)
        ],
    )


@pytest.fixture
def read(monkeypatch: pytest.MonkeyPatch):
    flow = _flow()
    monkeypatch.setattr(
        flow_step_kinds_router,
        "require_flow_current_definition_access",
        AsyncMock(return_value=SimpleNamespace(flow=flow)),
    )
    container = MagicMock()
    service = AsyncMock()
    service.get_flow_assistant_prompts.return_value = {
        flow.steps[1].assistant_id: SimpleNamespace(text="Use {{step_1}}.")
    }
    container.flow_service.return_value = service

    async def call(**query: object):
        return await flow_step_kinds_router.get_flow_step_kinds(
            id=flow.require_persisted_id(),
            request=SimpleNamespace(state=SimpleNamespace()),  # type: ignore[arg-type]
            container=container,
            **query,  # type: ignore[arg-type]
        )

    return flow, call


async def test_a_read_that_names_no_place_is_refused(read, monkeypatch):
    # Every place at once judges the whole draft per kind and place: work that
    # grows with the square of the step count, in one request.
    _, call = read
    answer = MagicMock()
    monkeypatch.setattr(flow_step_kinds_router, "step_kind_answer", answer)

    with pytest.raises(BadRequestException, match="position or step_id"):
        await call()
    answer.assert_not_called()


async def test_a_place_and_a_step_named_together_are_both_answered(read):
    flow, call = read

    answer = await call(position=1, step_id=flow.steps[0].id)

    assert answer.flow_id == flow.id
    assert answer.draft_revision == 7
    assert [place.position for place in answer.insertions] == [1]
    assert [place.step_id for place in answer.steps] == [flow.steps[0].id]
    assert [option.kind for option in answer.steps[0].options] == list(FlowStepKind)


async def test_a_named_place_is_the_only_one_answered(read):
    flow, call = read

    by_position = await call(position=3)
    by_step = await call(step_id=flow.steps[1].id)

    assert [place.position for place in by_position.insertions] == [3]
    assert by_position.steps == []
    assert by_step.insertions == []
    assert [place.step_id for place in by_step.steps] == [flow.steps[1].id]
    send = next(o for o in by_position.insertions[0].options if o.kind == "send_http")
    assert send.allowed
    assert send.configuration.output_config is not None
    assert send.configuration.output_config["url"] == ""


async def test_a_place_the_draft_does_not_have_is_refused(read):
    _, call = read

    with pytest.raises(BadRequestException, match="between 1 and 3"):
        await call(position=4)
    with pytest.raises(NotFoundException):
        await call(step_id=uuid4())
