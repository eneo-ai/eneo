from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_authoring_policy import AIBuilderAuthoringPolicy
from intric.flows.application.flow_authoring_command import (
    AIBuilderFlowAuthoringOrigin,
    CreateFlowAuthoringCommand,
    EditFlowAuthoringCommand,
    FlowAuthoringCommandService,
)
from intric.flows.domain.flow import Flow, FlowPersistedJsonObject, FlowStep
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)


@pytest.mark.anyio
async def test_prepare_stamps_ai_builder_origin() -> None:
    spec = _spec(
        flow_description="Generate a DOCX-format report.",
        output_type=OutputType.DOCX,
    )
    origin = _origin(spec_hash=spec.spec_hash())

    prepared = await FlowAuthoringCommandService().prepare(
        command=CreateFlowAuthoringCommand(
            space_id=uuid4(),
            spec=spec,
            origin=origin,
        ),
        flow_service=SimpleNamespace(),
        origin_policy=AIBuilderAuthoringPolicy(origin),
    )

    assert prepared.changeset.metadata_json is not None
    metadata = prepared.changeset.metadata_json["ai_builder"]
    assert metadata["origin"] == {
        "builder_session_id": str(origin.session_id),
        "builder_plan_id": str(origin.plan_id),
        "builder_spec_hash": origin.spec_hash,
        "applied_at": origin.applied_at.isoformat(),
    }
    assert "description" not in metadata


@pytest.mark.anyio
async def test_prepare_removes_stale_ai_builder_description_metadata() -> None:
    current_flow = _flow(
        description="Existing description.",
        draft_revision=1,
        steps=[_flow_step(output_type="text")],
        metadata_json={
            "ai_builder": {
                "description": {
                    "stale": True,
                },
                "other": {"kept": True},
            }
        },
    )
    spec = _spec(
        flow_description=current_flow.description or "",
        existing_step_ref="existing_step_1",
        output_type=OutputType.TEXT,
    )
    origin = _origin(spec_hash=spec.spec_hash())

    prepared = await FlowAuthoringCommandService().prepare(
        command=EditFlowAuthoringCommand(
            space_id=current_flow.space_id,
            flow_id=current_flow.id,
            expected_revision=1,
            spec=spec,
            removed_existing_step_refs=frozenset(),
            origin=origin,
        ),
        flow_service=SimpleNamespace(get_flow=_async_return(current_flow)),
        origin_policy=AIBuilderAuthoringPolicy(origin),
    )

    assert prepared.changeset.metadata_json is not None
    ai_builder = prepared.changeset.metadata_json["ai_builder"]
    assert "description" not in ai_builder
    assert ai_builder["other"] == {"kept": True}
    assert ai_builder["origin"]["builder_plan_id"] == str(origin.plan_id)


@pytest.mark.anyio
async def test_prepare_rewrites_builder_managed_stale_terminal_output_description() -> (
    None
):
    current_flow = _flow(
        description="Sammanställer fallöversikt i textformat.",
        draft_revision=1,
        steps=[_flow_step(output_type="text")],
    )
    spec = _spec(
        flow_description=current_flow.description or "",
        existing_step_ref="existing_step_1",
        output_type=OutputType.DOCX,
    )
    origin = _origin(spec_hash=spec.spec_hash())

    prepared = await FlowAuthoringCommandService().prepare(
        command=EditFlowAuthoringCommand(
            space_id=current_flow.space_id,
            flow_id=current_flow.id,
            expected_revision=1,
            spec=spec,
            removed_existing_step_refs=frozenset(),
            origin=origin,
        ),
        flow_service=SimpleNamespace(get_flow=_async_return(current_flow)),
        origin_policy=AIBuilderAuthoringPolicy(origin),
    )

    assert prepared.spec.flow_description == "Sammanställer fallöversikt i DOCX-format."
    assert prepared.changeset.flow_description == prepared.spec.flow_description


@pytest.mark.anyio
async def test_manual_description_override_keeps_current_description() -> None:
    current_flow = _flow(
        description="Sammanställer fallöversikt i textformat.",
        draft_revision=1,
        steps=[_flow_step(output_type="text")],
    )
    spec = _spec(
        flow_description=current_flow.description or "",
        existing_step_ref="existing_step_1",
        output_type=OutputType.DOCX,
    )
    origin = _origin(
        spec_hash=spec.spec_hash(),
        description_override_manual=True,
    )

    prepared = await FlowAuthoringCommandService().prepare(
        command=EditFlowAuthoringCommand(
            space_id=current_flow.space_id,
            flow_id=current_flow.id,
            expected_revision=1,
            spec=spec,
            removed_existing_step_refs=frozenset(),
            origin=origin,
        ),
        flow_service=SimpleNamespace(get_flow=_async_return(current_flow)),
        origin_policy=AIBuilderAuthoringPolicy(origin),
    )

    assert prepared.spec.flow_description == current_flow.description
    assert prepared.changeset.metadata_json is not None
    metadata = prepared.changeset.metadata_json["ai_builder"]
    assert "description" not in metadata
    assert metadata["origin"]["builder_plan_id"] == str(origin.plan_id)


@pytest.mark.anyio
async def test_unsupported_current_flow_signature_leaves_description_unchanged() -> (
    None
):
    current_flow = _flow(
        description="Calls an HTTP source and returns text.",
        draft_revision=1,
        steps=[_flow_step(input_source="http_get", output_type="text")],
    )
    spec = _spec(
        flow_description=current_flow.description or "",
        existing_step_ref="existing_step_1",
        output_type=OutputType.DOCX,
    )
    origin = _origin(spec_hash=spec.spec_hash())

    prepared = await FlowAuthoringCommandService().prepare(
        command=EditFlowAuthoringCommand(
            space_id=current_flow.space_id,
            flow_id=current_flow.id,
            expected_revision=1,
            spec=spec,
            removed_existing_step_refs=frozenset(),
            origin=origin,
        ),
        flow_service=SimpleNamespace(get_flow=_async_return(current_flow)),
        origin_policy=AIBuilderAuthoringPolicy(origin),
    )

    assert prepared.spec.flow_description == current_flow.description


@pytest.mark.anyio
async def test_unsupported_middle_step_signature_leaves_description_unchanged() -> None:
    current_flow = _flow(
        description="Sammanställer fallöversikt i textformat.",
        draft_revision=1,
        steps=[
            _flow_step(step_order=1, input_source="flow_input", output_type="text"),
            _flow_step(step_order=2, input_source="http_get", output_type="json"),
            _flow_step(step_order=3, input_source="previous_step", output_type="text"),
        ],
    )
    spec = _spec(
        flow_description=current_flow.description or "",
        steps=[
            _spec_step(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
            _spec_step(
                plan_step_ref="step_b",
                existing_step_ref="existing_step_2",
                output_type=OutputType.JSON,
            ),
            _spec_step(
                plan_step_ref="step_c",
                existing_step_ref="existing_step_3",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.DOCX,
            ),
        ],
    )
    origin = _origin(spec_hash=spec.spec_hash())

    prepared = await FlowAuthoringCommandService().prepare(
        command=EditFlowAuthoringCommand(
            space_id=current_flow.space_id,
            flow_id=current_flow.id,
            expected_revision=1,
            spec=spec,
            removed_existing_step_refs=frozenset(),
            origin=origin,
        ),
        flow_service=SimpleNamespace(get_flow=_async_return(current_flow)),
        origin_policy=AIBuilderAuthoringPolicy(origin),
    )

    assert prepared.spec.flow_description == current_flow.description


def _spec(
    *,
    flow_description: str = "",
    output_type: OutputType = OutputType.TEXT,
    existing_step_ref: str | None = None,
    steps: list[StepSpec] | None = None,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Flow",
        flow_description=flow_description,
        steps=steps
        or [_spec_step(existing_step_ref=existing_step_ref, output_type=output_type)],
    )


def _spec_step(
    *,
    plan_step_ref: str = "step_a",
    existing_step_ref: str | None = None,
    input_source: InputSource = InputSource.FLOW_INPUT,
    output_type: OutputType = OutputType.TEXT,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=plan_step_ref,
        existing_step_ref=existing_step_ref,
        name="Step A",
        assistant_spec=AssistantSpec(instructions="Do something."),
        input_source=input_source,
        input_type=InputType.TEXT,
        output_mode=OutputMode.PASS_THROUGH,
        output_type=output_type,
    )


def _flow(
    *,
    description: str,
    draft_revision: int,
    steps: list[FlowStep],
    metadata_json: FlowPersistedJsonObject | None = None,
) -> Flow:
    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Existing flow",
        description=description,
        steps=steps,
        draft_revision=draft_revision,
        metadata_json=metadata_json,
    )


def _flow_step(
    *,
    output_type: str,
    input_source: str = "flow_input",
    step_order: int = 1,
) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=f"Step {step_order}",
        input_source=input_source,
        input_type="text",
        output_mode="pass_through",
        output_type=output_type,
        mcp_policy="inherit",
    )


def _origin(
    *,
    spec_hash: str,
    description_override_manual: bool = False,
) -> AIBuilderFlowAuthoringOrigin:
    return AIBuilderFlowAuthoringOrigin(
        session_id=uuid4(),
        plan_id=uuid4(),
        spec_hash=spec_hash,
        applied_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
        description_override_manual=description_override_manual,
    )


def _async_return(value: object):
    async def _inner(*args: object, **kwargs: object) -> object:
        return value

    return _inner
