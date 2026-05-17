from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, TypeAlias, TypeGuard

from pydantic import BaseModel, ConfigDict, Field

from intric.flows.enums import FlowRunReviewCheckpointState
from intric.flows.flow_run_evidence_export_manifest import (
    EvidenceReviewCheckpointSummary,
)
from intric.flows.flow_run_provenance import PayloadPreview

EvidenceOutputKind: TypeAlias = Literal[
    "empty", "text", "structured", "artifact", "mixed"
]
EvidenceReviewDecision: TypeAlias = Literal["approved", "rejected", "cancelled"]


class EvidenceFinalOutputSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EvidenceOutputKind
    text_present: bool
    text_preview: PayloadPreview | None = None
    structured_present: bool
    artifact_count: int
    artifact_names: list[str]


class EvidenceStepReviewEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str
    state: FlowRunReviewCheckpointState
    decision: EvidenceReviewDecision | None = None
    edited: bool
    resumed: bool
    attempt_no: int
    revision: int
    output_changed: bool | None = Field(
        default=None,
        description=(
            "True when the exported original and current checkpoint payloads differ, "
            "false when both are present and equal, and null when either payload is "
            "not available in the exported evidence."
        ),
    )


class EvidenceStepReviewImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint_count: int
    any_edited: bool
    any_resumed: bool
    any_output_changed: bool
    last_event: EvidenceStepReviewEvent | None = None
    events: list[EvidenceStepReviewEvent]


class EvidenceStepOverview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_order: int
    step_id: str | None = None
    user_description: str | None = None
    status: str | None = None
    attempts_count: int
    retries: int
    duration_ms: int | None = None
    models_used: list[str]
    artifact_names: list[str]
    result_output_kind: EvidenceOutputKind | None = None
    output_summary: PayloadPreview | None = None
    configured_input_type: str | None = None
    configured_output_type: str | None = None
    review_impact: EvidenceStepReviewImpact


class EvidenceExportSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    trace_id: str | None = None
    steps_count: int
    completed_steps: int
    failed_steps: int
    attempts_count: int
    artifacts_count: int
    duration_ms: int | None = None
    models_used: list[str]
    review_checkpoints: EvidenceReviewCheckpointSummary
    final_output: EvidenceFinalOutputSummary
    step_overview: list[EvidenceStepOverview]


def build_evidence_export_summary(
    legacy_summary: Mapping[str, object],
    *,
    review_checkpoints: Sequence[Mapping[str, object]],
) -> EvidenceExportSummary:
    """Project legacy export summary into a typed additive API contract."""
    review_events_by_step_order = _review_events_by_step_order(review_checkpoints)
    return EvidenceExportSummary(
        status=_str_or_none(legacy_summary.get("status")),
        trace_id=_str_or_none(legacy_summary.get("trace_id")),
        steps_count=_int_or_default(legacy_summary.get("steps_count")),
        completed_steps=_int_or_default(legacy_summary.get("completed_steps")),
        failed_steps=_int_or_default(legacy_summary.get("failed_steps")),
        attempts_count=_int_or_default(legacy_summary.get("attempts_count")),
        artifacts_count=_int_or_default(legacy_summary.get("artifacts_count")),
        duration_ms=_int_or_none(legacy_summary.get("duration_ms")),
        models_used=_str_list(legacy_summary.get("models_used")),
        review_checkpoints=_review_checkpoint_summary(
            legacy_summary.get("review_checkpoints")
        ),
        final_output=_final_output_summary(legacy_summary.get("final_output")),
        step_overview=[
            _step_overview_item(item, review_events_by_step_order)
            for item in _mapping_list(legacy_summary.get("step_overview"))
            if _int_or_none(item.get("step_order")) is not None
        ],
    )


def _step_overview_item(
    item: Mapping[str, object],
    review_events_by_step_order: Mapping[int, list[EvidenceStepReviewEvent]],
) -> EvidenceStepOverview:
    step_order = _int_or_default(item.get("step_order"))
    events = review_events_by_step_order.get(step_order, [])
    return EvidenceStepOverview(
        step_order=step_order,
        step_id=_str_or_none(item.get("step_id")),
        user_description=_str_or_none(item.get("user_description")),
        status=_str_or_none(item.get("status")),
        attempts_count=_int_or_default(item.get("attempts_count")),
        retries=_int_or_default(item.get("retries")),
        duration_ms=_int_or_none(item.get("duration_ms")),
        models_used=_str_list(item.get("models_used")),
        artifact_names=_str_list(item.get("artifact_names")),
        result_output_kind=_output_kind_or_none(item.get("result_output_kind")),
        output_summary=_payload_preview(item.get("output_summary")),
        configured_input_type=_str_or_none(item.get("configured_input_type")),
        configured_output_type=_str_or_none(item.get("configured_output_type")),
        review_impact=_review_impact(events),
    )


def _review_events_by_step_order(
    checkpoints: Sequence[Mapping[str, object]],
) -> dict[int, list[EvidenceStepReviewEvent]]:
    event_rows_by_step_order: dict[
        int, list[tuple[tuple[int, int, str, str], EvidenceStepReviewEvent]]
    ] = {}
    for checkpoint in checkpoints:
        step_order = _int_or_none(checkpoint.get("step_order"))
        event = _review_event(checkpoint)
        if step_order is None or event is None:
            continue
        created_at = _str_or_none(checkpoint.get("created_at")) or ""
        sort_key = (
            event.attempt_no,
            event.revision,
            created_at,
            event.checkpoint_id,
        )
        event_rows_by_step_order.setdefault(step_order, []).append((sort_key, event))

    return {
        step_order: [event for _, event in sorted(event_rows)]
        for step_order, event_rows in event_rows_by_step_order.items()
    }


def _review_event(
    checkpoint: Mapping[str, object],
) -> EvidenceStepReviewEvent | None:
    checkpoint_id = _str_or_none(checkpoint.get("id"))
    state = _checkpoint_state(checkpoint.get("state"))
    attempt_no = _int_or_none(checkpoint.get("attempt_no"))
    revision = _int_or_none(checkpoint.get("revision"))
    if checkpoint_id is None or state is None or attempt_no is None or revision is None:
        return None
    return EvidenceStepReviewEvent(
        checkpoint_id=checkpoint_id,
        state=state,
        decision=_review_decision(checkpoint.get("decision")),
        edited=state == FlowRunReviewCheckpointState.EDITED
        or checkpoint.get("edited_at") is not None,
        resumed=state == FlowRunReviewCheckpointState.RESUMED
        or checkpoint.get("resumed_at") is not None,
        attempt_no=attempt_no,
        revision=revision,
        output_changed=_output_changed(checkpoint),
    )


def _review_impact(
    events: list[EvidenceStepReviewEvent],
) -> EvidenceStepReviewImpact:
    return EvidenceStepReviewImpact(
        checkpoint_count=len(events),
        any_edited=any(event.edited for event in events),
        any_resumed=any(event.resumed for event in events),
        any_output_changed=any(event.output_changed is True for event in events),
        last_event=events[-1] if events else None,
        events=events,
    )


def _review_checkpoint_summary(value: object) -> EvidenceReviewCheckpointSummary:
    if _is_mapping(value):
        return EvidenceReviewCheckpointSummary.model_validate(value)
    return EvidenceReviewCheckpointSummary(
        count=0,
        by_state={state: 0 for state in FlowRunReviewCheckpointState},
        any_edited=False,
        any_resumed=False,
        active_checkpoint_id=None,
        active_checkpoint_conflict=False,
    )


def _final_output_summary(value: object) -> EvidenceFinalOutputSummary:
    empty_mapping: Mapping[str, object] = {}
    mapping = value if _is_mapping(value) else empty_mapping
    return EvidenceFinalOutputSummary(
        kind=_output_kind_or_default(mapping.get("kind")),
        text_present=_bool(mapping.get("text_present")),
        text_preview=_payload_preview(mapping.get("text_preview")),
        structured_present=_bool(mapping.get("structured_present")),
        artifact_count=_int_or_default(mapping.get("artifact_count")),
        artifact_names=_str_list(mapping.get("artifact_names")),
    )


def _output_changed(checkpoint: Mapping[str, object]) -> bool | None:
    if (
        "original_payload_json" not in checkpoint
        or "current_payload_json" not in checkpoint
    ):
        return None
    original_payload = checkpoint["original_payload_json"]
    current_payload = checkpoint["current_payload_json"]
    if original_payload is None or current_payload is None:
        return None
    return original_payload != current_payload


def _checkpoint_state(value: object) -> FlowRunReviewCheckpointState | None:
    if not isinstance(value, str):
        return None
    try:
        return FlowRunReviewCheckpointState(value)
    except ValueError:
        return None


def _review_decision(value: object) -> EvidenceReviewDecision | None:
    match value:
        case "approved":
            return "approved"
        case "rejected":
            return "rejected"
        case "cancelled":
            return "cancelled"
        case _:
            return None


def _output_kind_or_default(value: object) -> EvidenceOutputKind:
    return _output_kind_or_none(value) or "empty"


def _output_kind_or_none(value: object) -> EvidenceOutputKind | None:
    match value:
        case "empty":
            return "empty"
        case "text":
            return "text"
        case "structured":
            return "structured"
        case "artifact":
            return "artifact"
        case "mixed":
            return "mixed"
        case _:
            return None


def _payload_preview(value: object) -> PayloadPreview | None:
    if not _is_mapping(value):
        return None
    return PayloadPreview.model_validate(value)


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _int_or_default(value: object) -> int:
    return _int_or_none(value) or 0


def _bool(value: object) -> bool:
    return value is True


def _str_list(value: object) -> list[str]:
    if not _is_sequence(value):
        return []
    return [item for item in value if isinstance(item, str)]


def _mapping_list(value: object) -> list[Mapping[str, object]]:
    if not _is_sequence(value):
        return []
    return [item for item in value if _is_mapping(item)]


def _is_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _is_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(
        value, str | bytes | bytearray
    )
