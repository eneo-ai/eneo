from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from enum import Enum
from typing import Any, cast

from pydantic import ValidationError

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
from eneo.flows.domain.canonical_json_hash import json_values_differ
from eneo.flows.domain.flow import (
    FLOW_STEP_RETRIEVAL_POLICY_KEY,
    FlowPersistedJsonObject,
    FlowRuntimeInputConfig,
    FlowStep,
    parse_flow_step_retrieval_policy,
)
from eneo.flows.domain.flow_step_validation import (
    FlowGraphIssueCode,
    FlowStepGraphIssue,
    FlowStepValidationError,
    FlowStepValidationView,
    flow_step_validation_views_from_flow_steps,
)
from eneo.flows.domain.runtime_input import build_runtime_input_config
from eneo.flows.domain.speaker_mapping_config import (
    validate_speaker_mapping_output_config,
)
from eneo.flows.domain.step_mapped_execution import (
    FlowStepMappedExecutionConfigurationError,
    resolve_step_mapped_execution,
    single_mapped_array_key,
)
from eneo.flows.domain.text_processing import text_processing_config
from eneo.flows.flow_authoring_spec import MAX_FLOW_AUTHORING_STEPS
from eneo.flows.flow_authoring_transcription import requires_audio_transcription
from eneo.flows.flow_capability_manifest import (
    FlowOutputMode,
    FlowOutputType,
    is_citation_capable_step,
)
from eneo.flows.flow_metadata import (
    FlowFormFieldType,
    FlowFormSchemaParseMode,
    parse_flow_form_schema,
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
from eneo.flows.flow_variable_definitions import (
    FlowRunInput,
    VariableShape,
    flow_input_key_shape,
    reads_unreceived_run_input,
    runtime_variable_shape,
)
from eneo.flows.input_binding_contract_rules import (
    FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
    InputBindingContractError,
    derive_structured_projection_contract,
    effective_question_binding,
    has_explicit_underlag,
    input_contract_binding_conflict,
    is_structured_projection_binding,
    item_template_field_names,
    question_binding,
    source_ref_bindings,
    source_ref_step_order,
    unsupported_input_binding_key,
    validate_source_refs_binding,
)
from eneo.flows.output_modes import (
    compose_text_violation,
    render_verbatim_violation,
    speaker_mapping_violation,
    text_document_pass_through_violation,
    transcribe_only_violation,
)
from eneo.flows.output_processing import (
    schema_expects_structured,
    validate_against_contract,
    validate_schema_syntax,
)
from eneo.flows.runtime.output_formats import resolve_format_spec
from eneo.flows.step_chain_rules import iter_step_chain_violations
from eneo.flows.step_lineage import (
    build_step_ref_mapping,
    resolve_upstream_step_orders,
    selected_source_step_order,
)
from eneo.flows.template_reference_analyzer import (
    TemplateReferenceKind,
    analyze_template,
    consumes_runtime_input,
)
from eneo.flows.transcription_config import (
    FlowTranscriptionConfigError,
    parse_transcription_config,
)
from eneo.flows.type_policies import INPUT_TYPE_POLICIES
from eneo.flows.variable_resolver import (
    iter_template_expressions,
    runtime_step_alias_order,
)
from eneo.main.exceptions import BadRequestException, TypedIOValidationException

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
    "flow_run_input",
    "retained_contracts",
    "run_input_alias_refusal",
    "step_limit_issue",
    "takes_runtime_files",
    "validate_form_schema",
    "validate_step_count",
    "validate_step_graph",
    "validate_steps",
    "validate_variable_alias_collisions",
]


def step_limit_issue(step_count: int) -> FlowStepGraphIssue | None:
    """The refusal for a flow with more steps than a flow can have, if any."""
    if step_count <= MAX_FLOW_AUTHORING_STEPS:
        return None
    return _bad_request_issue(
        code=FlowGraphIssueCode.FLOW_STEP_LIMIT_EXCEEDED,
        message=(
            f"A flow can have at most {MAX_FLOW_AUTHORING_STEPS} steps; this one has "
            f"{step_count}. Remove steps or split the work into several flows."
        ),
        context={"step_count": step_count, "max_steps": MAX_FLOW_AUTHORING_STEPS},
    )


def validate_step_count(step_count: int) -> None:
    issue = step_limit_issue(step_count)
    if issue is not None:
        raise _to_exception(issue)


def retained_contracts(
    steps: Sequence[FlowStep], stored_steps: Sequence[FlowStep]
) -> frozenset[tuple[int, str]]:
    """The (step order, field) of every contract a save leaves as it was stored, as JSON."""
    stored = {step.id: step for step in stored_steps if step.id is not None}
    retained: set[tuple[int, str]] = set()
    for step in steps:
        before = stored.get(step.id) if step.id is not None else None
        if before is None:
            continue
        for field in ("input_contract", "output_contract"):
            contract = getattr(step, field)
            if contract is not None and not json_values_differ(
                getattr(before, field), contract
            ):
                retained.add((step.step_order, field))
    return frozenset(retained)


def validate_steps(
    steps: list[FlowStep],
    *,
    metadata_json: FlowPersistedJsonObject | None = None,
    require_complete_template_fill_config: bool = False,
    prompt_templates: Mapping[int, str] | None = None,
    retained: frozenset[tuple[int, str]] = frozenset(),
) -> None:
    """Validate the step graph; ``prompt_templates`` are the assistant prompts by step order.

    ``retained`` names the contracts (see retained_contracts) that keep the rules they
    were saved under."""
    validate_step_graph(
        flow_step_validation_views_from_flow_steps(
            steps, prompt_templates=prompt_templates
        ),
        metadata_json=metadata_json,
        require_complete_template_fill_config=require_complete_template_fill_config,
        retained=retained,
    )


def validate_step_graph(
    steps: Sequence[FlowStepValidationView],
    *,
    metadata_json: FlowPersistedJsonObject | None = None,
    require_complete_template_fill_config: bool = False,
    retained: frozenset[tuple[int, str]] = frozenset(),
) -> None:
    issues = collect_step_graph_issues(
        steps,
        metadata_json=metadata_json,
        require_complete_template_fill_config=require_complete_template_fill_config,
        retained=retained,
    )
    if issues:
        raise _to_exception(issues[0])


def collect_step_graph_issues(
    steps: Sequence[FlowStepValidationView],
    *,
    metadata_json: FlowPersistedJsonObject | None = None,
    require_complete_template_fill_config: bool = False,
    retained: frozenset[tuple[int, str]] = frozenset(),
) -> list[FlowStepGraphIssue]:
    if not steps:
        return []

    limit_issue = step_limit_issue(len(steps))
    if limit_issue is not None:
        return [limit_issue]

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
    form_schema = (
        parse_flow_form_schema(
            metadata_json, mode=FlowFormSchemaParseMode.PERSISTED_READ
        )
        if require_complete_template_fill_config
        else None
    )
    form_field_names: set[str] = (
        {field.name for field in form_schema.fields}
        if form_schema is not None
        else set()
    )
    form_field_types: dict[str, str] = (
        {field.name: field.type.value for field in form_schema.fields}
        if form_schema is not None
        else {}
    )
    run_input = flow_run_input(
        form_fields=bool(form_field_names),
        step_input_configs=[step.input_config for step in sorted_steps],
    )
    step_ref_mapping = build_step_ref_mapping(
        {
            "step_order": step.step_order,
            "user_description": step.user_description,
        }
        for step in sorted_steps
    )
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
            lambda: _validate_retrieval_policy(step),
        )
        _capture_flow_step_validation(
            issues,
            FlowGraphIssueCode.CITATION_MODE_UNSUPPORTED,
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
                    validate=lambda: validate_http_output_config(
                        step=replace(
                            step,
                            output_config={
                                key: value
                                for key, value in (step.output_config or {}).items()
                                if key != FLOW_STEP_RETRIEVAL_POLICY_KEY
                            },
                        )
                    ),
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
        speaker_mapping_error = speaker_mapping_violation(
            step_order=step.step_order,
            input_source=step.input_source,
            input_type=step.input_type,
            output_type=step.output_type,
            output_mode=step.output_mode,
        )
        if speaker_mapping_error is not None:
            issues.append(
                _flow_step_issue(
                    code=FlowGraphIssueCode.FLOW_STEP_INVALID,
                    message=speaker_mapping_error,
                    step_order=step.step_order,
                )
            )
        if step.output_mode == "speaker_mapping":
            _capture_flow_step_validation(
                issues,
                FlowGraphIssueCode.FLOW_STEP_INVALID,
                lambda: validate_speaker_mapping_output_config(
                    step=step,
                    form_field_types=form_field_types,
                    require_complete_config=require_complete_template_fill_config,
                ),
            )
        if step.output_mode == "template_fill":
            _capture_flow_step_validation(
                issues,
                FlowGraphIssueCode.TEMPLATE_FILL_REQUIRES_DOCX
                if step.output_type != "docx"
                else FlowGraphIssueCode.FLOW_STEP_INVALID,
                lambda: _validate_template_fill_config(
                    step=step,
                    available_orders=seen,
                    require_complete_config=require_complete_template_fill_config,
                    steps_by_order=steps_by_order,
                    form_field_types=form_field_types,
                    step_ref_mapping=step_ref_mapping,
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
                retained=(step.step_order, "input_contract") in retained,
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
                    lambda: _validate_input_contract_source_compatibility(
                        step=step, steps_by_order=steps_by_order
                    ),
                )
        if step.output_contract is not None:
            output_contract_valid = _capture_contract_syntax(
                issues,
                code=FlowGraphIssueCode.INVALID_OUTPUT_CONTRACT_SCHEMA,
                contract=step.output_contract,
                label=f"Step {step.step_order} output_contract",
                step_order=step.step_order,
                retained=(step.step_order, "output_contract") in retained,
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
                    steps_by_order=steps_by_order,
                    form_field_names=form_field_names,
                    step_ref_mapping=step_ref_mapping,
                    publish_strict=require_complete_template_fill_config,
                ),
            )
            _capture_flow_step_validation(
                issues,
                FlowGraphIssueCode.FLOW_STEP_INVALID,
                lambda: _validate_source_ref_contracts(
                    step=step,
                    steps_by_order=steps_by_order,
                    step_ref_mapping=(
                        step_ref_mapping
                        if require_complete_template_fill_config
                        else {}
                    ),
                ),
            )
        if require_complete_template_fill_config:
            _capture_flow_step_validation(
                issues,
                FlowGraphIssueCode.FLOW_INPUT_ALIAS_NOT_RECEIVED,
                lambda: _validate_run_input_alias_reads(step=step, run_input=run_input),
            )
            _capture_flow_step_validation(
                issues,
                FlowGraphIssueCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION,
                lambda: _validate_section_source_reads(
                    step=step,
                    steps_by_order=steps_by_order,
                    step_ref_mapping=step_ref_mapping,
                ),
            )
        _capture_bad_request_validation(
            issues,
            FlowGraphIssueCode.FLOW_STEP_INVALID,
            validate=lambda: _validate_step_input_configuration(step=step),
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
    # The HTTP payload must carry the canonical issue identity so clients can
    # translate and point at the offending step instead of showing raw text.
    code = issue.exception_code or issue.code.value
    context: dict[str, object] = dict(issue.context or {})
    # The canonical identity always wins over issue-provided context keys.
    context["issue_code"] = issue.code.value
    if issue.step_order is not None:
        context["step_order"] = issue.step_order
    if issue.exception_kind == "flow_step" and issue.step_order is not None:
        return FlowStepValidationError(
            issue.message,
            step_order=issue.step_order,
            code=code,
            context=context,
        )
    return BadRequestException(
        issue.message,
        code=code,
        context=context,
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
    retained: bool,
) -> bool:
    try:
        validate_schema_syntax(contract, label=label, retained=retained)
    except TypedIOValidationException as exc:
        issues.append(
            _flow_step_issue(
                code=code,
                message=str(exc),
                step_order=step_order,
                context=exc.context,
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
            output_type=FlowOutputType(step.output_type),
        )
    except BadRequestException as exc:
        raise FlowStepValidationError(
            str(exc),
            code=exc.code,
            context=exc.context,
            step_order=step.step_order,
        ) from exc


def _validate_retrieval_policy(step: FlowStepValidationView) -> None:
    try:
        parse_flow_step_retrieval_policy(
            step.output_config,
            output_mode=FlowOutputMode(step.output_mode),
        )
    except ValueError as exc:
        raise FlowStepValidationError(
            f"Step {step.step_order}: {exc}",
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
    if step.output_mode == "speaker_mapping":
        raise FlowStepValidationError(
            f"Step {step.step_order}: output_contract is fixed for output_mode "
            "'speaker_mapping' and cannot be authored.",
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
    *,
    step: FlowStepValidationView,
    steps_by_order: dict[int, FlowStepValidationView],
) -> None:
    if step.input_contract is None:
        return
    if step.input_source == "previous_step" and step.input_type == "json":
        try:
            if effective_question_binding(step.input_bindings) is not None:
                return
        except InputBindingContractError:
            return
        producer = steps_by_order.get(step.step_order - 1)
        if producer is None:
            return
        produced = producer.output_contract
        if produced is not None and (
            json.dumps(produced, sort_keys=True)
            == json.dumps(step.input_contract, sort_keys=True)
            or _json_contract_is_subset(produced, step.input_contract)
        ):
            return
        raise FlowStepValidationError(
            f"Step {step.step_order}: input_contract is not guaranteed by step "
            f"{producer.step_order} output_contract for implicit JSON input. "
            "Preserve the consumed contract or edit the consumer as well.",
            step_order=step.step_order,
            context={"producer_step_order": producer.step_order},
        )
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


def _json_contract_is_subset(produced: object, consumed: object) -> bool:
    """Prove inclusion for the authored type/object/array subset only."""
    if consumed is True or produced is False:
        return True
    if produced is True:
        produced = {}
    if not isinstance(produced, dict) or not isinstance(consumed, dict):
        return False
    source = cast(FlowPersistedJsonObject, produced)
    target = cast(FlowPersistedJsonObject, consumed)
    supported = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "title",
        "description",
        "default",
        "examples",
        "$comment",
    }
    # Unknown assertions and references require an unchanged whole contract;
    # equal fragments can resolve differently against their enclosing schema.
    if (source.keys() | target.keys()) - supported:
        return False
    source_types = _json_contract_types(source)
    target_types = _json_contract_types(target)
    if source_types is None or target_types is None:
        return False
    if not source_types <= target_types:
        return False
    if "object" in source_types:
        source_properties = source.get("properties", {})
        target_properties = target.get("properties", {})
        source_required = source.get("required", [])
        target_required = target.get("required", [])
        if not isinstance(source_properties, dict) or not isinstance(
            target_properties, dict
        ):
            return False
        if not isinstance(source_required, list) or not isinstance(
            target_required, list
        ):
            return False
        source_required = cast(list[object], source_required)
        target_required = cast(list[object], target_required)
        if not all(
            isinstance(key, str) for key in [*source_required, *target_required]
        ):
            return False
        if not set(target_required) <= set(source_required):
            return False
        source_properties = cast(FlowPersistedJsonObject, source_properties)
        target_properties = cast(FlowPersistedJsonObject, target_properties)
        source_extra = source.get("additionalProperties", True)
        target_extra = target.get("additionalProperties", True)
        for key in source_properties.keys() | target_properties.keys():
            if not _json_contract_is_subset(
                source_properties.get(key, source_extra),
                target_properties.get(key, target_extra),
            ):
                return False
        if not _json_contract_is_subset(source_extra, target_extra):
            return False
    if "array" in source_types and not _json_contract_is_subset(
        source.get("items", True), target.get("items", True)
    ):
        return False
    return True


def _json_contract_types(schema: FlowPersistedJsonObject) -> set[str] | None:
    raw = schema.get("type", ["null", "boolean", "object", "array", "number", "string"])
    values = [raw] if isinstance(raw, str) else raw
    if not isinstance(values, list) or not all(
        isinstance(value, str) for value in cast(list[object], values)
    ):
        return None
    types = set(cast(list[str], values))
    if "number" in types:
        types.add("integer")
    return types


def _validate_input_contract_binding_compatibility(
    *, step: FlowStepValidationView
) -> None:
    conflict = input_contract_binding_conflict(
        input_bindings=step.input_bindings,
        input_contract=step.input_contract,
        input_type=step.input_type,
    )
    if conflict is None:
        return
    if conflict == "source_refs":
        raise FlowStepValidationError(
            f"Step {step.step_order}: input_contract requires structured JSON "
            "input_bindings.source_refs without question, text refs, or item templates.",
            code=FlowGraphIssueCode.FLOW_INPUT_CONTRACT_INAPPLICABLE.value,
            context={
                "step_order": step.step_order,
                "field": "input_contract",
                "conflict": "input_bindings.source_refs",
            },
            step_order=step.step_order,
        )
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


_SCALAR_FORM_FIELD_TYPES = frozenset(
    {
        FlowFormFieldType.TEXT.value,
        FlowFormFieldType.NUMBER.value,
        FlowFormFieldType.DATE.value,
        FlowFormFieldType.SELECT.value,
    }
)


def _validate_template_fill_config(
    *,
    step: FlowStepValidationView,
    available_orders: set[int],
    require_complete_config: bool,
    steps_by_order: dict[int, FlowStepValidationView],
    form_field_types: dict[str, str],
    step_ref_mapping: dict[str, int],
) -> None:
    validate_template_fill_output_config(
        step=step,
        available_orders=available_orders,
        require_complete_config=require_complete_config,
    )
    if not require_complete_config:
        return
    # The syntax validator above establishes an object of exact expressions or
    # explicit empty values. Publishing additionally requires a known scalar.
    bindings = cast(dict[str, str], (step.output_config or {})["bindings"])
    output_contracts_by_order = {
        order: source.output_contract for order, source in steps_by_order.items()
    }
    for placeholder, binding in bindings.items():
        validate_template_binding_scalar(
            binding,
            placeholder=placeholder,
            step_order=step.step_order,
            output_contracts_by_order=output_contracts_by_order,
            form_field_types=form_field_types,
            step_ref_mapping=step_ref_mapping,
        )
        _validate_template_binding_present(
            binding,
            placeholder=placeholder,
            step_order=step.step_order,
            output_contracts_by_order=output_contracts_by_order,
            step_ref_mapping=step_ref_mapping,
        )


def validate_template_binding_scalar(
    binding: str,
    *,
    placeholder: str,
    step_order: int,
    output_contracts_by_order: Mapping[int, FlowPersistedJsonObject | None],
    form_field_types: Mapping[str, str],
    step_ref_mapping: Mapping[str, int],
) -> None:
    """Require one template binding to name a known scalar, or raise.

    The one rule for what a DOCX placeholder may read: an earlier step's text,
    status or error message, a scalar field of an earlier step's declared
    contract, a scalar Flow input field, or a scalar runtime variable. An
    explicit blank is allowed. Publication applies it to persisted steps; the
    Builder applies the same rule to mappings an edit keeps.
    """

    if not binding.strip():
        return
    references = analyze_template(
        binding,
        step_refs=dict(step_ref_mapping),
        form_field_names=set(form_field_types),
    )
    reference = references[0] if len(references) == 1 else None
    scalar = False
    if reference is None:
        pass
    elif reference.kind is TemplateReferenceKind.STEP:
        source_order = reference.step_order
        if (
            source_order is not None
            and source_order in output_contracts_by_order
            and source_order < step_order
        ):
            scalar = reference.tail in {"output.text", "status", "error_message"}
            source_contract = output_contracts_by_order[source_order]
            if reference.structured_path and source_contract is not None:
                schema = _source_ref_schema(
                    contract=source_contract,
                    field_path=reference.structured_path,
                    current_step_order=step_order,
                    path_label=f"template binding '{placeholder}'",
                    context={
                        "field": "output_config.bindings",
                        "placeholder": placeholder,
                    },
                    error_code=None,
                )
                scalar = _schema_is_scalar(schema)
    elif reference.kind is TemplateReferenceKind.FORM_FIELD:
        scalar = (
            not reference.tail
            and form_field_types.get(reference.head) in _SCALAR_FORM_FIELD_TYPES
        )
    elif reference.kind is TemplateReferenceKind.RUNTIME:
        if not reference.tail:
            scalar = runtime_variable_shape(reference.head) is VariableShape.SCALAR
        elif reference.head in {"flow_input", "flow"}:
            field_name = reference.tail
            if reference.head == "flow":
                field_name = (
                    field_name.removeprefix("input.")
                    if field_name.startswith("input.")
                    else ""
                )
            scalar = (
                form_field_types.get(field_name) in _SCALAR_FORM_FIELD_TYPES
                or flow_input_key_shape(field_name) is VariableShape.SCALAR
            )
    if not scalar or (reference is not None and reference.path_error_code is not None):
        raise FlowStepValidationError(
            f"Step {step_order}: template binding '{placeholder}' must resolve "
            "to a scalar value; select a text output or a scalar field from a declared contract.",
            context={"field": "output_config.bindings", "placeholder": placeholder},
            step_order=step_order,
        )


def template_binding_structured_source(
    binding: str, *, step_ref_mapping: Mapping[str, int]
) -> tuple[int, tuple[str, ...]] | None:
    """The step order and structured field path a template binding reads, if any."""

    references = analyze_template(
        binding, step_refs=dict(step_ref_mapping), form_field_names=set()
    )
    reference = references[0] if len(references) == 1 else None
    if (
        reference is None
        or reference.kind is not TemplateReferenceKind.STEP
        or reference.step_order is None
        or not reference.structured_path
        or reference.path_error_code is not None
    ):
        return None
    return reference.step_order, reference.structured_path


# A tuple, not a set: a declared type list is unhashable.
_FIELD_TYPES = ("string", "number", "integer", "boolean")


def _mapping(node: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], node) if isinstance(node, Mapping) else {}


def template_bound_path_ok(schema: Mapping[str, object], path: tuple[str, ...]) -> bool:
    """Whether the field at `path` is a required field of one type, from the step's result down.

    Keywords of a JSON Schema node are conjunctive: a node whose `type` is one
    non-null type excludes null however its other keywords read. So the step's
    result and every object above the field have `type` exactly "object" and
    list the next key in `properties` and `required`, and the field's `type` is
    exactly one of string, number, integer or boolean. Other keywords are
    allowed, except `$ref` on the path: refs are not resolved here and a
    draft-07 validator ignores its siblings. Satisfiability is not asked.
    """

    node: object = schema
    for key in path:
        obj = _mapping(node)
        required = obj.get("required")
        if (
            obj.get("type") != "object"
            or "$ref" in obj
            or not isinstance(required, list)
            or key not in cast(list[object], required)
        ):
            return False
        node = _mapping(obj.get("properties")).get(key)
    field = _mapping(node)
    return "$ref" not in field and field.get("type") in _FIELD_TYPES


# The keywords a schema may carry anywhere and still be edited. Any other (not,
# allOf, $ref, enum, const, ...) asserts something an edit could turn, here or
# in another branch, into a contract no value satisfies. `default` and
# `examples` are annotations in draft 2020-12 and nothing here reads them.
_PLAIN_NODE_KEYS = frozenset(
    "type properties required additionalProperties items title description "
    "examples default $comment".split()
)


def _is_plain_tree(node: object) -> bool:
    """Whether every schema node under `node` carries only `_PLAIN_NODE_KEYS`."""

    if not isinstance(node, dict):
        return False
    schema = cast(dict[str, object], node)
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if (
        not set(schema) <= _PLAIN_NODE_KEYS
        or not isinstance(properties, dict)
        or not isinstance(required, list)
        # A closed object cannot require a key it does not declare.
        or (
            schema.get("additionalProperties") is False
            and any(key not in properties for key in cast(list[object], required))
        )
    ):
        return False
    children = [*cast(dict[str, object], properties).values()]
    children += [
        schema[key]
        for key in ("items", "additionalProperties")
        if key in schema and not isinstance(schema[key], bool)
    ]
    return all(_is_plain_tree(child) for child in children)


def _narrowed_to(node: dict[str, object], allowed: tuple[str, ...]) -> bool:
    """Whether `node` has one of the `allowed` types, narrowing `[type, "null"]`."""

    declared = node.get("type")
    if isinstance(declared, list):
        kept = [item for item in cast(list[object], declared) if item != "null"]
        if len(kept) == 1 and kept[0] in allowed:
            node["type"] = kept[0]
    return node.get("type") in allowed


def _witness(schema: object) -> object:
    """One instance for a plain schema, accepted whenever the schema is satisfiable.

    Text is "", numbers and integers 0, booleans false and an array `[]`, which
    a plain schema always accepts (it has no minItems, contains or
    prefixItems). An object has every required key, filled recursively: from
    `properties`, else from the `additionalProperties` schema, else "". The one
    plain shape it can refuse without cause is a type list of several non-null
    types whose first member is unsatisfiable while another is not; the edit
    is then refused, which fails safe.
    """

    node = _mapping(schema)
    declared = node.get("type")
    listed = cast(list[object], declared) if isinstance(declared, list) else [declared]
    kinds = [kind for kind in listed if isinstance(kind, str)]
    kind = next((kind for kind in kinds if kind != "null"), "null" if kinds else None)
    if kind == "object" or (kind is None and "properties" in node):
        required = node.get("required")
        properties = _mapping(node.get("properties"))
        return {
            str(key): _witness(
                properties[str(key)]
                if str(key) in properties
                else node.get("additionalProperties")
            )
            for key in (
                cast(list[object], required) if isinstance(required, list) else []
            )
        }
    if kind == "array":
        return []
    if kind in ("number", "integer"):
        return 0
    if kind == "boolean":
        return False
    return None if kind == "null" else ""


def _accepts_witness(contract: FlowPersistedJsonObject) -> bool:
    """Whether the platform's validator (draft 2020-12) accepts the witness.

    Only called on a plain contract: no `$ref` keyword can be in it, so the
    validator resolves nothing.
    """

    try:
        validate_schema_syntax(contract, label="contract")
        validate_against_contract(_witness(contract), contract, label="witness")
    except TypedIOValidationException:
        return False
    return True


def template_bound_path_made_ok(
    schema: FlowPersistedJsonObject, path: tuple[str, ...]
) -> FlowPersistedJsonObject | None:
    """`schema` with `type` and `required` on `path` set so `template_bound_path_ok` holds.

    A path already ok is left alone. Otherwise the schema is edited only when
    the ENTIRE schema is plain: an assertion anywhere could interact with the
    edit. A type list of one non-null type (with or without "null") becomes
    that type and each key on the path joins its parent's `required`. The edit
    is kept only if a witness instance still validates against the result. None
    when the schema is not plain, a node has no single type or the witness
    fails. `schema` itself when it has no such path or the field is a
    container, which publication names.
    """

    contract = deepcopy(schema)
    nodes = [contract]
    for key in path:
        child = _mapping(nodes[-1].get("properties")).get(key)
        if not isinstance(child, dict):
            return schema
        nodes.append(cast(dict[str, object], child))
    if nodes[-1].get("type") in ("array", "object") or template_bound_path_ok(
        schema, path
    ):
        return schema
    if not _is_plain_tree(schema):
        return None
    for node, key in zip(nodes, path, strict=False):
        required = cast(list[object], node.setdefault("required", []))
        if not _narrowed_to(node, ("object",)):
            return None
        if key not in required:
            required.append(key)
    edited = _narrowed_to(nodes[-1], _FIELD_TYPES) and _accepts_witness(contract)
    return contract if edited else None


def _blank_remedy(contract: FlowPersistedJsonObject, path: tuple[str, ...]) -> str:
    """How the field says there is nothing to fill in, by its declared type alone."""

    node: object = contract
    for key in path:
        node = _mapping(_mapping(node).get("properties")).get(key)
    declared = _mapping(node).get("type")
    listed = cast(list[object], declared) if isinstance(declared, list) else [declared]
    kinds = {item for item in listed if isinstance(item, str) and item != "null"}
    if kinds and kinds <= {"number", "integer", "boolean"}:
        return (
            "the step always gives a valid value, and a deliberately blank "
            "template binding is the way to leave the placeholder empty."
        )
    return (
        "the step writes an empty string when there is nothing to say only if the "
        "field accepts one; otherwise it always gives a valid value, and a "
        "deliberately blank template binding leaves the placeholder empty."
    )


def _validate_template_binding_present(
    binding: str,
    *,
    placeholder: str,
    step_order: int,
    output_contracts_by_order: Mapping[int, FlowPersistedJsonObject | None],
    step_ref_mapping: Mapping[str, int],
) -> None:
    """Refuse a placeholder bound to a step field that is not a required field of one type.

    The fill step stops the run on null and on a key the step did not write,
    and treats "" as a deliberate omission. The Builder makes its own bound
    fields meet the rule; this is the rule for every other author.
    """

    source = template_binding_structured_source(
        binding, step_ref_mapping=step_ref_mapping
    )
    if source is None:
        return
    source_order, path = source
    contract = output_contracts_by_order.get(source_order)
    if contract is None or source_order >= step_order:
        return
    if not template_bound_path_ok(contract, path):
        field = ".".join(path)
        raise FlowStepValidationError(
            f"Step {step_order}: template binding '{placeholder}' reads '{field}' of "
            f"step {source_order}, which is not a required field of one type. A "
            "template field cannot be filled from a missing or null value. Declare "
            f"'{field}' as required with exactly one type (string, number, integer "
            "or boolean), and every object above it and the step's result as "
            f'type "object" listing it in required; {_blank_remedy(contract, path)}',
            context={"field": "output_config.bindings", "placeholder": placeholder},
            step_order=step_order,
        )


def _schema_is_scalar(schema: FlowPersistedJsonObject) -> bool:
    """Prove that a declared field excludes objects and arrays."""
    scalar_types = {"string", "number", "integer", "boolean", "null"}
    raw_type = schema.get("type")
    if isinstance(raw_type, str) and raw_type in scalar_types:
        return True
    if (
        isinstance(raw_type, list)
        and raw_type
        and all(
            isinstance(item, str) and item in scalar_types
            for item in cast(list[object], raw_type)
        )
    ):
        return True
    if "const" in schema and not isinstance(schema["const"], (dict, list)):
        return True
    values = schema.get("enum")
    if (
        isinstance(values, list)
        and values
        and all(
            not isinstance(value, (dict, list)) for value in cast(list[object], values)
        )
    ):
        return True
    for keyword in ("anyOf", "oneOf"):
        branches = schema.get(keyword)
        if (
            isinstance(branches, list)
            and branches
            and all(
                isinstance(branch, dict)
                and _schema_is_scalar(cast(FlowPersistedJsonObject, branch))
                for branch in cast(list[object], branches)
            )
        ):
            return True
    return False


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
        non_null_types = [item for item in declared if item != "null"]
        if len(non_null_types) == 1:
            return non_null_types[0]
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
    try:
        transcription_required = requires_audio_transcription(steps)
    except BadRequestException:
        # Step input validation already reports malformed runtime upload config.
        return
    if not transcription_required:
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


def _binding_reference_context(field: str, reference: str) -> dict[str, object]:
    return {"field": field, "reference": reference}


def _validate_binding_references(
    *,
    input_bindings: FlowPersistedJsonObject,
    current_step_order: int,
    available_orders: set[int],
    steps_by_order: dict[int, FlowStepValidationView],
    form_field_names: set[str],
    step_ref_mapping: dict[str, int],
    publish_strict: bool,
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
    question = question_binding(input_bindings)
    ordered_references: list[tuple[str, int | None, str]] = []
    question_step_paths: list[tuple[str, int | None, str]] = []
    if publish_strict and question is not None:
        for reference in analyze_template(
            question,
            step_refs=step_ref_mapping,
            form_field_names=form_field_names,
        ):
            if reference.path_error_code is not None:
                code = (
                    FlowGraphIssueCode.FLOW_INPUT_BINDING_INVALID_STEP_REFERENCE
                    if reference.path_error_code == "invalid_step_reference_format"
                    else FlowGraphIssueCode.FLOW_INPUT_BINDING_UNSUPPORTED_KEY
                )
                raise FlowStepValidationError(
                    f"Invalid input binding reference '{reference.expression}'.",
                    code=code.value,
                    context=(
                        _binding_reference_context(
                            "input_bindings.question", reference.expression
                        )
                        if code
                        is FlowGraphIssueCode.FLOW_INPUT_BINDING_INVALID_STEP_REFERENCE
                        else {
                            "field": "input_bindings.question",
                            "key": reference.expression,
                        }
                    ),
                    step_order=current_step_order,
                )
            if reference.kind is TemplateReferenceKind.UNKNOWN:
                raise FlowStepValidationError(
                    f"Invalid input binding reference '{reference.expression}'.",
                    code=FlowGraphIssueCode.FLOW_INPUT_BINDING_INVALID_STEP_REFERENCE.value,
                    context=_binding_reference_context(
                        "input_bindings.question", reference.expression
                    ),
                    step_order=current_step_order,
                )
            if reference.kind is TemplateReferenceKind.FORM_FIELD and reference.tail:
                raise FlowStepValidationError(
                    f"Unsupported input binding path '{reference.expression}'.",
                    code=FlowGraphIssueCode.FLOW_INPUT_BINDING_UNSUPPORTED_KEY.value,
                    context={
                        "field": "input_bindings.question",
                        "key": reference.expression,
                    },
                    step_order=current_step_order,
                )
            if reference.kind is not TemplateReferenceKind.STEP:
                continue
            if (
                reference.head in step_ref_mapping
                and runtime_step_alias_order(reference.head) is None
                and reference.tail
            ):
                raise FlowStepValidationError(
                    f"Invalid input binding reference '{reference.expression}'.",
                    code=FlowGraphIssueCode.FLOW_INPUT_BINDING_INVALID_STEP_REFERENCE.value,
                    context=_binding_reference_context(
                        "input_bindings.question", reference.expression
                    ),
                    step_order=current_step_order,
                )
            ordered_references.append(
                (
                    reference.expression,
                    reference.step_order,
                    "input_bindings.question",
                )
            )
            question_step_paths.append(
                (reference.expression, reference.step_order, reference.tail)
            )
    if publish_strict:
        for index, source_ref in enumerate(source_refs):
            referenced_order = source_ref_step_order(
                source_ref.step_ref, step_ref_mapping
            )
            ordered_references.append(
                (
                    source_ref.step_ref,
                    referenced_order,
                    f"input_bindings.source_refs[{index}].step_ref",
                )
            )
    for expression, referenced_order, field in ordered_references:
        context = _binding_reference_context(field, expression)
        if referenced_order is None:
            raise FlowStepValidationError(
                f"Invalid input binding reference '{expression}'.",
                code=FlowGraphIssueCode.FLOW_INPUT_BINDING_INVALID_STEP_REFERENCE.value,
                context=context,
                step_order=current_step_order,
            )
        if referenced_order >= current_step_order:
            raise FlowStepValidationError(
                f"Input binding reference '{expression}' must refer to an earlier step.",
                code=FlowGraphIssueCode.FLOW_INPUT_BINDING_FUTURE_STEP_REFERENCE.value,
                context=context,
                step_order=current_step_order,
            )
        if referenced_order not in available_orders:
            raise FlowStepValidationError(
                f"Input binding reference '{expression}' uses unknown step order {referenced_order}.",
                code=FlowGraphIssueCode.FLOW_INPUT_BINDING_UNKNOWN_STEP_ORDER.value,
                context=context,
                step_order=current_step_order,
            )
    for expression, referenced_order, tail in question_step_paths:
        if tail in {"", "output", "output.text"}:
            continue
        if tail == "output.structured":
            structured_path: tuple[str, ...] = ()
        elif tail.startswith("output.structured."):
            raw_path = tail.removeprefix("output.structured.")
            segments = tuple(segment.strip() for segment in raw_path.split("."))
            if not segments or any(not segment for segment in segments):
                raise FlowStepValidationError(
                    f"Unsupported input binding path '{expression}'.",
                    code=FlowGraphIssueCode.FLOW_INPUT_BINDING_UNSUPPORTED_KEY.value,
                    context={
                        "field": "input_bindings.question",
                        "key": expression,
                    },
                    step_order=current_step_order,
                )
            structured_path = segments
        else:
            raise FlowStepValidationError(
                f"Unsupported input binding path '{expression}'.",
                code=FlowGraphIssueCode.FLOW_INPUT_BINDING_UNSUPPORTED_KEY.value,
                context={
                    "field": "input_bindings.question",
                    "key": expression,
                },
                step_order=current_step_order,
            )
        referenced_step = (
            steps_by_order.get(referenced_order)
            if referenced_order is not None
            else None
        )
        if referenced_step is None or referenced_step.output_contract is None:
            raise FlowStepValidationError(
                f"Input binding path '{expression}' requires the referenced step to declare output_contract.",
                code=FlowGraphIssueCode.FLOW_INPUT_BINDING_UNSUPPORTED_KEY.value,
                context={
                    "field": "input_bindings.question",
                    "key": expression,
                },
                step_order=current_step_order,
            )
        _source_ref_schema(
            contract=referenced_step.output_contract,
            field_path=structured_path,
            current_step_order=current_step_order,
            path_label=f"input binding path '{expression}'",
            context={
                "field": "input_bindings.question",
                "key": expression,
            },
        )
    if publish_strict:
        return

    # A template head is read by the template grammar, a source ref's step_ref
    # by the source-ref grammar: they differ on purpose.
    expressions: list[tuple[str, str, Callable[[str], int | None]]] = [
        (reference.expression, "input_bindings.question", runtime_step_alias_order)
        for reference in analyze_template(
            question or "",
            step_refs={},
            form_field_names=set(),
        )
    ]
    expressions.extend(
        (
            source_ref.step_ref,
            f"input_bindings.source_refs[{index}].step_ref",
            source_ref_step_order,
        )
        for index, source_ref in enumerate(source_refs)
    )
    for expression, field, read_order in expressions:
        if expression.startswith("step_input"):
            continue
        if not expression.startswith("step_"):
            continue

        context = _binding_reference_context(field, expression)
        head = expression.split(".", maxsplit=1)[0]
        referenced_order = read_order(head)
        if referenced_order is None:
            raise FlowStepValidationError(
                f"Invalid step reference '{head}' in input bindings.",
                code=FlowGraphIssueCode.FLOW_INPUT_BINDING_INVALID_STEP_REFERENCE.value,
                context=context,
                step_order=current_step_order,
            )

        if referenced_order >= current_step_order:
            raise FlowStepValidationError(
                "Input bindings may only reference outputs from earlier steps.",
                code=FlowGraphIssueCode.FLOW_INPUT_BINDING_FUTURE_STEP_REFERENCE.value,
                context=context,
                step_order=current_step_order,
            )
        if referenced_order not in available_orders:
            raise FlowStepValidationError(
                f"Input binding references unknown step order: {referenced_order}.",
                code=FlowGraphIssueCode.FLOW_INPUT_BINDING_UNKNOWN_STEP_ORDER.value,
                context=context,
                step_order=current_step_order,
            )


def _validate_source_ref_contracts(
    *,
    step: FlowStepValidationView,
    steps_by_order: dict[int, FlowStepValidationView],
    step_ref_mapping: dict[str, int],
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

    if is_structured_projection_binding(
        input_bindings=step.input_bindings,
        input_type=step.input_type,
    ):
        if step.input_contract is None:
            raise FlowStepValidationError(
                f"Step {step.step_order}: structured JSON source_refs require "
                "input_contract.",
                code=FlowGraphIssueCode.FLOW_INPUT_CONTRACT_INAPPLICABLE.value,
                context={
                    "step_order": step.step_order,
                    "field": "input_contract",
                    "conflict": "input_bindings.source_refs",
                },
                step_order=step.step_order,
            )
        source_contracts_by_step_ref: dict[str, FlowPersistedJsonObject] = {}
        for ref in source_refs:
            referenced_step = _referenced_step_for_source_ref(
                ref_step=ref.step_ref,
                steps_by_order=steps_by_order,
                step_ref_mapping=step_ref_mapping,
            )
            if referenced_step is None or referenced_step.output_contract is None:
                raise FlowStepValidationError(
                    f"Step {step.step_order}: structured JSON source_ref "
                    f"'{ref.step_ref}' requires a producer output_contract.",
                    code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
                    context={"field": "input_bindings", "key": "source_refs"},
                    step_order=step.step_order,
                )
            source_contracts_by_step_ref[ref.step_ref] = referenced_step.output_contract
        try:
            projected_contract = derive_structured_projection_contract(
                input_bindings=step.input_bindings,
                source_contracts_by_step_ref=source_contracts_by_step_ref,
            )
        except InputBindingContractError as exc:
            raise FlowStepValidationError(
                f"Step {step.step_order}: {exc}",
                code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
                context={"field": "input_bindings", "key": "source_refs"},
                step_order=step.step_order,
            ) from exc
        if projected_contract != step.input_contract:
            raise FlowStepValidationError(
                f"Step {step.step_order}: input_contract does not match the exact "
                "structured source_ref projection.",
                code=FlowGraphIssueCode.FLOW_INPUT_CONTRACT_INAPPLICABLE.value,
                context={
                    "step_order": step.step_order,
                    "field": "input_contract",
                    "conflict": "input_bindings.source_refs",
                },
                step_order=step.step_order,
            )
        return

    for ref in source_refs:
        if "*" in ref.field_path:
            raise FlowStepValidationError(
                f"Step {step.step_order}: source_ref field_path '{'.'.join(ref.field_path)}': "
                "wildcards require a structured JSON projection.",
                code=FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
                context={"field": "input_bindings", "key": "source_refs"},
                step_order=step.step_order,
            )

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
            step_ref_mapping=step_ref_mapping,
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
            path_label=f"source_ref field_path '{'.'.join(ref.field_path)}'",
            context={"field": "input_bindings", "key": "source_refs"},
        )
        target_type = _schema_type_hint(target_schema)
        if target_type == "array":
            raw_items = target_schema.get("items")
            if (
                ref.item_template is None
                and ref.field_path
                and isinstance(raw_items, dict)
                and _schema_type_hint(cast(FlowPersistedJsonObject, raw_items))
                in {"string", "number", "integer", "boolean", "null"}
            ):
                continue
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
        if target_type != "string" and not (
            ref.field_path
            and target_type in {"number", "integer", "boolean", "object", "null"}
        ):
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
    step_ref_mapping: dict[str, int],
) -> FlowStepValidationView | None:
    step_order = source_ref_step_order(ref_step, step_ref_mapping)
    return steps_by_order.get(step_order) if step_order is not None else None


def _source_ref_schema(
    *,
    contract: FlowPersistedJsonObject,
    field_path: tuple[str, ...],
    current_step_order: int,
    path_label: str,
    context: dict[str, object],
    error_code: str | None = FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
) -> FlowPersistedJsonObject:
    current: FlowPersistedJsonObject = contract
    for segment in field_path:
        if _schema_type_hint(current) != "object":
            raise FlowStepValidationError(
                f"Step {current_step_order}: {path_label} does not resolve through an object contract.",
                code=error_code,
                context=context,
                step_order=current_step_order,
            )
        raw_properties = current.get("properties")
        if not isinstance(raw_properties, dict):
            raise FlowStepValidationError(
                f"Step {current_step_order}: {path_label} references a contract without object properties.",
                code=error_code,
                context=context,
                step_order=current_step_order,
            )
        properties = cast(dict[str, object], raw_properties)
        next_schema = properties.get(segment)
        if not isinstance(next_schema, dict):
            raise FlowStepValidationError(
                f"Step {current_step_order}: {path_label} references unknown field '{segment}'.",
                code=error_code,
                context=context,
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


def _validate_step_input_configuration(*, step: FlowStepValidationView) -> None:
    _validate_runtime_input_publish_rules(step=step)
    _validate_step_mapped_execution(step=step)


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

    try:
        question_binding = effective_question_binding(bindings)
    except InputBindingContractError:
        return
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
                code=FlowGraphIssueCode.FLOW_INPUT_BINDING_RUNTIME_INPUT_UNUSED.value,
            )


def takes_runtime_files(input_config: FlowPersistedJsonObject | None) -> bool:
    """Whether a step's config asks the run for uploaded files (a malformed
    config is reported by the step validation, so it takes none here)."""

    try:
        return build_runtime_input_config(input_config).enabled
    except BadRequestException:
        return False


def flow_run_input(
    *,
    form_fields: bool,
    step_input_configs: Sequence[FlowPersistedJsonObject | None],
) -> FlowRunInput:
    """What a flow's run form collects: the run contract's form fields and the
    steps that take uploaded files."""

    return FlowRunInput(
        form_fields=form_fields,
        runtime_files=any(takes_runtime_files(config) for config in step_input_configs),
    )


def run_input_alias_refusal(
    expression: str, run_input: FlowRunInput, *, takes_upload: bool
) -> str:
    """The refusal of a read of free-text run input on a flow whose run form
    collects only fields or uploads; ``takes_upload`` is whether the reading
    step is the one taking the upload."""

    if run_input.form_fields:
        collects = "only its form fields"
        instead = (
            "Read a field with {{ flow_input.<field> }}, or remove the form fields "
            "so the run takes free text."
        )
    else:
        collects = "only uploaded files"
        instead = (
            "Read the upload with {{ step_input.text }}."
            if takes_upload
            else "Read an earlier step's output instead."
        )
    return (
        f"'{{{{ {expression} }}}}' reads the run's free-text input, but this flow's "
        f"run collects {collects}. The run dialog and the documented run contract "
        "supply only the declared form fields (and uploads), so publish refuses a "
        f"step that reads run text on such a flow. {instead}"
    )


def _validate_run_input_alias_reads(
    *, step: FlowStepValidationView, run_input: FlowRunInput
) -> None:
    """Refuse at publish a read of free-text run input on a flow whose run form
    declares only fields or uploads."""

    if run_input.free_text:
        return
    sites = [
        ("input_bindings.question", question_binding(step.input_bindings)),
        ("prompt", step.prompt_template),
        ("output_config", _template_text(step.output_config)),
    ]
    if step.input_source == "http_get":
        # The fetch's URL, headers and body are interpolated with the run
        # context like a question is.
        sites.append(("input_config", _template_text(step.input_config)))
    for field, template in sites:
        for expression in iter_template_expressions(template or ""):
            if reads_unreceived_run_input(expression, run_input):
                raise FlowStepValidationError(
                    f"Step {step.step_order}: "
                    + run_input_alias_refusal(
                        expression,
                        run_input,
                        takes_upload=takes_runtime_files(step.input_config),
                    ),
                    code=FlowGraphIssueCode.FLOW_INPUT_ALIAS_NOT_RECEIVED.value,
                    context=_binding_reference_context(field, expression),
                    step_order=step.step_order,
                )


def _template_text(config: FlowPersistedJsonObject | None) -> str | None:
    return json.dumps(config, ensure_ascii=False) if config else None


def _validate_section_source_reads(
    *,
    step: FlowStepValidationView,
    steps_by_order: dict[int, FlowStepValidationView],
    step_ref_mapping: dict[str, int],
) -> None:
    """Refuse at publish the structured source section processing refuses at run.

    Which steps are read is the runtime's selection rule; whether one yields
    structured output is its output format's rule, the one the runtime writes by.
    """
    try:
        if text_processing_config(step.input_config) is None:
            return
        question = question_binding(step.input_bindings)
        source_refs = source_ref_bindings(step.input_bindings)
    except (ValidationError, InputBindingContractError):
        return  # the mapped-execution and binding checks report these
    # (field, template, reported reference) for each authored place a read
    # comes from; source_refs are named by their step_ref as authored.
    authored: list[tuple[str, str | None, str | None]] = [
        ("input_bindings.question", question, None),
        *(
            (
                f"input_bindings.source_refs[{index}].step_ref",
                ref.template_expression(),
                ref.step_ref,
            )
            for index, ref in enumerate(source_refs)
        ),
        ("prompt", step.prompt_template, None),
    ]
    reads: list[tuple[str, str, int]] = []
    for field, template, authored_reference in authored:
        for reference in analyze_template(
            template or "", step_refs=step_ref_mapping, form_field_names=set()
        ):
            order = selected_source_step_order(
                reference, step_order=step.step_order, section_processing=True
            )
            if order is not None:
                reads.append((field, authored_reference or reference.expression, order))
    if question is None and not source_refs:
        reads.extend(
            ("input_source", str(_enum_value(step.input_source)), order)
            for order in resolve_upstream_step_orders(
                input_source=step.input_source,
                step_order=step.step_order,
                binding_references=None,
                max_prior_step_order=step.step_order - 1,
            )
        )
    for field, reference, source_order in reads:
        source = steps_by_order.get(source_order)
        if source is None or not _yields_structured_output(source):
            continue
        raise FlowStepValidationError(
            f"Step {step.step_order}: section processing reads text, but "
            f"'{reference}' reads step {source_order}, whose output is structured, not text.",
            code=FlowGraphIssueCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value,
            context={
                "field": field,
                "reference": reference,
                "source_step_order": source_order,
            },
            step_order=step.step_order,
        )


def _yields_structured_output(step: FlowStepValidationView) -> bool:
    try:
        spec = resolve_format_spec(str(_enum_value(step.output_type)))
    except TypedIOValidationException:
        return False  # the enum check reports an unknown output_type
    return spec.requests_structured_output(step.output_contract)


def _validate_step_mapped_execution(*, step: FlowStepValidationView) -> None:
    try:
        mapped_execution = resolve_step_mapped_execution(
            input_source=step.input_source,
            input_type=step.input_type,
            output_mode=step.output_mode,
            output_type=step.output_type,
            input_config=step.input_config,
        )
    except FlowStepMappedExecutionConfigurationError as exc:
        raise FlowStepValidationError(
            f"Step {step.step_order}: {exc}",
            step_order=step.step_order,
            code=FlowGraphIssueCode.FLOW_STEP_INVALID.value,
        ) from exc

    if text_processing_config(step.input_config) is not None:
        if single_mapped_array_key(step.output_contract) is None:
            raise FlowStepValidationError(
                f"Step {step.step_order}: section processing requires exactly one authored array of objects.",
                step_order=step.step_order,
                code=FlowGraphIssueCode.FLOW_STEP_INVALID.value,
            )
    if mapped_execution is None:
        return
    if mapped_execution.execution_mode == "per_item" and has_explicit_underlag(
        step.input_bindings
    ):
        raise FlowStepValidationError(
            f"Step {step.step_order}: item_map reads the previous step's items; "
            "explicit input_bindings are not supported on a mapped step.",
            step_order=step.step_order,
        )
    if mapped_execution.maximum_items is not None:
        return
    if mapped_execution.execution_mode == "per_source":
        raise FlowStepValidationError(
            f"Step {step.step_order}: per_source runtime input requires an explicit max_files ceiling.",
            step_order=step.step_order,
        )
    raise FlowStepValidationError(
        f"Step {step.step_order}: enabled item_map requires an explicit max_items ceiling.",
        step_order=step.step_order,
    )
