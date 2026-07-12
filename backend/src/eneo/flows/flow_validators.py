from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from enum import Enum
from typing import Any, cast

from eneo.database.tables.flow_tables import (
    FLOW_STEP_INPUT_SOURCE_VALUES,
    FLOW_STEP_INPUT_TYPE_VALUES,
    FLOW_STEP_OUTPUT_MODE_VALUES,
    FLOW_STEP_OUTPUT_TYPE_VALUES,
)
from eneo.flows.citation_sidecar import (
    CITATION_MODE_INLINE_INREF_SIDECAR,
    CITATION_MODE_OFF,
    resolve_citation_mode,
)
from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRuntimeInputConfig,
    FlowStep,
)
from eneo.flows.domain.flow_step_validation import (
    FlowGraphIssueCode,
    FlowStepGraphIssue,
    FlowStepValidationError,
    FlowStepValidationView,
    flow_step_validation_views_from_flow_steps,
)
from eneo.flows.flow_capability_manifest import (
    FlowOutputMode,
    FlowOutputType,
    is_citation_capable_step,
)
from eneo.flows.flow_review_policy import parse_flow_step_review_policy
from eneo.flows.flow_validators_form import (
    validate_form_schema,
    validate_variable_alias_collisions,
)
from eneo.flows.flow_validators_http import (
    validate_http_input_config,
    validate_http_output_config,
)
from eneo.flows.flow_validators_template import (
    validate_template_fill_output_config,
)
from eneo.flows.input_binding_contract_rules import (
    FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
    InputBindingContractError,
    effective_question_binding,
    input_contract_conflicts_with_question_binding,
    item_template_field_names,
    question_binding,
    source_ref_bindings,
    unsupported_input_binding_key,
    validate_source_refs_binding,
)
from eneo.flows.output_modes import (
    compose_text_violation,
    render_verbatim_violation,
    text_document_pass_through_violation,
    transcribe_only_violation,
)
from eneo.flows.output_processing import (
    schema_expects_structured,
    validate_schema_syntax,
)
from eneo.flows.runtime_input import build_runtime_input_config
from eneo.flows.step_chain_rules import iter_step_chain_violations
from eneo.flows.step_item_map import build_step_item_map_config
from eneo.flows.template_reference_analyzer import (
    analyze_template,
    consumes_runtime_input,
)
from eneo.flows.transcription_config import (
    FlowTranscriptionConfigError,
    parse_transcription_config,
)
from eneo.flows.type_policies import INPUT_TYPE_POLICIES
from eneo.flows.variable_resolver import iter_template_expressions
from eneo.main.exceptions import BadRequestException, TypedIOValidationException

_STEP_REFERENCE_PATTERN = re.compile(r"^step_(\d+)$")
_ALLOWED_FLOW_INPUT_SOURCES = set(FLOW_STEP_INPUT_SOURCE_VALUES)
_ALLOWED_FLOW_INPUT_TYPES = set(FLOW_STEP_INPUT_TYPE_VALUES)
_ALLOWED_FLOW_OUTPUT_MODES = set(FLOW_STEP_OUTPUT_MODE_VALUES)
_ALLOWED_FLOW_OUTPUT_TYPES = set(FLOW_STEP_OUTPUT_TYPE_VALUES)
FLOW_AUDIO_TRANSCRIPTION_REQUIRED = (
    FlowGraphIssueCode.FLOW_AUDIO_TRANSCRIPTION_REQUIRED.value
)
FLOW_AUDIO_TRANSCRIPTION_MODEL_REQUIRED = (
    FlowGraphIssueCode.FLOW_AUDIO_TRANSCRIPTION_MODEL_REQUIRED.value
)
__all__ = [
    "FLOW_AUDIO_TRANSCRIPTION_MODEL_REQUIRED",
    "FLOW_AUDIO_TRANSCRIPTION_REQUIRED",
    "collect_step_graph_issues",
    "validate_form_schema",
    "validate_step_graph",
    "validate_steps",
    "validate_variable_alias_collisions",
]


def validate_steps(
    steps: list[FlowStep],
    *,
    metadata_json: FlowPersistedJsonObject | None = None,
    require_complete_template_fill_config: bool = False,
) -> None:
    validate_step_graph(
        flow_step_validation_views_from_flow_steps(steps),
        metadata_json=metadata_json,
        require_complete_template_fill_config=require_complete_template_fill_config,
    )


def validate_step_graph(
    steps: Sequence[FlowStepValidationView],
    *,
    metadata_json: FlowPersistedJsonObject | None = None,
    require_complete_template_fill_config: bool = False,
) -> None:
    issues = collect_step_graph_issues(
        steps,
        metadata_json=metadata_json,
        require_complete_template_fill_config=require_complete_template_fill_config,
    )
    if issues:
        raise _to_exception(issues[0])


def collect_step_graph_issues(
    steps: Sequence[FlowStepValidationView],
    *,
    metadata_json: FlowPersistedJsonObject | None = None,
    require_complete_template_fill_config: bool = False,
) -> list[FlowStepGraphIssue]:
    if not steps:
        return []

    sorted_steps = sorted(steps, key=lambda item: item.step_order)
    step_orders = [step.step_order for step in sorted_steps]
    if len(step_orders) != len(set(step_orders)):
        return [
            _bad_request_issue(
                code=FlowGraphIssueCode.DUPLICATE_STEP_ORDER,
                message="Duplicate step_order detected.",
            )
        ]

    expected_orders = list(range(1, len(sorted_steps) + 1))
    if step_orders != expected_orders:
        return [
            _bad_request_issue(
                code=FlowGraphIssueCode.STEP_ORDER_NOT_CONTIGUOUS,
                message="Step order must be contiguous and start at 1.",
            )
        ]

    issues: list[FlowStepGraphIssue] = []
    normalized_names: set[str] = set()
    for step in sorted_steps:
        if step.user_description is None:
            continue
        normalized_name = step.user_description.strip().casefold()
        if not normalized_name:
            continue
        if normalized_name in normalized_names:
            issues.append(
                _bad_request_issue(
                    code=FlowGraphIssueCode.DUPLICATE_STEP_NAME,
                    message="Step names must be unique (case-insensitive) for publishable flows.",
                    step_order=step.step_order,
                )
            )
        normalized_names.add(normalized_name)

    for chain_violation in iter_step_chain_violations(sorted_steps):
        issues.append(
            _flow_step_issue(
                code=chain_violation.code,
                message=chain_violation.message,
                step_order=chain_violation.step_order,
            )
        )

    terminal_step_order = sorted_steps[-1].step_order
    steps_by_order = {step.step_order: step for step in sorted_steps}
    seen: set[int] = set()
    for step in sorted_steps:
        seen.add(step.step_order)
        issue_count_before_enum = len(issues)
        _capture_flow_step_validation(
            issues,
            FlowGraphIssueCode.FLOW_STEP_INVALID,
            lambda: _validate_step_enum_values(step),
        )
        if len(issues) > issue_count_before_enum:
            continue
        _capture_flow_step_validation(
            issues,
            FlowGraphIssueCode.FLOW_STEP_INVALID,
            lambda: _validate_step_timeout(step),
        )
        _capture_flow_step_validation(
            issues,
            FlowGraphIssueCode.FLOW_STEP_INVALID,
            lambda: _validate_review_policy(step),
        )
        _capture_flow_step_validation(
            issues,
            FlowGraphIssueCode.FLOW_STEP_INVALID,
            lambda: _validate_citation_mode(step),
        )
        if step.input_source == "http_get":
            _capture_bad_request_validation(
                issues,
                FlowGraphIssueCode.FLOW_STEP_INVALID,
                step_order=step.step_order,
                validate=lambda: validate_http_input_config(step=step),
            )
        if step.output_mode == "http_post":
            if step.step_order != terminal_step_order:
                issues.append(
                    _flow_step_issue(
                        code=FlowGraphIssueCode.FLOW_HTTP_POST_OUTPUT_MUST_BE_TERMINAL,
                        message=(
                            f"Step {step.step_order}: output_mode 'http_post' is only supported "
                            "on the last step."
                        ),
                        step_order=step.step_order,
                        exception_code=(
                            FlowGraphIssueCode.FLOW_HTTP_POST_OUTPUT_MUST_BE_TERMINAL.value
                        ),
                    )
                )
            else:
                _capture_bad_request_validation(
                    issues,
                    FlowGraphIssueCode.FLOW_STEP_INVALID,
                    step_order=step.step_order,
                    validate=lambda: validate_http_output_config(step=step),
                )
        transcribe_only_error = transcribe_only_violation(
            step_order=step.step_order,
            input_type=step.input_type,
            output_type=step.output_type,
            output_mode=step.output_mode,
        )
        if transcribe_only_error is not None:
            issues.append(
                _flow_step_issue(
                    code=FlowGraphIssueCode.TRANSCRIBE_ONLY_VIOLATION,
                    message=transcribe_only_error,
                    step_order=step.step_order,
                )
            )
        render_verbatim_error = render_verbatim_violation(
            step_order=step.step_order,
            input_type=step.input_type,
            output_type=step.output_type,
            output_mode=step.output_mode,
        )
        if render_verbatim_error is not None:
            issues.append(
                _flow_step_issue(
                    code=FlowGraphIssueCode.FLOW_STEP_INVALID,
                    message=render_verbatim_error,
                    step_order=step.step_order,
                )
            )
        compose_text_error = compose_text_violation(
            step_order=step.step_order,
            input_type=step.input_type,
            output_type=step.output_type,
            output_mode=step.output_mode,
        )
        if compose_text_error is not None:
            issues.append(
                _flow_step_issue(
                    code=FlowGraphIssueCode.FLOW_STEP_INVALID,
                    message=compose_text_error,
                    step_order=step.step_order,
                )
            )
        text_document_pass_through_error = text_document_pass_through_violation(
            step_order=step.step_order,
            input_type=step.input_type,
            output_type=step.output_type,
            output_mode=step.output_mode,
        )
        if text_document_pass_through_error is not None:
            issues.append(
                _flow_step_issue(
                    code=FlowGraphIssueCode.FLOW_STEP_INVALID,
                    message=text_document_pass_through_error,
                    step_order=step.step_order,
                )
            )
        if step.output_mode == "template_fill":
            _capture_flow_step_validation(
                issues,
                FlowGraphIssueCode.TEMPLATE_FILL_REQUIRES_DOCX
                if step.output_type != "docx"
                else FlowGraphIssueCode.FLOW_STEP_INVALID,
                lambda: validate_template_fill_output_config(
                    step=step,
                    available_orders=seen,
                    require_complete_config=require_complete_template_fill_config,
                ),
            )
        input_policy = INPUT_TYPE_POLICIES.get(step.input_type)
        if input_policy and not input_policy.supported:
            issues.append(
                _flow_step_issue(
                    code=FlowGraphIssueCode.UNSUPPORTED_INPUT_TYPE,
                    message=(
                        f"Step {step.step_order}: {_enum_value(step.input_type)} is not yet supported."
                    ),
                    step_order=step.step_order,
                )
            )
        if (
            step.input_contract is not None
            and input_policy
            and not input_policy.contract_allowed
        ):
            issues.append(
                _flow_step_issue(
                    code=FlowGraphIssueCode.INPUT_CONTRACT_TYPE_MISMATCH,
                    message=(
                        f"Step {step.step_order}: input_contract is not supported for "
                        f"input_type '{_enum_value(step.input_type)}'."
                    ),
                    step_order=step.step_order,
                )
            )
        if step.input_contract is not None:
            input_contract_valid = _capture_contract_syntax(
                issues,
                code=FlowGraphIssueCode.INVALID_INPUT_CONTRACT_SCHEMA,
                contract=step.input_contract,
                label=f"Step {step.step_order} input_contract",
                step_order=step.step_order,
            )
            if input_contract_valid:
                _capture_flow_step_validation(
                    issues,
                    FlowGraphIssueCode.FLOW_STEP_INVALID,
                    lambda: _validate_input_contract_binding_compatibility(step=step),
                )
                _capture_flow_step_validation(
                    issues,
                    FlowGraphIssueCode.INPUT_CONTRACT_SOURCE_MISMATCH,
                    lambda: _validate_input_contract_source_compatibility(step=step),
                )
        if step.output_contract is not None:
            output_contract_valid = _capture_contract_syntax(
                issues,
                code=FlowGraphIssueCode.INVALID_OUTPUT_CONTRACT_SCHEMA,
                contract=step.output_contract,
                label=f"Step {step.step_order} output_contract",
                step_order=step.step_order,
            )
            if output_contract_valid:
                _capture_flow_step_validation(
                    issues,
                    _output_contract_issue_code(step),
                    lambda: _validate_output_contract_compatibility(step=step),
                )

        if step.input_bindings is not None:
            input_bindings = step.input_bindings
            if require_complete_template_fill_config:
                _capture_flow_step_validation(
                    issues,
                    FlowGraphIssueCode.FLOW_STEP_INVALID,
                    lambda: _validate_supported_input_binding_keys(step=step),
                )
            _capture_flow_step_validation(
                issues,
                FlowGraphIssueCode.FLOW_STEP_INVALID,
                lambda: _validate_binding_references(
                    input_bindings=input_bindings,
                    current_step_order=step.step_order,
                    available_orders=seen,
                ),
            )
            _capture_flow_step_validation(
                issues,
                FlowGraphIssueCode.FLOW_STEP_INVALID,
                lambda: _validate_compose_source_ref_contracts(
                    step=step,
                    steps_by_order=steps_by_order,
                ),
            )
        _capture_flow_step_validation(
            issues,
            FlowGraphIssueCode.FLOW_STEP_INVALID,
            lambda: _validate_runtime_input_publish_rules(step=step),
        )
        _capture_bad_request_validation(
            issues,
            FlowGraphIssueCode.FLOW_STEP_INVALID,
            validate=lambda: _validate_step_item_map_config(step=step),
            step_order=step.step_order,
        )

    _capture_bad_request_validation(
        issues,
        FlowGraphIssueCode.AUDIO_DOCUMENT_TRANSCRIPT_CHAIN_INVALID,
        validate=lambda: _validate_audio_document_transcript_chain(steps=sorted_steps),
    )
    _capture_bad_request_validation(
        issues,
        FlowGraphIssueCode.FLOW_AUDIO_TRANSCRIPTION_INVALID,
        validate=lambda: _validate_audio_transcription_settings(
            steps=sorted_steps,
            metadata_json=metadata_json,
        ),
    )
    return issues


def _to_exception(issue: FlowStepGraphIssue) -> BadRequestException:
    if issue.exception_kind == "flow_step" and issue.step_order is not None:
        return FlowStepValidationError(
            issue.message,
            step_order=issue.step_order,
            code=issue.exception_code,
            context=issue.context,
        )
    return BadRequestException(
        issue.message,
        code=issue.exception_code,
        context=issue.context,
    )


def _bad_request_issue(
    *,
    code: FlowGraphIssueCode,
    message: str,
    step_order: int | None = None,
    exception_code: str | None = None,
    context: dict[str, object] | None = None,
) -> FlowStepGraphIssue:
    return FlowStepGraphIssue(
        step_order=step_order,
        code=code,
        message=message,
        exception_kind="bad_request",
        exception_code=exception_code,
        context=context,
    )


def _flow_step_issue(
    *,
    code: FlowGraphIssueCode,
    message: str,
    step_order: int,
    exception_code: str | None = None,
    context: dict[str, object] | None = None,
) -> FlowStepGraphIssue:
    return FlowStepGraphIssue(
        step_order=step_order,
        code=code,
        message=message,
        exception_kind="flow_step",
        exception_code=exception_code,
        context=context,
    )


def _capture_flow_step_validation(
    issues: list[FlowStepGraphIssue],
    code: FlowGraphIssueCode,
    validate: Callable[[], None],
) -> None:
    try:
        validate()
    except FlowStepValidationError as exc:
        issues.append(
            _flow_step_issue(
                code=_issue_code_from_exception_code(exc.code, default=code),
                message=str(exc),
                step_order=exc.step_order,
                exception_code=exc.code,
                context=exc.context,
            )
        )


def _capture_bad_request_validation(
    issues: list[FlowStepGraphIssue],
    code: FlowGraphIssueCode,
    *,
    validate: Callable[[], None],
    step_order: int | None = None,
) -> None:
    try:
        validate()
    except FlowStepValidationError as exc:
        issues.append(
            _flow_step_issue(
                code=_issue_code_from_exception_code(exc.code, default=code),
                message=str(exc),
                step_order=exc.step_order,
                exception_code=exc.code,
                context=exc.context,
            )
        )
    except BadRequestException as exc:
        issues.append(
            _bad_request_issue(
                code=_issue_code_from_exception_code(exc.code, default=code),
                message=str(exc),
                step_order=step_order,
                exception_code=exc.code,
                context=exc.context,
            )
        )


def _capture_contract_syntax(
    issues: list[FlowStepGraphIssue],
    *,
    code: FlowGraphIssueCode,
    contract: FlowPersistedJsonObject,
    label: str,
    step_order: int,
) -> bool:
    try:
        validate_schema_syntax(contract, label=label)
    except TypedIOValidationException as exc:
        issues.append(
            _flow_step_issue(
                code=code,
                message=str(exc),
                step_order=step_order,
            )
        )
        return False
    return True


def _output_contract_issue_code(step: FlowStepValidationView) -> FlowGraphIssueCode:
    if step.output_mode == "template_fill":
        return FlowGraphIssueCode.OUTPUT_CONTRACT_TEMPLATE_FILL_INCOMPATIBLE
    return FlowGraphIssueCode.OUTPUT_CONTRACT_TYPE_MISMATCH


def _issue_code_from_exception_code(
    value: str | None,
    *,
    default: FlowGraphIssueCode,
) -> FlowGraphIssueCode:
    if value is None:
        return default
    try:
        return FlowGraphIssueCode(value)
    except ValueError:
        return default


def _validate_step_enum_values(step: FlowStepValidationView) -> None:
    if step.input_source not in _ALLOWED_FLOW_INPUT_SOURCES:
        raise FlowStepValidationError(
            f"Step {step.step_order}: unsupported input_source '{_enum_value(step.input_source)}'.",
            step_order=step.step_order,
        )
    if step.input_type not in _ALLOWED_FLOW_INPUT_TYPES:
        raise FlowStepValidationError(
            f"Step {step.step_order}: unsupported input_type '{_enum_value(step.input_type)}'.",
            step_order=step.step_order,
        )
    if step.output_mode not in _ALLOWED_FLOW_OUTPUT_MODES:
        raise FlowStepValidationError(
            f"Step {step.step_order}: unsupported output_mode '{_enum_value(step.output_mode)}'.",
            step_order=step.step_order,
        )
    if step.output_type not in _ALLOWED_FLOW_OUTPUT_TYPES:
        raise FlowStepValidationError(
            f"Step {step.step_order}: unsupported output_type '{_enum_value(step.output_type)}'.",
            step_order=step.step_order,
        )


def _validate_step_timeout(step: FlowStepValidationView) -> None:
    if step.timeout_seconds is None:
        return
    if isinstance(step.timeout_seconds, bool):
        raise FlowStepValidationError(
            f"Step {step.step_order}: timeout_seconds must be an integer.",
            step_order=step.step_order,
        )
    if step.timeout_seconds <= 0:
        raise FlowStepValidationError(
            f"Step {step.step_order}: timeout_seconds must be greater than zero.",
            step_order=step.step_order,
        )


def _validate_citation_mode(step: FlowStepValidationView) -> None:
    citation_mode = resolve_citation_mode(step.output_config)
    if citation_mode == CITATION_MODE_OFF:
        return
    if citation_mode != CITATION_MODE_INLINE_INREF_SIDECAR:
        raise FlowStepValidationError(
            f"Step {step.step_order}: unsupported output_config.citation_mode '{citation_mode}'.",
            step_order=step.step_order,
        )
    if step.output_type != "text":
        raise FlowStepValidationError(
            f"Step {step.step_order}: citation_mode 'inline_inref_sidecar' requires output_type 'text'.",
            step_order=step.step_order,
        )
    if not is_citation_capable_step(
        output_type=FlowOutputType(step.output_type),
        output_mode=FlowOutputMode(step.output_mode),
        output_config=step.output_config,
    ):
        raise FlowStepValidationError(
            f"Step {step.step_order}: citation_mode 'inline_inref_sidecar' requires an LLM-backed text step.",
            step_order=step.step_order,
        )


def _validate_review_policy(step: FlowStepValidationView) -> None:
    raw_policy: object = step.review_policy
    try:
        parse_flow_step_review_policy(
            raw_policy=raw_policy,
            output_mode=FlowOutputMode(step.output_mode),
        )
    except BadRequestException as exc:
        raise FlowStepValidationError(
            str(exc),
            code=exc.code,
            context=exc.context,
            step_order=step.step_order,
        ) from exc


def _validate_output_contract_compatibility(*, step: FlowStepValidationView) -> None:
    if step.output_contract is None:
        return
    if step.output_mode == "template_fill":
        raise FlowStepValidationError(
            f"Step {step.step_order}: output_contract is not supported for output_mode 'template_fill'.",
            step_order=step.step_order,
        )
    if step.output_mode == "render_verbatim":
        raise FlowStepValidationError(
            f"Step {step.step_order}: output_contract is not supported for output_mode 'render_verbatim'.",
            step_order=step.step_order,
        )
    if step.output_type == "text":
        raise FlowStepValidationError(
            f"Step {step.step_order}: output_contract is not supported for output_type 'text'.",
            step_order=step.step_order,
        )
    if step.output_type in {"pdf", "docx"}:
        schema_type = _schema_type_hint(step.output_contract)
        if schema_type not in {"object", "array"}:
            raise FlowStepValidationError(
                f"Step {step.step_order}: output_contract for generated document "
                f"output_type '{step.output_type}' must declare schema type "
                "'object' or 'array'.",
                step_order=step.step_order,
            )


def _validate_input_contract_source_compatibility(
    *, step: FlowStepValidationView
) -> None:
    if step.input_contract is None:
        return
    if step.input_source != "all_previous_steps":
        return
    if step.input_type != "text":
        return
    if not schema_expects_structured(step.input_contract):
        return
    raise FlowStepValidationError(
        f"Step {step.step_order}: structured input_contract is not supported with "
        "input_source 'all_previous_steps' because concatenated prior step text "
        "is not a single JSON value.",
        step_order=step.step_order,
    )


def _validate_input_contract_binding_compatibility(
    *, step: FlowStepValidationView
) -> None:
    if not input_contract_conflicts_with_question_binding(
        input_bindings=step.input_bindings,
        input_contract=step.input_contract,
    ):
        return
    raise FlowStepValidationError(
        f"Step {step.step_order}: input_contract cannot validate "
        "input_bindings.question because the question binding supplies the "
        "complete rendered step input. Remove input_contract or remove "
        "input_bindings.question.",
        code=FlowGraphIssueCode.FLOW_INPUT_CONTRACT_INAPPLICABLE.value,
        context={
            "step_order": step.step_order,
            "field": "input_contract",
            "conflict": "input_bindings.question",
        },
        step_order=step.step_order,
    )


def _validate_supported_input_binding_keys(*, step: FlowStepValidationView) -> None:
    unsupported_key = unsupported_input_binding_key(step.input_bindings)
    if unsupported_key is not None:
        raise FlowStepValidationError(
            f"Step {step.step_order}: unsupported input_bindings key '{unsupported_key}'. "
            "Only input_bindings.question and input_bindings.source_refs are supported.",
            code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
            context={"field": "input_bindings", "key": unsupported_key},
            step_order=step.step_order,
        )
    try:
        validate_source_refs_binding(step.input_bindings)
    except InputBindingContractError as exc:
        raise FlowStepValidationError(
            f"Step {step.step_order}: {exc}",
            code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
            context={"field": "input_bindings", "key": exc.key},
            step_order=step.step_order,
        ) from exc


def _schema_type_hint(schema: dict[str, Any]) -> str:
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return raw_type
    if isinstance(raw_type, list):
        declared: list[str] = [
            item for item in cast(list[object], raw_type) if isinstance(item, str)
        ]
        if "object" in declared:
            return "object"
        if "array" in declared:
            return "array"
    if isinstance(schema.get("properties"), dict):
        return "object"
    if "items" in schema:
        return "array"
    return "unknown"


def _enum_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    return value


def _validate_audio_transcription_settings(
    *,
    steps: Sequence[FlowStepValidationView],
    metadata_json: FlowPersistedJsonObject | None,
) -> None:
    if not any(step.input_type == "audio" for step in steps):
        return

    try:
        config = parse_transcription_config(metadata_json)
    except FlowTranscriptionConfigError as exc:
        raise BadRequestException(str(exc)) from exc

    if not config.enabled:
        raise BadRequestException(
            "Transcription must be enabled when using audio input steps.",
            code=FLOW_AUDIO_TRANSCRIPTION_REQUIRED,
        )
    if config.model_id is None:
        raise BadRequestException(
            "A transcription model must be selected when using audio input steps.",
            code=FLOW_AUDIO_TRANSCRIPTION_MODEL_REQUIRED,
        )


def _validate_audio_document_transcript_chain(
    *, steps: Sequence[FlowStepValidationView]
) -> None:
    if not steps:
        return
    first_step = steps[0]
    terminal_step = steps[-1]
    if first_step.input_source != "flow_input" or first_step.input_type != "audio":
        return
    if terminal_step.output_type not in {"pdf", "docx"}:
        return
    if first_step.output_type == "text" and first_step.output_mode == "transcribe_only":
        return
    raise BadRequestException(
        "Audio document flows must start with a dedicated transcribe_only "
        "audio-to-text step before analysis or document generation."
    )


def _validate_binding_references(
    *,
    input_bindings: FlowPersistedJsonObject,
    current_step_order: int,
    available_orders: set[int],
) -> None:
    try:
        source_refs = source_ref_bindings(input_bindings)
    except InputBindingContractError as exc:
        raise FlowStepValidationError(
            f"Step {current_step_order}: {exc}",
            code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
            context={"field": "input_bindings", "key": exc.key},
            step_order=current_step_order,
        ) from exc
    expressions = list(
        iter_template_expressions(
            json.dumps({"question": question_binding(input_bindings)})
        )
    )
    expressions.extend(ref.step_ref for ref in source_refs)
    for expression in expressions:
        if expression.startswith("step_input"):
            continue
        if not expression.startswith("step_"):
            continue

        head = expression.split(".", maxsplit=1)[0]
        step_ref = _STEP_REFERENCE_PATTERN.match(head)
        if step_ref is None:
            raise FlowStepValidationError(
                f"Invalid step reference '{head}' in input bindings.",
                code=FlowGraphIssueCode.FLOW_INPUT_BINDING_INVALID_STEP_REFERENCE.value,
                step_order=current_step_order,
            )

        referenced_order = int(step_ref.group(1))
        if referenced_order >= current_step_order:
            raise FlowStepValidationError(
                "Input bindings may only reference outputs from earlier steps.",
                code=FlowGraphIssueCode.FLOW_INPUT_BINDING_FUTURE_STEP_REFERENCE.value,
                step_order=current_step_order,
            )
        if referenced_order not in available_orders:
            raise FlowStepValidationError(
                f"Input binding references unknown step order: {referenced_order}.",
                code=FlowGraphIssueCode.FLOW_INPUT_BINDING_UNKNOWN_STEP_ORDER.value,
                step_order=current_step_order,
            )


def _validate_compose_source_ref_contracts(
    *,
    step: FlowStepValidationView,
    steps_by_order: dict[int, FlowStepValidationView],
) -> None:
    try:
        source_refs = source_ref_bindings(step.input_bindings)
    except InputBindingContractError as exc:
        raise FlowStepValidationError(
            f"Step {step.step_order}: {exc}",
            code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
            context={"field": "input_bindings", "key": exc.key},
            step_order=step.step_order,
        ) from exc
    if not source_refs:
        return

    if step.output_mode != "compose_text":
        for ref in source_refs:
            if ref.item_template is not None:
                raise FlowStepValidationError(
                    f"Step {step.step_order}: input_bindings.source_refs.item_template "
                    "is only supported for output_mode 'compose_text'.",
                    code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
                    context={"field": "input_bindings", "key": "source_refs"},
                    step_order=step.step_order,
                )
        return

    for ref in source_refs:
        if ref.output == "text":
            if ref.item_template is not None:
                raise FlowStepValidationError(
                    f"Step {step.step_order}: item_template is only valid for structured array refs.",
                    code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
                    context={"field": "input_bindings", "key": "source_refs"},
                    step_order=step.step_order,
                )
            continue

        referenced_step = _referenced_step_for_source_ref(
            ref_step=ref.step_ref,
            steps_by_order=steps_by_order,
        )
        if referenced_step is None or referenced_step.output_contract is None:
            raise FlowStepValidationError(
                f"Step {step.step_order}: compose_text structured source_refs require "
                "the referenced step to declare output_contract.",
                code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
                context={"field": "input_bindings", "key": "source_refs"},
                step_order=step.step_order,
            )
        target_schema = _source_ref_schema(
            contract=referenced_step.output_contract,
            field_path=ref.field_path,
            current_step_order=step.step_order,
        )
        target_type = _schema_type_hint(target_schema)
        if target_type == "array":
            _validate_compose_array_source_ref(
                step_order=step.step_order,
                schema=target_schema,
                item_template=ref.item_template,
            )
            continue
        if ref.item_template is not None:
            raise FlowStepValidationError(
                f"Step {step.step_order}: item_template is only valid for structured array refs.",
                code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
                context={"field": "input_bindings", "key": "source_refs"},
                step_order=step.step_order,
            )
        if target_type != "string":
            raise FlowStepValidationError(
                f"Step {step.step_order}: compose_text structured source_refs without "
                "item_template must resolve to a string field.",
                code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
                context={"field": "input_bindings", "key": "source_refs"},
                step_order=step.step_order,
            )


def _referenced_step_for_source_ref(
    *,
    ref_step: str,
    steps_by_order: dict[int, FlowStepValidationView],
) -> FlowStepValidationView | None:
    step_ref = _STEP_REFERENCE_PATTERN.match(ref_step)
    if step_ref is None:
        return None
    return steps_by_order.get(int(step_ref.group(1)))


def _source_ref_schema(
    *,
    contract: FlowPersistedJsonObject,
    field_path: tuple[str, ...],
    current_step_order: int,
) -> FlowPersistedJsonObject:
    current: FlowPersistedJsonObject = contract
    for segment in field_path:
        if _schema_type_hint(current) != "object":
            raise FlowStepValidationError(
                f"Step {current_step_order}: source_ref field_path '{'.'.join(field_path)}' "
                "does not resolve through an object contract.",
                code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
                context={"field": "input_bindings", "key": "source_refs"},
                step_order=current_step_order,
            )
        raw_properties = current.get("properties")
        if not isinstance(raw_properties, dict):
            raise FlowStepValidationError(
                f"Step {current_step_order}: source_ref field_path '{'.'.join(field_path)}' "
                "references a contract without object properties.",
                code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
                context={"field": "input_bindings", "key": "source_refs"},
                step_order=current_step_order,
            )
        properties = cast(dict[str, object], raw_properties)
        next_schema = properties.get(segment)
        if not isinstance(next_schema, dict):
            raise FlowStepValidationError(
                f"Step {current_step_order}: source_ref field_path '{'.'.join(field_path)}' "
                f"references unknown field '{segment}'.",
                code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
                context={"field": "input_bindings", "key": "source_refs"},
                step_order=current_step_order,
            )
        current = cast(FlowPersistedJsonObject, next_schema)
    return current


def _validate_compose_array_source_ref(
    *,
    step_order: int,
    schema: FlowPersistedJsonObject,
    item_template: str | None,
) -> None:
    if item_template is None:
        raise FlowStepValidationError(
            f"Step {step_order}: compose_text structured array source_refs require item_template.",
            code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
            context={"field": "input_bindings", "key": "source_refs"},
            step_order=step_order,
        )
    raw_items = schema.get("items")
    if not isinstance(raw_items, dict):
        raise FlowStepValidationError(
            f"Step {step_order}: compose_text item_template requires an array of objects.",
            code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
            context={"field": "input_bindings", "key": "source_refs"},
            step_order=step_order,
        )
    items = cast(FlowPersistedJsonObject, raw_items)
    if _schema_type_hint(items) != "object":
        raise FlowStepValidationError(
            f"Step {step_order}: compose_text item_template requires an array of objects.",
            code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
            context={"field": "input_bindings", "key": "source_refs"},
            step_order=step_order,
        )
    raw_properties = items.get("properties")
    if not isinstance(raw_properties, dict):
        raise FlowStepValidationError(
            f"Step {step_order}: compose_text item_template requires item properties.",
            code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
            context={"field": "input_bindings", "key": "source_refs"},
            step_order=step_order,
        )
    properties = cast(dict[str, object], raw_properties)
    unknown_fields = [
        field
        for field in item_template_field_names(item_template)
        if field not in properties
    ]
    if unknown_fields:
        raise FlowStepValidationError(
            f"Step {step_order}: item_template references unknown item field "
            f"'{unknown_fields[0]}'.",
            code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
            context={"field": "input_bindings", "key": "source_refs"},
            step_order=step_order,
        )


def _validate_runtime_input_publish_rules(*, step: FlowStepValidationView) -> None:
    runtime_input: FlowRuntimeInputConfig = build_runtime_input_config(
        step.input_config
    )
    if not runtime_input.enabled:
        return

    if step.output_mode == "transcribe_only" and runtime_input.input_format != "audio":
        raise FlowStepValidationError(
            f"Step {step.step_order}: transcribe_only steps require runtime_input.input_format 'audio'.",
            step_order=step.step_order,
        )

    bindings = step.input_bindings if isinstance(step.input_bindings, dict) else None
    if bindings is None:
        return

    question_binding = effective_question_binding(bindings)
    if question_binding is not None:
        references = analyze_template(
            question_binding,
            step_refs={},
            form_field_names=set(),
        )
        if not consumes_runtime_input(references):
            raise FlowStepValidationError(
                f"Step {step.step_order}: explicit question bindings must reference step_input.* when runtime input is enabled.",
                step_order=step.step_order,
            )


def _validate_step_item_map_config(*, step: FlowStepValidationView) -> None:
    build_step_item_map_config(step.input_config)
