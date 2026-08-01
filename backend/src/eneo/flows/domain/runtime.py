from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eneo.flows.domain.flow import FlowStepResult, FlowStepRetrievalPolicy
from eneo.flows.domain.flow_step_attempt_input import (
    FlowStepAttemptMappedAdmission,
    FlowStepAttemptStart,
)
from eneo.flows.domain.step_output import (
    OUTPUT_TEXT_OVERFLOW_KEY,
    FileBackedStepText,
    StepOutputMetadataError,
    interpret_step_text,
)
from eneo.flows.enums import flow_output_mode_uses_completion_model
from eneo.flows.flow_review_policy import FlowStepReviewPolicy
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputEdge,
)

if TYPE_CHECKING:
    from eneo.files.file_models import File
    from eneo.spaces.space import Space


def _empty_step_diagnostics() -> list["StepDiagnostic"]:
    return []


def _empty_step_names_by_order() -> dict[int, str]:
    return {}


def _empty_step_ref_mapping() -> dict[str, int]:
    return {}


def _empty_attempt_start_by_step() -> dict[UUID, FlowStepAttemptStart]:
    return {}


def _empty_space_cache() -> dict[UUID, Space]:
    return {}


def _empty_mapped_admission_by_step() -> dict[UUID, FlowStepAttemptMappedAdmission]:
    return {}


def _empty_activated_attempts() -> set[tuple[UUID, int]]:
    return set()


@dataclass(frozen=True)
class RuntimeStep:
    step_id: UUID
    step_order: int
    assistant_id: UUID
    user_description: str | None
    input_source: str
    input_bindings: dict[str, Any] | None
    input_config: dict[str, Any] | None
    output_mode: str
    output_config: dict[str, Any] | None
    output_classification_override: int | None = None
    output_type: str = "text"
    output_contract: dict[str, Any] | None = None
    input_type: str = "text"
    input_contract: dict[str, Any] | None = None
    plan_step_ref: str | None = None
    existing_step_ref: str | None = None
    assistant_snapshot: dict[str, Any] | None = None
    review_policy: FlowStepReviewPolicy | None = None
    retrieval_policy: FlowStepRetrievalPolicy | None = None
    timeout_seconds: int | None = None

    @property
    def may_call_completion_provider(self) -> bool:
        return flow_output_mode_uses_completion_model(self.output_mode)


@dataclass(frozen=True)
class StepDiagnostic:
    code: str
    message: str
    severity: str = "warning"


@dataclass
class StepExecutionOutput:
    input_text: str
    source_text: str
    input_source: str
    used_question_binding: bool
    full_text: str
    persisted_text: str
    generated_file_ids: list[UUID]
    tool_calls_metadata: list[dict[str, Any]] | dict[str, Any] | None
    num_tokens_input: int | None
    num_tokens_output: int | None
    effective_prompt: str
    model_parameters_json: dict[str, Any]
    requested_model: str | None = None
    response_model: str | None = None
    provider: str | None = None
    finish_reason: str | None = None
    provider_response_id: str | None = None
    contract_validation: dict[str, Any] | None = None
    structured_output: dict[str, Any] | list[Any] | None = None
    diagnostics: list[StepDiagnostic] = field(default_factory=_empty_step_diagnostics)
    artifacts: list[dict[str, Any]] | None = None
    rag_metadata: dict[str, Any] | None = None
    transcription_metadata: dict[str, Any] | None = None
    runtime_input_metadata: dict[str, Any] | None = None
    output_payload_extensions: dict[str, Any] | None = None
    citation_sidecar: dict[str, Any] | None = None
    raw_completion_text: str | None = None


@dataclass
class StepInputValue:
    text: str
    source_text: str = ""
    files: list[File] | None = None
    structured: dict[str, Any] | list[Any] | None = None
    raw_extracted_text: str = ""
    input_source: str = "flow_input"
    used_question_binding: bool = False
    diagnostics: list[StepDiagnostic] = field(default_factory=_empty_step_diagnostics)
    transcription_metadata: dict[str, Any] | None = None
    runtime_input_metadata: dict[str, Any] | None = None
    edges: tuple[FlowResolvedInputEdge, ...] = ()


@dataclass
class RunExecutionState:
    completed_by_order: dict[int, FlowStepResult]
    prior_results: list[FlowStepResult]
    assistant_cache: dict[UUID, Any]
    json_mode_supported: dict[str, bool]
    file_cache: dict[frozenset[UUID], list[File]]
    space_cache: dict[UUID, Space] = field(default_factory=_empty_space_cache)
    attempt_start_by_step: dict[UUID, FlowStepAttemptStart] = field(
        default_factory=_empty_attempt_start_by_step
    )
    in_flight_llm_task: asyncio.Task[Any] | None = None
    mapped_admission_by_step: dict[UUID, FlowStepAttemptMappedAdmission] = field(
        default_factory=_empty_mapped_admission_by_step
    )
    activated_attempts: set[tuple[UUID, int]] = field(
        default_factory=_empty_activated_attempts
    )
    step_names_by_order: dict[int, str] = field(
        default_factory=_empty_step_names_by_order
    )
    step_ref_mapping: dict[str, int] = field(default_factory=_empty_step_ref_mapping)

    def all_previous_text_before(self, step_order: int) -> str:
        segments: list[str] = []
        for completed_order in sorted(self.completed_by_order):
            if completed_order >= step_order:
                continue
            segments.append(
                format_all_previous_step_segment(
                    self.completed_by_order[completed_order]
                )
            )
        return "".join(segments)

    def append_completed(self, result: FlowStepResult) -> None:
        self.completed_by_order[result.step_order] = result
        self.prior_results.append(result)


def format_all_previous_step_segment(result: FlowStepResult) -> str:
    payload = result.output_payload_json
    if not isinstance(payload, dict) or (
        "text" not in payload and OUTPUT_TEXT_OVERFLOW_KEY not in payload
    ):
        return (
            f"<step_{result.step_order}_output>\n\n</step_{result.step_order}_output>\n"
        )
    text = interpret_step_text(payload)
    if isinstance(text, FileBackedStepText):
        raise StepOutputMetadataError(
            "Complete step text is stored in a generated output file."
        )
    return (
        f"<step_{result.step_order}_output>\n{text.text}\n"
        f"</step_{result.step_order}_output>\n"
    )
