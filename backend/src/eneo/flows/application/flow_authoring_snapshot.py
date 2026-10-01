from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum

from eneo.flows.assistant_authoring_snapshot import (
    AssistantAuthoringSnapshot,
    AssistantAuthoringSnapshots,
)
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_name import normalize_flow_name
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_capability_manifest import (
    CapabilityAxis,
    CapabilityProjection,
    projection_values,
)
from eneo.flows.http_transport import redact_persisted_config
from eneo.flows.step_lineage import existing_step_ref_for_order

AssistantSnapshotProjector = Callable[[AssistantAuthoringSnapshot], AssistantSpec]

# The authoring vocabulary, per axis: a saved step with a value outside it runs
# on the platform but cannot be carried by an authoring spec. Whether a
# combination of carried values may run is the platform validators' decision.
_AUTHORING_AXES: tuple[CapabilityAxis, ...] = (
    "input_source",
    "input_type",
    "output_mode",
    "output_type",
)
_EDITABLE_VALUES: dict[CapabilityAxis, frozenset[str]] = {
    axis: frozenset(projection_values(CapabilityProjection.EDITABLE_EXISTING, axis))
    for axis in _AUTHORING_AXES
}


@dataclass(frozen=True, slots=True)
class UnsupportedSavedStep:
    """A saved step the authoring vocabulary cannot carry, and why.

    ``fields`` holds ``(field, raw enum value)`` pairs only: configuration and
    credentials never travel with it.
    """

    step_order: int
    existing_step_ref: str
    name: str
    fields: tuple[tuple[str, str], ...]


class UnsupportedSavedStepsError(ValueError):
    """Saved steps the authoring vocabulary cannot carry.

    A ``ValueError`` so callers that already tolerate an unprojectable step keep
    doing so; callers that can answer the user read ``steps`` instead.
    """

    def __init__(self, steps: Sequence[UnsupportedSavedStep]) -> None:
        self.steps = tuple(steps)
        super().__init__(
            "Saved steps outside the authoring vocabulary: "
            + "; ".join(
                f"{step.existing_step_ref} "
                + ", ".join(f"{field}={value}" for field, value in step.fields)
                for step in self.steps
            )
        )


def _saved_value(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else value


def unsupported_saved_steps(
    steps: Sequence[FlowStep],
) -> tuple[UnsupportedSavedStep, ...]:
    """Every saved step outside the authoring vocabulary, in step order."""

    listed: list[UnsupportedSavedStep] = []
    for step in steps:
        saved: dict[CapabilityAxis, str] = {
            "input_source": _saved_value(step.input_source),
            "input_type": _saved_value(step.input_type),
            "output_mode": _saved_value(step.output_mode),
            "output_type": _saved_value(step.output_type),
        }
        fields = tuple(
            (field, value)
            for field, value in saved.items()
            if value not in _EDITABLE_VALUES[field]
        )
        if fields:
            ref = existing_step_ref_for_order(step.step_order)
            listed.append(
                UnsupportedSavedStep(
                    step_order=step.step_order,
                    existing_step_ref=ref,
                    name=step.user_description or ref,
                    fields=fields,
                )
            )
    return tuple(listed)


def current_flow_authoring_spec(
    *,
    current_steps: list[FlowStep],
    flow_name: str | None,
    flow_description: str | None,
    assistant_snapshots: AssistantAuthoringSnapshots | None,
    assistant_snapshot_projector: AssistantSnapshotProjector | None = None,
    form_fields: list[FormFieldSpec] | None = None,
) -> FlowDraftSpecCore:
    spec = FlowDraftSpecCore(
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
    return _with_document_body_writer_identity(spec)


def _with_document_body_writer_identity(spec: FlowDraftSpecCore) -> FlowDraftSpecCore:
    """Reconstruct persisted body-writer identity for every snapshot consumer.

    Persisted Flows do not store ``document_body_writer_step_refs``; the
    compose-then-render adjacency is the durable identity. Reconstructing it
    here keeps edit compilation and checkpoint-baseline resolution on one
    owner.
    """

    body_writer_refs = tuple(
        step.plan_step_ref
        for step, next_step in zip(spec.steps, spec.steps[1:], strict=False)
        if step.output_mode == OutputMode.COMPOSE_TEXT
        and next_step.output_mode == OutputMode.RENDER_VERBATIM
    )
    if not body_writer_refs:
        return spec
    return spec.model_copy(update={"document_body_writer_step_refs": body_writer_refs})


def flow_step_to_authoring_spec(
    step: FlowStep,
    plan_ref: str,
    *,
    assistant_snapshots: AssistantAuthoringSnapshots | None = None,
    assistant_snapshot_projector: AssistantSnapshotProjector | None = None,
) -> StepSpec:
    if unsupported := unsupported_saved_steps([step]):
        raise UnsupportedSavedStepsError(unsupported)
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
        input_bindings=step.input_bindings,
        input_contract=step.input_contract,
        output_contract=step.output_contract,
        # Stored credentials become sentinels here: an authoring spec is
        # resubmitted through update_flow, and a real secret coming back in
        # would be indistinguishable from one the author just typed.
        input_config=redact_persisted_config(step.input_config),
        output_config=redact_persisted_config(step.output_config),
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

    if snapshot.model is None and not snapshot.knowledge_refs:
        return AssistantSpec(instructions=snapshot.instructions)

    raise ValueError("Assistant snapshot projector is required for resource refs.")


__all__ = [
    "AssistantSnapshotProjector",
    "UnsupportedSavedStep",
    "UnsupportedSavedStepsError",
    "current_flow_authoring_spec",
    "flow_step_to_authoring_spec",
    "unsupported_saved_steps",
]
