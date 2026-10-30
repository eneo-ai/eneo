from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal, TypeAlias
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
from eneo.flows.domain.step_output import (
    ResolvedStepMaterial as ResolvedStepMaterial,
)
from eneo.flows.enums import flow_output_mode_uses_completion_model
from eneo.flows.flow_review_policy import FlowStepReviewPolicy
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputEdge,
)

if TYPE_CHECKING:
    from eneo.collections.domain.collection import Collection
    from eneo.files.file_models import File, FileInfo
    from eneo.flows.domain.review_edit_references import (
        ReviewedResult,
        ReviewedResultKey,
    )
    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from eneo.spaces.space import Space
    from eneo.websites.domain.website import Website


def _empty_step_diagnostics() -> list["StepDiagnostic"]:
    return []


def _empty_step_names_by_order() -> dict[int, str]:
    return {}


def _empty_step_ref_mapping() -> dict[str, int]:
    return {}


def _empty_attempt_start_by_step() -> dict[UUID, FlowStepAttemptStart]:
    return {}


def _empty_collection_cache() -> dict[UUID, Collection]:
    return {}


def _empty_website_cache() -> dict[UUID, Website]:
    return {}


def _empty_integration_knowledge_cache() -> dict[UUID, IntegrationKnowledge]:
    return {}


def _empty_mapped_admission_by_step() -> dict[UUID, FlowStepAttemptMappedAdmission]:
    return {}


def _empty_reviewed_results() -> dict[ReviewedResultKey, ReviewedResult]:
    return {}


def _empty_counted_tool_server_levels() -> dict[int, int | None]:
    return {}


def _empty_activated_attempts() -> set[tuple[UUID, int]]:
    return set()


def assistant_cache_key(
    assistant_id: UUID, snapshot: dict[str, Any]
) -> tuple[UUID, str]:
    return assistant_id, str(snapshot["execution_surface_hash"])


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


StepDiagnosticSeverity: TypeAlias = Literal["info", "warning", "error"]


@dataclass(frozen=True)
class StepDiagnostic:
    code: str
    message: str
    severity: StepDiagnosticSeverity = "warning"


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
    # Inherited sources the model cited, carried so the next consumer of this
    # output inherits them as well.
    inherited_citation_sources: list[dict[str, Any]] | None = None
    raw_completion_text: str | None = None
    materials: tuple[ResolvedStepMaterial, ...] = ()
    max_inline_text_bytes: int = 0
    # The coverage record of a step that digested long material.
    long_material: dict[str, Any] | None = None


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
    materials: tuple[ResolvedStepMaterial, ...] = ()
    processing_ceiling_bytes: int | None = None


@dataclass(frozen=True)
class InputFileSize:
    inline_bytes: int
    binary_bytes: int
    upload_bytes: int
    audio: bool


@dataclass(frozen=True)
class InputFileAdmission:
    files: Mapping[UUID, FileInfo]
    sizes: Mapping[UUID, InputFileSize]


@dataclass
class RunExecutionState:
    completed_by_order: dict[int, FlowStepResult]
    prior_results: list[FlowStepResult]
    assistant_cache: dict[tuple[UUID, str], Any]
    json_mode_supported: dict[str, bool]
    file_cache: dict[frozenset[UUID], list[File]]
    input_file_admission: InputFileAdmission | None = None
    material_cache: dict[tuple[UUID, str], str] | None = None
    resolved_materials: tuple[ResolvedStepMaterial, ...] = ()
    json_schema_rejected_models: set[str] = field(default_factory=set[str])
    flow_id: UUID | None = None
    flow_space: Space | None = None
    collection_cache: dict[UUID, Collection] = field(
        default_factory=_empty_collection_cache
    )
    website_cache: dict[UUID, Website] = field(default_factory=_empty_website_cache)
    integration_knowledge_cache: dict[UUID, IntegrationKnowledge] = field(
        default_factory=_empty_integration_knowledge_cache
    )
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
    # Edited reviewed JSON results of this run, by (step_id, current attempt).
    reviewed_results: Mapping[ReviewedResultKey, ReviewedResult] = field(
        default_factory=_empty_reviewed_results
    )
    # The orders of the steps whose input is a tool's answer.
    tool_step_orders: frozenset[int] = frozenset()
    # The level the run's preflight counted the server of each tool step at,
    # by step order (None: a server without a classification). Empty while
    # security classifications are off.
    counted_tool_server_levels: dict[int, int | None] = field(
        default_factory=_empty_counted_tool_server_levels
    )

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
        result = project_completed_result(result)
        self.completed_by_order[result.step_order] = result
        self.prior_results.append(result)


# The copies of a step's input text. Later steps read a completed step's
# output, its identity and its input's metadata (runtime_input, rag,
# transcription), never these nor its prompt; every other key stays.
_UNREAD_COMPLETED_INPUT_KEYS: Final = frozenset({"text", "source_text"})


def project_completed_result(result: FlowStepResult) -> FlowStepResult:
    """A completed step result as run state holds it, without the input copies
    and prompt no later step reads.

    A shallow copy: the persisted row, which review, regeneration and retry
    read again from the repository, is left as it is.
    """
    payload = result.input_payload_json
    update: dict[str, Any] = {"effective_prompt": None}
    if isinstance(payload, dict):
        update["input_payload_json"] = {
            key: value
            for key, value in payload.items()
            if key not in _UNREAD_COMPLETED_INPUT_KEYS
        }
    return result.model_copy(update=update)


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
