from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from intric.flows.domain.flow import FlowStepResult
from intric.flows.variable_resolver import flow_step_result_output_text


def _empty_step_diagnostics() -> list["StepDiagnostic"]:
    return []


def _empty_step_names_by_order() -> dict[int, str]:
    return {}


def _empty_step_ref_mapping() -> dict[str, int]:
    return {}


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
    legacy_prompt_binding_used: bool
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
    files: list[Any] | None = None
    structured: dict[str, Any] | list[Any] | None = None
    raw_extracted_text: str = ""
    input_source: str = "flow_input"
    used_question_binding: bool = False
    legacy_prompt_binding_used: bool = False
    diagnostics: list[StepDiagnostic] = field(default_factory=_empty_step_diagnostics)
    transcription_metadata: dict[str, Any] | None = None
    runtime_input_metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class StepInputResolution:
    input_text: str
    source_text: str
    input_source: str
    used_question_binding: bool
    legacy_prompt_binding_used: bool


@dataclass
class RunExecutionState:
    completed_by_order: dict[int, FlowStepResult]
    prior_results: list[FlowStepResult]
    all_previous_segments: list[str]
    assistant_cache: dict[UUID, Any]
    json_mode_supported: dict[str, bool]
    file_cache: dict[frozenset[UUID], list[Any]]
    step_names_by_order: dict[int, str] = field(
        default_factory=_empty_step_names_by_order
    )
    step_ref_mapping: dict[str, int] = field(default_factory=_empty_step_ref_mapping)

    @property
    def all_previous_text(self) -> str:
        return "".join(self.all_previous_segments)

    def append_completed(self, result: FlowStepResult) -> None:
        self.completed_by_order[result.step_order] = result
        self.prior_results.append(result)
        text = flow_step_result_output_text(result)
        self.all_previous_segments.append(
            f"<step_{result.step_order}_output>\n{text}\n</step_{result.step_order}_output>\n"
        )
