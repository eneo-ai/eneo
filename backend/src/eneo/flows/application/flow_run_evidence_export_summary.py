from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.application.flow_run_evidence_export_manifest import (
    EvidenceArtifactManifestItem,
    EvidenceReviewCheckpointSummary,
)
from eneo.flows.enums import FlowRunReviewCheckpointState
from eneo.flows.flow_run_provenance import PayloadPreview
from eneo.json_types import JsonObject, JsonValue

EvidenceOutputKind: TypeAlias = Literal[
    "empty", "text", "structured", "artifact", "mixed"
]
EvidenceReviewDecision: TypeAlias = Literal["approved", "rejected", "cancelled"]


class EvidenceRagSourceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str | None = None
    display_name: str | None = None
    source_title_raw: str | None = None
    source_display_name: str | None = None
    source_url: str | None = None
    source_kind: str | None = None
    source_container_kind: str | None = None
    source_container_name: str | None = None
    source_container_name_raw: str | None = None
    source_container_display_name: str | None = None
    source_container_label: str | None = None
    source_container_id: str | None = None
    usage_state: str | None = None


class EvidenceRerunLineageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations_count: int
    queued_operations_count: int
    running_operations_count: int
    completed_operations_count: int
    failed_operations_count: int
    cancelled_operations_count: int
    active_operations_count: int
    terminal_operations_count: int
    invalidated_steps_count: int
    completed_replacement_count: int


class EvidenceStepInputLineageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_source: JsonValue
    used_question_binding: JsonValue
    uses_runtime_input: bool
    runtime_input_format: JsonValue
    runtime_file_count: int
    runtime_file_ids: list[str]
    runtime_file_names: list[str]
    runtime_file_checksums: list[str]
    runtime_files: list[JsonObject]
    question_binding_references_runtime_input: bool
    question_binding_expressions: list[str]
    upstream_step_orders: list[int]
    upstream_step_labels: list[str]


class EvidenceStepKnowledgeRetrievalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: JsonValue
    attempted: JsonValue
    retrieval_duration_ms: JsonValue
    unique_sources: JsonValue
    references_truncated: JsonValue
    reference_metadata_status: JsonValue
    retrieval_error_type: JsonValue = None
    error_code: JsonValue = None
    source_names: JsonValue
    source_display_names: JsonValue
    prompt_context: JsonObject | None


class EvidenceFinalOutputSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EvidenceOutputKind
    text_present: bool
    text_preview: PayloadPreview | None = None
    structured_present: bool
    artifact_count: int
    artifact_names: list[str]
    artifact_details: list[EvidenceArtifactManifestItem]


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
    knowledge_sources_count: int
    knowledge_usage_state: str | None = None
    knowledge_retrieval: EvidenceStepKnowledgeRetrievalSummary | None = None
    citations: JsonObject
    artifact_names: list[str]
    artifact_details: list[EvidenceArtifactManifestItem]
    result_output_kind: EvidenceOutputKind | None = None
    output_summary: PayloadPreview | None = None
    input_lineage: EvidenceStepInputLineageSummary
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
    artifact_names: list[str]
    artifact_details: list[EvidenceArtifactManifestItem]
    duration_ms: int | None = None
    models_used: list[str]
    rag_sources_count: int
    rag_source_names: list[str]
    rag_source_display_names: list[str]
    rag_sources: list[EvidenceRagSourceSummary]
    rag_usage_tracking: JsonObject
    citations: JsonObject
    rerun_lineage: EvidenceRerunLineageSummary
    review_checkpoints: EvidenceReviewCheckpointSummary
    final_output: EvidenceFinalOutputSummary
    step_overview: list[EvidenceStepOverview]


def build_evidence_step_review_impacts_by_step_order(
    review_checkpoints: Sequence[Mapping[str, object]],
) -> dict[int, EvidenceStepReviewImpact]:
    return {
        step_order: _review_impact(events)
        for step_order, events in _review_events_by_step_order(
            review_checkpoints
        ).items()
    }


def empty_evidence_step_review_impact() -> EvidenceStepReviewImpact:
    return _review_impact([])


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


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
