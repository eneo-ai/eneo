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
from intric.flows.domain.flow import Flow, FlowStep
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
async def test_prepare_stamps_ai_builder_origin_and_description_provenance() -> None:
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
    assert metadata["description"]["mode"] == "builder_managed"
    assert metadata["description"]["last_generated_hash"] is not None
    assert (
        metadata["description"]["semantic_signature"]["terminal_output_type"] == "docx"
    )


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
    description_metadata = prepared.changeset.metadata_json["ai_builder"]["description"]
    assert description_metadata["mode"] == "manual"
    assert description_metadata["semantic_signature"] is None
    assert description_metadata["last_generated_hash"] is None


def _spec(
    *,
    flow_description: str = "",
    output_type: OutputType = OutputType.TEXT,
    existing_step_ref: str | None = None,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Flow",
        flow_description=flow_description,
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                existing_step_ref=existing_step_ref,
                name="Step A",
                assistant_spec=AssistantSpec(instructions="Do something."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=output_type,
            )
        ],
    )


def _flow(
    *,
    description: str,
    draft_revision: int,
    steps: list[FlowStep],
) -> Flow:
    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Existing flow",
        description=description,
        steps=steps,
        draft_revision=draft_revision,
    )


def _flow_step(*, output_type: str) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=1,
        user_description="Step A",
        input_source="flow_input",
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
