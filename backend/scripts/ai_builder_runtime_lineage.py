"""Runtime input lineage: which content a run's input step consumed.

The run's evidence is parsed once, at this boundary, into strict typed records
(`parse_runtime_input_evidence`). A record that does not parse is invalid
evidence, named after the section that failed. The lineage policy
(`runtime_lineage`) decides only on the parsed model:

- `not_reached` needs affirmative noncompletion: no run at all, a recorded
  input-step result that did not complete, or a complete read that holds no
  result for the step. Any completed record of the uploads being consumed
  contradicts all three.
- a completed input step must prove tracked lineage for every uploaded file.

Every reader accepts a stored claim only through `RuntimeLineage.accepts`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, TypeVar, cast
from uuid import UUID

from ai_builder_receipt import is_sha256
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

from eneo.flows.ai_builder.ai_builder_flow_review_sample import (
    reader_omitted_step_results,
)
from eneo.flows.application.flow_run_evidence import RunViewEvidenceOmission
from eneo.flows.enums import FlowStepAttemptStatus, FlowStepResultStatus
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputLineage,
    FlowResolvedInputLineageTracked,
    FlowResolvedInputRuntimeFileSource,
)


class RuntimeLineageStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    COMPLETE = "complete"
    NOT_REACHED = "not_reached"
    # Invalid evidence: the parse failed in this section.
    RUNTIME_EVIDENCE_UNRECORDED = "runtime_evidence_unrecorded"
    RUNTIME_EVIDENCE_MALFORMED = "runtime_evidence_malformed"
    INPUT_STEP_INVALID = "input_step_invalid"
    UPLOADED_FILES_INVALID = "uploaded_files_invalid"
    STEP_RESULTS_INVALID = "step_results_invalid"
    STEP_ATTEMPTS_INVALID = "step_attempts_invalid"
    READER_METADATA_INVALID = "reader_metadata_invalid"
    # Invalid evidence: parsed, but it does not prove what the policy needs.
    CURRENT_STEP_CONTRADICTORY = "current_step_contradictory"
    CURRENT_STEP_UNREAD = "current_step_unread"
    CURRENT_STEP_INVALID = "current_step_invalid"
    CURRENT_ATTEMPT_INVALID = "current_attempt_invalid"
    CURRENT_LINEAGE_NOT_TRACKED = "current_lineage_not_tracked"
    CURRENT_LINEAGE_INVALID = "current_lineage_invalid"
    CURRENT_LINEAGE_INCOMPLETE = "current_lineage_incomplete"


@dataclass(frozen=True, slots=True)
class RuntimeLineage:
    status: RuntimeLineageStatus
    sha256s: tuple[str | None, ...]

    @property
    def holds(self) -> bool:
        """Positive acceptance: the only statuses a valid observation carries,
        each with exactly the digests it implies."""
        if self.status is RuntimeLineageStatus.NOT_REQUIRED:
            return self.sha256s == ()
        if self.status is RuntimeLineageStatus.COMPLETE:
            return bool(self.sha256s) and all(map(is_sha256, self.sha256s))
        if self.status is RuntimeLineageStatus.NOT_REACHED:
            return bool(self.sha256s) and all(v is None for v in self.sha256s)
        return False

    def accepts(self, identity: Mapping[str, object]) -> bool:
        """Positive acceptance of a stored identity's runtime half: it claims
        exactly this lineage, and this lineage holds."""
        return (
            self.holds
            and identity.get("runtime_evidence_status") == self.status.value
            and identity.get("runtime_source_sha256s") == list(self.sha256s)
        )


_Row = TypeVar("_Row")


def _distinct(
    *fields: str,
) -> AfterValidator:
    def check(rows: tuple[_Row, ...]) -> tuple[_Row, ...]:
        keys = [tuple(getattr(row, name) for name in fields) for row in rows]
        if len(set(keys)) != len(keys):
            raise ValueError(f"{'/'.join(fields)} must be distinct")
        return rows

    return AfterValidator(check)


_AttemptNo = Annotated[int, Field(ge=1)]


class _Strict(BaseModel):
    # Only the fields below are read; any other field never reaches the policy.
    model_config = ConfigDict(extra="ignore", frozen=True)


class _InputStep(_Strict):
    step_id: UUID


class _RunContract(_Strict):
    steps_requiring_input: Annotated[
        tuple[_InputStep, ...], Field(min_length=1, max_length=1)
    ]


class _UploadedFile(_Strict):
    id: UUID
    size: Annotated[int, Field(ge=0)]


class _StepResult(_Strict):
    step_id: UUID
    status: FlowStepResultStatus
    current_attempt_no: _AttemptNo | None
    runtime_input_file_ids: tuple[UUID, ...]


class _StepAttempt(_Strict):
    id: UUID
    step_id: UUID
    attempt_no: _AttemptNo
    status: FlowStepAttemptStatus
    resolved_input_lineage: FlowResolvedInputLineage


class _ReaderSummary(_Strict):
    omissions: tuple[RunViewEvidenceOmission, ...]


class _ReaderRun(_Strict):
    summary: _ReaderSummary


class _ReaderExport(_Strict):
    run: _ReaderRun


class RuntimeInputEvidence(_Strict):
    run_contract: _RunContract
    uploaded_files: Annotated[tuple[_UploadedFile, ...], _distinct("id")]
    step_results: Annotated[tuple[_StepResult, ...], _distinct("step_id")]
    step_attempts: Annotated[
        tuple[_StepAttempt, ...], _distinct("id"), _distinct("step_id", "attempt_no")
    ]
    debug_export: _ReaderExport | None


_SECTION_REASONS: Mapping[str, RuntimeLineageStatus] = {
    "run_contract": RuntimeLineageStatus.INPUT_STEP_INVALID,
    "uploaded_files": RuntimeLineageStatus.UPLOADED_FILES_INVALID,
    "step_results": RuntimeLineageStatus.STEP_RESULTS_INVALID,
    "step_attempts": RuntimeLineageStatus.STEP_ATTEMPTS_INVALID,
    "debug_export": RuntimeLineageStatus.READER_METADATA_INVALID,
}

_Model = TypeVar("_Model", bound=BaseModel)


def _strict_json(model: type[_Model], value: object) -> _Model:
    """Strict JSON-mode validation, nested product models included: ints
    exclude booleans and floats, enums and literals need their exact value; a
    valid UUID in any representation is normalized.
    Raises ValueError: content that is not JSON, or a ValidationError."""
    return model.model_validate_json(json.dumps(value, allow_nan=False), strict=True)


def parse_runtime_input_evidence(
    raw: object,
) -> RuntimeInputEvidence | RuntimeLineageStatus:
    if not isinstance(raw, Mapping):
        return RuntimeLineageStatus.RUNTIME_EVIDENCE_MALFORMED
    fields = cast(Mapping[str, object], raw)
    try:
        return _strict_json(
            RuntimeInputEvidence,
            {key: fields[key] for key in _SECTION_REASONS if key in fields},
        )
    except ValidationError as error:
        location = error.errors()[0]["loc"]
        return _SECTION_REASONS.get(
            str(location[0]) if location else "",
            RuntimeLineageStatus.RUNTIME_EVIDENCE_MALFORMED,
        )
    except (TypeError, ValueError):
        return RuntimeLineageStatus.RUNTIME_EVIDENCE_MALFORMED


def runtime_lineage(runtime_evidence: object, *, expected_count: int) -> RuntimeLineage:
    if expected_count == 0:
        return RuntimeLineage(RuntimeLineageStatus.NOT_REQUIRED, ())
    absent: tuple[None, ...] = (None,) * expected_count
    if runtime_evidence is None:
        # The harness executed nothing: no plan, a skipped run.
        return RuntimeLineage(RuntimeLineageStatus.NOT_REACHED, absent)
    evidence = parse_runtime_input_evidence(runtime_evidence)
    if isinstance(evidence, RuntimeLineageStatus):
        return RuntimeLineage(evidence, absent)
    judged = _judge(evidence, expected_count)
    if isinstance(judged, RuntimeLineageStatus):
        return RuntimeLineage(judged, absent)
    return RuntimeLineage(RuntimeLineageStatus.COMPLETE, judged)


def recorded_runtime_lineage(
    bundle: Mapping[str, object], *, expected_count: int
) -> RuntimeLineage:
    """The lineage a stored observation's own evidence proves. Every writer
    records the key; a bundle without it recorded nothing to prove."""
    if expected_count and "runtime_evidence" not in bundle:
        return RuntimeLineage(
            RuntimeLineageStatus.RUNTIME_EVIDENCE_UNRECORDED,
            (None,) * expected_count,
        )
    return runtime_lineage(
        bundle.get("runtime_evidence"), expected_count=expected_count
    )


def _consumed(
    evidence: RuntimeInputEvidence, step_id: UUID, uploaded_ids: tuple[UUID, ...]
) -> bool:
    """A completed record of the uploads being read: a completed attempt of the
    input step, a completed result that lists an upload, or a completed attempt
    with a runtime-file edge. Any of them contradicts noncompletion."""
    return any(
        result.status is FlowStepResultStatus.COMPLETED
        and not set(uploaded_ids).isdisjoint(result.runtime_input_file_ids)
        for result in evidence.step_results
    ) or any(
        attempt.status is FlowStepAttemptStatus.COMPLETED
        and (
            attempt.step_id == step_id
            or (
                isinstance(
                    attempt.resolved_input_lineage, FlowResolvedInputLineageTracked
                )
                and any(
                    isinstance(edge.source, FlowResolvedInputRuntimeFileSource)
                    for edge in attempt.resolved_input_lineage.edges
                )
            )
        )
        for attempt in evidence.step_attempts
    )


def _judge(
    evidence: RuntimeInputEvidence, expected_count: int
) -> RuntimeLineageStatus | tuple[str, ...]:
    step_id = evidence.run_contract.steps_requiring_input[0].step_id
    uploaded = evidence.uploaded_files
    if len(uploaded) != expected_count:
        return RuntimeLineageStatus.UPLOADED_FILES_INVALID
    uploaded_ids = tuple(file.id for file in uploaded)
    result = next((r for r in evidence.step_results if r.step_id == step_id), None)
    if result is None or result.status is not FlowStepResultStatus.COMPLETED:
        if _consumed(evidence, step_id, uploaded_ids):
            return RuntimeLineageStatus.CURRENT_STEP_CONTRADICTORY
        if result is None and (
            evidence.debug_export is None
            # The product reader owns what an omission means; it reads JSON.
            or reader_omitted_step_results(
                evidence.debug_export.model_dump(mode="json")
            )
        ):
            return RuntimeLineageStatus.CURRENT_STEP_UNREAD
        return RuntimeLineageStatus.NOT_REACHED

    if (
        result.current_attempt_no is None
        or result.runtime_input_file_ids != uploaded_ids
    ):
        return RuntimeLineageStatus.CURRENT_STEP_INVALID
    current = next(
        (
            a
            for a in evidence.step_attempts
            if a.step_id == step_id and a.attempt_no == result.current_attempt_no
        ),
        None,
    )
    if current is None or current.status is not FlowStepAttemptStatus.COMPLETED:
        return RuntimeLineageStatus.CURRENT_ATTEMPT_INVALID
    lineage = current.resolved_input_lineage
    if not isinstance(lineage, FlowResolvedInputLineageTracked):
        return RuntimeLineageStatus.CURRENT_LINEAGE_NOT_TRACKED

    sizes = {file.id: file.size for file in uploaded}
    positions = {file_id: position for position, file_id in enumerate(uploaded_ids)}
    checksums: dict[UUID, str] = {}
    placements: list[tuple[int, int, str]] = []
    for edge in lineage.edges:
        source = edge.source
        if not isinstance(source, FlowResolvedInputRuntimeFileSource):
            continue
        if (
            source.file_id not in sizes
            or source.byte_size != sizes[source.file_id]
            or source.file_id in checksums
            or not is_sha256(source.checksum)
        ):
            return RuntimeLineageStatus.CURRENT_LINEAGE_INVALID
        checksums[source.file_id] = source.checksum
        placements.append(
            (positions[source.file_id], source.input_file_ordinal, edge.binding_ref)
        )
    if set(checksums) != set(sizes):
        return RuntimeLineageStatus.CURRENT_LINEAGE_INCOMPLETE
    # Ordinals are run-global, or each source ran alone as its step's file 0.
    global_ordinals = all(position == ordinal for position, ordinal, _ in placements)
    per_source_ordinals = all(
        ordinal == 0 and binding_ref == "runtime_files[0]"
        for _, ordinal, binding_ref in placements
    )
    if not global_ordinals and not per_source_ordinals:
        return RuntimeLineageStatus.CURRENT_LINEAGE_INVALID
    return tuple(checksums[file_id] for file_id in uploaded_ids)
