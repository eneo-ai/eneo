from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from eneo.flows.domain.flow import FlowPersistedJsonObject, FlowStep
from eneo.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowMcpPolicy,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_review_policy import FlowStepReviewPolicy
from eneo.main.exceptions import BadRequestException


class FlowStepValidationError(BadRequestException):
    def __init__(
        self,
        message: str,
        *,
        step_order: int,
        code: str | None = None,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message, code=code, context=context)
        self.step_order = step_order


class FlowGraphIssueCode(StrEnum):
    AUDIO_DOCUMENT_TRANSCRIPT_CHAIN_INVALID = "audio_document_transcript_chain_invalid"
    DUPLICATE_STEP_NAME = "duplicate_step_name"
    DUPLICATE_STEP_ORDER = "duplicate_step_order"
    FLOW_AUDIO_TRANSCRIPTION_INVALID = "flow_audio_transcription_invalid"
    FLOW_AUDIO_TRANSCRIPTION_MODEL_REQUIRED = "flow_audio_transcription_model_required"
    FLOW_AUDIO_TRANSCRIPTION_REQUIRED = "flow_audio_transcription_required"
    FLOW_HTTP_POST_OUTPUT_MUST_BE_TERMINAL = "flow_http_post_output_must_be_terminal"
    FLOW_INPUT_BINDING_FUTURE_STEP_REFERENCE = (
        "flow_input_binding_future_step_reference"
    )
    FLOW_INPUT_BINDING_INVALID_STEP_REFERENCE = (
        "flow_input_binding_invalid_step_reference"
    )
    FLOW_INPUT_BINDING_UNKNOWN_STEP_ORDER = "flow_input_binding_unknown_step_order"
    FLOW_INPUT_BINDING_UNSUPPORTED_KEY = "flow_input_binding_unsupported_key"
    FLOW_INPUT_CONTRACT_INAPPLICABLE = "flow_input_contract_inapplicable"
    FLOW_REVIEW_POLICY_INVALID = "flow_review_policy_invalid"
    FLOW_REVIEW_POLICY_OUTBOUND_OUTPUT_UNSUPPORTED = (
        "flow_review_policy_outbound_output_unsupported"
    )
    FLOW_STEP_INVALID = "flow_step_invalid"
    INPUT_CONTRACT_SOURCE_MISMATCH = "input_contract_source_mismatch"
    INPUT_CONTRACT_TYPE_MISMATCH = "input_contract_type_mismatch"
    INVALID_INPUT_CONTRACT_SCHEMA = "invalid_input_contract_schema"
    INVALID_OUTPUT_CONTRACT_SCHEMA = "invalid_output_contract_schema"
    OUTPUT_CONTRACT_TEMPLATE_FILL_INCOMPATIBLE = (
        "output_contract_template_fill_incompatible"
    )
    OUTPUT_CONTRACT_TYPE_MISMATCH = "output_contract_type_mismatch"
    STEP_ORDER_NOT_CONTIGUOUS = "step_order_not_contiguous"
    TEMPLATE_FILL_REQUIRES_DOCX = "template_fill_requires_docx"
    TRANSCRIBE_ONLY_VIOLATION = "transcribe_only_violation"
    TYPED_IO_AUDIO_SOURCE_UNSUPPORTED = "typed_io_audio_source_unsupported"
    TYPED_IO_DOCUMENT_SOURCE_UNSUPPORTED = "typed_io_document_source_unsupported"
    TYPED_IO_FILE_SOURCE_UNSUPPORTED = "typed_io_file_source_unsupported"
    TYPED_IO_FLOW_INPUT_POSITION_INVALID = "typed_io_flow_input_position_invalid"
    TYPED_IO_INCOMPATIBLE_TYPE_CHAIN = "typed_io_incompatible_type_chain"
    TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION = (
        "typed_io_invalid_input_source_combination"
    )
    TYPED_IO_INVALID_INPUT_SOURCE_POSITION = "typed_io_invalid_input_source_position"
    TYPED_IO_MISSING_PREVIOUS_STEP = "typed_io_missing_previous_step"
    TYPED_IO_MULTIPLE_FLOW_INPUT_STEPS = "typed_io_multiple_flow_input_steps"
    UNSUPPORTED_INPUT_TYPE = "unsupported_input_type"


@dataclass(frozen=True, slots=True)
class FlowStepGraphIssue:
    # `code` is the canonical diagnostic consumed by Builder; `exception_code`
    # preserves the legacy BadRequest/FlowStepValidationError `.code` surface.
    step_order: int | None
    code: FlowGraphIssueCode
    message: str
    exception_kind: Literal["bad_request", "flow_step"]
    exception_code: str | None = None
    context: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class FlowStepValidationView:
    step_order: int
    timeout_seconds: int | None
    user_description: str | None
    input_source: FlowInputSource
    input_type: FlowInputType
    input_contract: FlowPersistedJsonObject | None
    output_mode: FlowOutputMode
    output_type: FlowOutputType
    output_contract: FlowPersistedJsonObject | None
    input_bindings: FlowPersistedJsonObject | None
    mcp_policy: FlowMcpPolicy
    input_config: FlowPersistedJsonObject | None
    output_config: FlowPersistedJsonObject | None
    review_policy: FlowStepReviewPolicy | None


def flow_step_validation_view_from_flow_step(
    step: FlowStep,
) -> FlowStepValidationView:
    return FlowStepValidationView(
        step_order=step.step_order,
        timeout_seconds=step.timeout_seconds,
        user_description=step.user_description,
        input_source=step.input_source,
        input_type=step.input_type,
        input_contract=step.input_contract,
        output_mode=step.output_mode,
        output_type=step.output_type,
        output_contract=step.output_contract,
        input_bindings=step.input_bindings,
        mcp_policy=step.mcp_policy,
        input_config=step.input_config,
        output_config=step.output_config,
        review_policy=step.review_policy,
    )


def flow_step_validation_views_from_flow_steps(
    steps: Sequence[FlowStep],
) -> list[FlowStepValidationView]:
    return [flow_step_validation_view_from_flow_step(step) for step in steps]
