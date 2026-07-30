from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from datetime import datetime
from typing import Annotated, Any, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRun,
    FlowRunRerunInvalidatedStep,
    FlowRunRerunOperation,
    FlowRunTokenUsage,
    FlowStepAttempt,
    FlowStepResult,
    FlowVersion,
)
from eneo.flows.domain.rag_evidence import (
    MAPPED_CALL_COLLECTION_KEYS,
    PassageDisclosure,
    RetrievedKnowledgeEvidence,
    apply_passage_disclosure,
    disclosed_passage_bytes_in,
    omitted_view_totals,
    recompute_mapped_aggregates,
)
from eneo.flows.flow_run_provenance import normalize_rag_payload
from eneo.flows.flow_run_step_result_file import FlowRunStepResultFile

DEBUG_EXPORT_SCHEMA_VERSION = "eneo.flow.debug-export.v2"

EvidenceSectionIdentifier: TypeAlias = Literal[
    "run",
    "definition_snapshot",
    "step_results",
    "step_attempts",
    "result_files",
    "runtime_input_files",
    "rerun_operations",
    "rerun_invalidated_steps",
    "review_checkpoints",
    "webhook_deliveries",
    "provider_calls",
    "whole_bundle",
]
EvidenceLimitIdentifier: TypeAlias = Literal[
    "corrupt_passage_evidence",
    "recorded_passage_bytes",
    "stored_provenance_bytes",
    "section_rows",
    "aggregate_stored_json_bytes",
    "aggregate_logical_json_bytes",
    "provider_call_events",
]
EvidenceOmissionReason: TypeAlias = Literal[
    "row_limit",
    "logical_bytes",
    "parent_section_omitted",
]


class RunViewEvidenceRowOmission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: Literal["row_limit"] = "row_limit"
    section: EvidenceSectionIdentifier
    rows_omitted: int = Field(ge=1)
    count_truncated: bool = False


class RunViewEvidenceLogicalByteOmission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: Literal["logical_bytes"] = "logical_bytes"
    section: EvidenceSectionIdentifier
    rows_omitted: int = Field(ge=1)
    count_truncated: bool = False


class RunViewEvidenceParentOmission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: Literal["parent_section_omitted"] = "parent_section_omitted"
    section: EvidenceSectionIdentifier
    rows_omitted: int = Field(ge=1)
    count_truncated: bool = False


RunViewEvidenceOmission: TypeAlias = Annotated[
    RunViewEvidenceRowOmission
    | RunViewEvidenceLogicalByteOmission
    | RunViewEvidenceParentOmission,
    Field(discriminator="reason"),
]


def _empty_run_view_evidence_omissions() -> list[RunViewEvidenceOmission]:
    return []


class DebugAttemptProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_no: int
    status: str | None
    duration_ms: int | None
    error_code: str | None
    requested_model: str | None
    response_model: str | None
    provider: str | None
    finish_reason: str | None
    provider_response_id: str | None
    num_tokens_input: int | None
    num_tokens_output: int | None


class DebugStepProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: Any
    step_order: Any
    assistant_id: Any
    io_types: dict[str, Any]
    input: dict[str, Any]
    output: dict[str, Any]
    rag: dict[str, Any] | None = None
    attempts: list[DebugAttemptProjection]


class DebugRunSummaryProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps_count: int
    completed_steps: int
    failed_steps: int
    attempts_count: int
    artifacts_count: int
    duration_ms: int | None
    models_used: list[str]
    token_usage: FlowRunTokenUsage | None = None
    knowledge_evidence_view: RunViewPassageOmission | None = None
    omissions: list[RunViewEvidenceOmission] = Field(
        default_factory=_empty_run_view_evidence_omissions
    )


def build_debug_export(
    *,
    run: FlowRun,
    version: FlowVersion,
    step_results: list[FlowStepResult] | None = None,
    step_attempts: list[FlowStepAttempt] | None = None,
    result_files: list[FlowRunStepResultFile] | None = None,
    rerun_operations: list[FlowRunRerunOperation] | None = None,
    rerun_invalidated_steps: list[FlowRunRerunInvalidatedStep] | None = None,
    token_usage: FlowRunTokenUsage | None = None,
    knowledge_evidence_view: RunViewPassageOmission | None = None,
    omissions: Sequence[RunViewEvidenceOmission] = (),
) -> dict[str, Any]:
    definition_snapshot = version.definition_json
    evidence_generated_at = _latest_evidence_timestamp(
        run=run,
        version=version,
        step_results=step_results or [],
        step_attempts=step_attempts or [],
        rerun_operations=rerun_operations or [],
        rerun_invalidated_steps=rerun_invalidated_steps or [],
    )
    rag_by_step_order = _current_attempt_rag_by_step_order(
        step_results=step_results or [],
        step_attempts=step_attempts or [],
    )
    attempts_by_step_order: dict[int, list[DebugAttemptProjection]] = {}
    for attempt in step_attempts or []:
        normalized_step_order = parse_step_order(attempt.step_order)
        if normalized_step_order is None:
            continue
        attempts_by_step_order.setdefault(normalized_step_order, []).append(
            normalize_debug_attempt(attempt)
        )

    raw_steps = definition_snapshot.get("steps")
    normalized_steps: list[dict[str, Any]] = []
    if isinstance(raw_steps, list):
        for raw_step in cast(list[object], raw_steps):
            if isinstance(raw_step, dict):
                raw_step_dict = cast(FlowPersistedJsonObject, raw_step)
                parsed_step_order = parse_step_order(
                    raw_step_dict.get("step_order"), default=0
                )
                step_order = parsed_step_order if parsed_step_order is not None else 0
                normalized_steps.append(
                    normalize_debug_step(
                        raw_step_dict,
                        rag_metadata=rag_by_step_order.get(step_order),
                        attempts=attempts_by_step_order.get(step_order, []),
                    )
                )
    summary = DebugRunSummaryProjection(
        steps_count=len(normalized_steps),
        completed_steps=sum(
            1
            for result in step_results or []
            if _normalize_status(result.status) == "completed"
        ),
        failed_steps=sum(
            1
            for result in step_results or []
            if _normalize_status(result.status) == "failed"
        ),
        attempts_count=sum(
            len(attempts) for attempts in attempts_by_step_order.values()
        ),
        artifacts_count=len({str(item.file_id) for item in result_files or []}),
        duration_ms=_calculate_duration_ms(run.created_at, run.updated_at),
        models_used=_collect_models_used(step_attempts or []),
        token_usage=token_usage,
        knowledge_evidence_view=knowledge_evidence_view,
        omissions=list(omissions),
    )

    return {
        "schema_version": DEBUG_EXPORT_SCHEMA_VERSION,
        "generated_at": evidence_generated_at.isoformat(),
        "run": {
            "run_id": str(run.id),
            "flow_id": str(run.flow_id),
            "flow_version": run.flow_version,
            "trace_id": str(run.trace_id),
            "status": run.status.value,
            "summary": summary.model_dump(mode="json"),
        },
        "definition": {
            "flow_id": str(version.flow_id),
            "version": version.version,
            "checksum": version.definition_checksum,
            "steps_count": len(normalized_steps),
        },
        "definition_snapshot": definition_snapshot,
        "steps": normalized_steps,
        "security": {
            "redaction_applied": False,
            "classification_field": "output_classification_override",
        },
    }


def _latest_evidence_timestamp(
    *,
    run: FlowRun,
    version: FlowVersion,
    step_results: list[FlowStepResult],
    step_attempts: list[FlowStepAttempt],
    rerun_operations: list[FlowRunRerunOperation],
    rerun_invalidated_steps: list[FlowRunRerunInvalidatedStep],
) -> datetime:
    timestamps = [run.updated_at, version.updated_at]
    timestamps.extend(result.updated_at for result in step_results)
    timestamps.extend(attempt.updated_at for attempt in step_attempts)
    timestamps.extend(operation.updated_at for operation in rerun_operations)
    timestamps.extend(step.updated_at for step in rerun_invalidated_steps)
    return max(timestamps)


def parse_step_order(value: Any, *, default: int | None = None) -> int | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return default
        try:
            return int(stripped)
        except ValueError:
            return default
    return default


def normalize_debug_step(
    step: dict[str, Any],
    *,
    rag_metadata: dict[str, Any] | None = None,
    attempts: list[DebugAttemptProjection] | None = None,
) -> dict[str, Any]:
    input_type = step.get("input_type")
    output_type = step.get("output_type")
    return DebugStepProjection(
        step_id=step.get("step_id"),
        step_order=step.get("step_order"),
        assistant_id=step.get("assistant_id"),
        io_types={
            "input": input_type,
            "output": output_type,
        },
        input={
            "source": step.get("input_source"),
            "type": input_type,
            "contract": step.get("input_contract"),
            "bindings": step.get("input_bindings"),
            "config": step.get("input_config"),
        },
        output={
            "mode": step.get("output_mode"),
            "type": output_type,
            "contract": step.get("output_contract"),
            "classification": step.get("output_classification_override"),
            "config": step.get("output_config"),
        },
        rag=_normalize_debug_rag(rag_metadata),
        attempts=list(attempts or []),
    ).model_dump(mode="json")


def normalize_debug_attempt(attempt: FlowStepAttempt) -> DebugAttemptProjection:
    started_at = attempt.started_at
    finished_at = attempt.finished_at
    duration_ms = None
    attempt_no = attempt.attempt_no
    if finished_at is not None:
        duration_ms = max(
            0,
            int((finished_at - started_at).total_seconds() * 1000),
        )
    return DebugAttemptProjection(
        attempt_no=attempt_no,
        status=_normalize_status(attempt.status),
        duration_ms=duration_ms,
        error_code=attempt.error_code,
        requested_model=attempt.requested_model,
        response_model=attempt.response_model,
        provider=attempt.provider,
        finish_reason=attempt.finish_reason,
        provider_response_id=attempt.provider_response_id,
        num_tokens_input=attempt.num_tokens_input,
        num_tokens_output=attempt.num_tokens_output,
    )


def _normalize_status(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    status_value = getattr(value, "value", None)
    return status_value if isinstance(status_value, str) else None


def _normalize_debug_rag(rag_metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    return normalize_rag_payload(rag_metadata)


def _calculate_duration_ms(started_at: Any, finished_at: Any) -> int | None:
    if not isinstance(started_at, datetime) or not isinstance(finished_at, datetime):
        return None
    return max(0, int((finished_at - started_at).total_seconds() * 1000))


def _collect_models_used(step_attempts: list[FlowStepAttempt]) -> list[str]:
    models: list[str] = []
    for attempt in step_attempts:
        candidate = attempt.response_model or attempt.requested_model
        if isinstance(candidate, str) and candidate.strip():
            models.append(candidate.strip())
    return list(dict.fromkeys(models))


def withhold_attempt_passages(
    step_attempts: Sequence[FlowStepAttempt],
    *,
    disclosure: PassageDisclosure,
) -> list[FlowStepAttempt]:
    """Apply a passage-disclosure decision to attempt provenance.

    Attempt provenance is the only owner of verbatim passages, so this is the
    single place every evidence surface — ordinary view, redacted export and raw
    export — passes through.
    """
    attempts = list(step_attempts)
    if disclosure == "text_disclosed":
        return attempts
    masked: list[FlowStepAttempt] = []
    for attempt in attempts:
        provenance = attempt.provenance_json
        if not isinstance(provenance, dict):
            masked.append(attempt)
            continue
        rag = provenance.get("rag")
        if not isinstance(rag, dict):
            masked.append(attempt)
            continue
        next_provenance = dict(provenance)
        next_provenance["rag"] = apply_passage_disclosure(
            deepcopy(cast(dict[str, Any], rag)),
            disclosure=disclosure,
        )
        masked.append(attempt.model_copy(update={"provenance_json": next_provenance}))
    return masked


def _current_attempt_rag_by_step_order(
    *,
    step_results: Sequence[FlowStepResult],
    step_attempts: Sequence[FlowStepAttempt],
) -> dict[int, dict[str, Any]]:
    """Retrieval evidence for each step's *current* attempt.

    Attempt provenance is the single owner of retrieval evidence, but a step can
    have several attempts. Showing the newest attempt that happens to contain
    RAG would present an earlier attempt's sources as the step's current ones —
    for example when a rerun fails before retrieval. The step result names its
    current attempt, so that is the attempt the step view reports. Run-wide
    history still aggregates every attempt explicitly.
    """
    current_attempt_by_step_order: dict[int, int] = {}
    for result in step_results:
        normalized_step_order = parse_step_order(result.step_order)
        if normalized_step_order is None or result.current_attempt_no is None:
            continue
        current_attempt_by_step_order[normalized_step_order] = result.current_attempt_no

    rag_by_step_order: dict[int, dict[str, Any]] = {}
    for attempt in sorted(
        step_attempts,
        key=lambda item: (parse_step_order(item.step_order) or 0, item.attempt_no),
    ):
        normalized_step_order = parse_step_order(attempt.step_order)
        if normalized_step_order is None:
            continue
        current_attempt_no = current_attempt_by_step_order.get(normalized_step_order)
        if current_attempt_no is None or attempt.attempt_no != current_attempt_no:
            # No identified current attempt means the step's current evidence
            # is unknown; showing an older attempt's sources as current would
            # misattribute them.
            continue
        provenance = attempt.provenance_json
        if not isinstance(provenance, dict):
            continue
        rag_metadata = provenance.get("rag")
        if not isinstance(rag_metadata, dict):
            continue
        rag_by_step_order[normalized_step_order] = cast(dict[str, Any], rag_metadata)
    return rag_by_step_order


EvidenceExportDetail = Literal["raw", "redacted"]


class RunViewPassageOmission(BaseModel):
    """Passage text an interactive run view left out of its response.

    Two stages can narrow the view, and each reports its effects. The bounded
    repository read admits current attempts first and recent history next under
    row and byte budgets. Every excluded row is reported in
    ``attempts_not_loaded``; ``corrupt_passage_aggregates`` identifies the
    subset excluded because its recorded passage-size aggregate is unreadable,
    and any excluded CURRENT attempt is named per step so its empty trace
    cannot be read as the step never having retrieved. When
    ``count_truncated`` is true, all three attempt-derived counts are lower
    bounds and the named step orders are the known subset from the bounded
    candidate window. The loaded evidence is then trimmed to the view byte
    budget — an output-size cap on the response.

    It never applies to an evidence export: an export returns the evidence that
    is actually retained, or fails, but never a quiet subset.
    """

    model_config = ConfigDict(extra="forbid")

    byte_budget: int
    returned_passage_bytes: int
    passages_omitted: int
    passage_bytes_omitted: int
    attempts_with_omitted_passages: int
    count_truncated: bool
    attempts_not_loaded: int = 0
    corrupt_passage_aggregates: int = 0
    current_attempts_not_loaded: int = 0
    current_step_orders_not_loaded: list[int] = []

    @property
    def omitted_any(self) -> bool:
        return self.passages_omitted > 0


def omit_passages_beyond_view_budget(
    step_attempts: Sequence[FlowStepAttempt],
    *,
    step_results: Sequence[FlowStepResult],
    byte_budget: int,
    count_truncated: bool,
    attempts_not_loaded: int = 0,
    corrupt_passage_aggregates: int = 0,
    current_attempts_not_loaded: int = 0,
    current_step_orders_not_loaded: tuple[int, ...] = (),
) -> tuple[list[FlowStepAttempt], RunViewPassageOmission]:
    """Trim passage text from an interactive run view's response.

    A run's attempt count is unbounded, so a per-attempt policy alone lets a
    heavily rerun flow return a very large view. Each step's current attempt is
    admitted first because that is what the step view renders; superseded
    attempts lose their passage text first. Sources, titles and counts always
    survive, and the omission is reported as counts so the view can say what it
    left out.

    The evidence itself is untouched on disk: this shapes one response.
    """
    attempts = list(step_attempts)
    current_attempt_by_step_order: dict[int, int] = {}
    for result in step_results:
        normalized_step_order = parse_step_order(result.step_order)
        if normalized_step_order is None or result.current_attempt_no is None:
            continue
        current_attempt_by_step_order[normalized_step_order] = result.current_attempt_no

    def admission_rank(item: tuple[int, FlowStepAttempt]) -> tuple[int, int, int]:
        index, attempt = item
        step_order = parse_step_order(attempt.step_order) or 0
        is_current = current_attempt_by_step_order.get(step_order) == attempt.attempt_no
        return (0 if is_current else 1, step_order, index)

    remaining = max(0, byte_budget)
    returned_bytes = 0
    passages_omitted = 0
    bytes_omitted = 0
    attempts_with_omitted_passages = 0
    bounded_by_index: dict[int, FlowStepAttempt] = {}

    for index, attempt in sorted(enumerate(attempts), key=admission_rank):
        provenance = attempt.provenance_json
        if not isinstance(provenance, dict):
            continue
        rag = provenance.get("rag")
        if not isinstance(rag, dict):
            continue
        next_rag = deepcopy(cast(dict[str, Any], rag))
        omitted_before = omitted_view_totals(next_rag)
        for payload in _mutable_rag_payloads(next_rag):
            evidence = RetrievedKnowledgeEvidence.from_payload(payload)
            if not evidence.sources:
                continue
            bounded = evidence.release_passages_beyond(remaining, budget="view")
            remaining = max(0, remaining - bounded.disclosed_passage_bytes)
            returned_bytes += bounded.disclosed_passage_bytes
            bounded.write_into(payload)
        recompute_mapped_aggregates(next_rag)
        omitted_after = omitted_view_totals(next_rag)
        omitted_passages = omitted_after[0] - omitted_before[0]
        if omitted_passages > 0:
            passages_omitted += omitted_passages
            bytes_omitted += omitted_after[1] - omitted_before[1]
            attempts_with_omitted_passages += 1
        next_provenance = dict(provenance)
        next_provenance["rag"] = next_rag
        bounded_by_index[index] = attempt.model_copy(
            update={"provenance_json": next_provenance}
        )

    return (
        [
            bounded_by_index.get(index, attempt)
            for index, attempt in enumerate(attempts)
        ],
        RunViewPassageOmission(
            byte_budget=byte_budget,
            returned_passage_bytes=returned_bytes,
            passages_omitted=passages_omitted,
            passage_bytes_omitted=bytes_omitted,
            attempts_with_omitted_passages=attempts_with_omitted_passages,
            count_truncated=count_truncated,
            attempts_not_loaded=attempts_not_loaded,
            corrupt_passage_aggregates=corrupt_passage_aggregates,
            current_attempts_not_loaded=current_attempts_not_loaded,
            current_step_orders_not_loaded=list(current_step_orders_not_loaded),
        ),
    )


def exported_passage_bytes(
    step_attempts: Sequence[FlowStepAttempt],
    *,
    detail: EvidenceExportDetail,
) -> int:
    """Passage bytes an export would carry, before deciding whether it may.

    A redacted export withholds some text, so it is measured by what it will
    actually contain. A raw export returns everything retained and is measured
    that way.
    """
    total = 0
    for attempt in step_attempts:
        provenance = attempt.provenance_json
        if not isinstance(provenance, dict):
            continue
        rag = provenance.get("rag")
        if not isinstance(rag, dict):
            continue
        typed_rag = cast(dict[str, Any], rag)
        if detail == "raw":
            for payload in _mutable_rag_payloads(typed_rag):
                total += RetrievedKnowledgeEvidence.from_payload(
                    payload
                ).recorded_passage_bytes
        else:
            total += disclosed_passage_bytes_in(typed_rag)
    return total


def _mutable_rag_payloads(rag_payload: dict[str, Any]) -> list[dict[str, Any]]:
    payloads = [rag_payload]
    for collection_key in MAPPED_CALL_COLLECTION_KEYS:
        calls = rag_payload.get(collection_key)
        if not isinstance(calls, list):
            continue
        for call in cast(list[object], calls):
            if isinstance(call, dict):
                payloads.extend(_mutable_rag_payloads(cast(dict[str, Any], call)))
    return payloads
