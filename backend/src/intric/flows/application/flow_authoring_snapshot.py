from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from intric.flows.assistant_authoring_snapshot import (
    AssistantAuthoringSnapshot,
    AssistantAuthoringSnapshots,
)
from intric.flows.domain.flow import Flow, FlowStep
from intric.flows.flow_authoring_name import normalize_flow_name
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.step_lineage import existing_step_ref_for_order

AssistantSnapshotProjector = Callable[[AssistantAuthoringSnapshot], AssistantSpec]


@dataclass(frozen=True, slots=True)
class FlowAuthoringUnsupportedFeature:
    code: str
    message: str
    step_ref: str | None = None


@dataclass(frozen=True, slots=True)
class FlowAuthoringSnapshot:
    spec: FlowDraftSpecCore
    draft_revision: int
    existing_step_refs: tuple[str, ...]
    unsupported_features: tuple[FlowAuthoringUnsupportedFeature, ...] = ()


def flow_to_authoring_snapshot(
    flow: Flow,
    *,
    assistant_snapshots: AssistantAuthoringSnapshots | None = None,
    assistant_snapshot_projector: AssistantSnapshotProjector | None = None,
    form_fields: list[FormFieldSpec] | None = None,
) -> FlowAuthoringSnapshot:
    spec = current_flow_authoring_spec(
        current_steps=list(flow.steps),
        flow_name=flow.name,
        flow_description=flow.description,
        assistant_snapshots=assistant_snapshots,
        assistant_snapshot_projector=assistant_snapshot_projector,
        form_fields=form_fields,
    )
    return FlowAuthoringSnapshot(
        spec=spec,
        draft_revision=flow.draft_revision,
        existing_step_refs=tuple(
            ref for step in spec.steps if (ref := step.existing_step_ref) is not None
        ),
    )


def current_flow_authoring_spec(
    *,
    current_steps: list[FlowStep],
    flow_name: str | None,
    flow_description: str | None,
    assistant_snapshots: AssistantAuthoringSnapshots | None,
    assistant_snapshot_projector: AssistantSnapshotProjector | None = None,
    form_fields: list[FormFieldSpec] | None = None,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name=normalize_flow_name(flow_name or "Unnamed Flow"),
        flow_description=flow_description or "",
        steps=[
            flow_step_to_authoring_spec(
                step,
                plan_ref=existing_step_ref_for_order(step.step_order),
                assistant_snapshots=assistant_snapshots,
                assistant_snapshot_projector=assistant_snapshot_projector,
            )
            for step in current_steps
        ],
        form_fields=form_fields,
    )


def flow_step_to_authoring_spec(
    step: FlowStep,
    plan_ref: str,
    *,
    assistant_snapshots: AssistantAuthoringSnapshots | None = None,
    assistant_snapshot_projector: AssistantSnapshotProjector | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=plan_ref,
        existing_step_ref=existing_step_ref_for_order(step.step_order),
        name=step.user_description or f"Step {step.step_order}",
        assistant_spec=_resolve_existing_assistant_spec(
            step=step,
            assistant_snapshots=assistant_snapshots,
            assistant_snapshot_projector=assistant_snapshot_projector,
        ),
        input_source=InputSource(step.input_source),
        input_type=InputType(step.input_type),
        output_mode=OutputMode(step.output_mode),
        output_type=OutputType(step.output_type),
        mcp_policy=MCPPolicy(step.mcp_policy),
        input_bindings=step.input_bindings,
        input_contract=step.input_contract,
        output_contract=step.output_contract,
        input_config=step.input_config,
        output_config=step.output_config,
        review_policy=step.review_policy,
    )


def _resolve_existing_assistant_spec(
    *,
    step: FlowStep,
    assistant_snapshots: AssistantAuthoringSnapshots | None,
    assistant_snapshot_projector: AssistantSnapshotProjector | None,
) -> AssistantSpec:
    if not assistant_snapshots:
        return AssistantSpec(instructions="")

    snapshot = assistant_snapshots.get(step.assistant_id)
    if snapshot is None:
        return AssistantSpec(instructions="")

    if assistant_snapshot_projector is not None:
        return assistant_snapshot_projector(snapshot)

    if (
        snapshot.model is None
        and not snapshot.knowledge_refs
        and not snapshot.mcp_server_refs
        and not snapshot.mcp_tool_refs
    ):
        return AssistantSpec(instructions=snapshot.instructions)

    raise ValueError("Assistant snapshot projector is required for resource refs.")


__all__ = [
    "AssistantSnapshotProjector",
    "FlowAuthoringSnapshot",
    "FlowAuthoringUnsupportedFeature",
    "current_flow_authoring_spec",
    "flow_step_to_authoring_spec",
    "flow_to_authoring_snapshot",
]
