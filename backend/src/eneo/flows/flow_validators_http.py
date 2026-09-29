from __future__ import annotations

from collections.abc import Sequence

from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.domain.flow_step_validation import (
    FlowGraphIssueCode,
    FlowStepValidationError,
    FlowStepValidationView,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.http_transport import (
    credential_template_message,
    parse_authored_http_config,
    secret_fields_holding_templates,
    validate_authored_config,
)
from eneo.main.config import get_settings
from eneo.main.exceptions import TypedIOValidationException


def validate_http_input_config(*, step: FlowStepValidationView) -> None:
    if step.input_type in {"document", "file", "image", "audio"}:
        raise FlowStepValidationError(
            f"Step {step.step_order}: input_type '{step.input_type}' is not supported with input_source '{step.input_source}'.",
            step_order=step.step_order,
        )
    validate_http_config(
        step_order=step.step_order,
        label="input_config",
        config=step.input_config,
        method="GET",
        direction="input",
    )


def validate_http_output_config(*, step: FlowStepValidationView) -> None:
    validate_http_config(
        step_order=step.step_order,
        label="output_config",
        config=step.output_config,
        method="POST",
        direction="output",
    )


def validate_http_config(
    *,
    step_order: int,
    label: str,
    config: FlowPersistedJsonObject | None,
    method: str,
    direction: str,
) -> None:
    validate_authored_http_config(
        step_order=step_order,
        label=label,
        config=config,
        method=method,
        direction=direction,
    )


def validate_authored_http_config(
    *,
    step_order: int,
    label: str,
    config: object,
    method: str,
    direction: str,
) -> None:
    max_timeout = float(get_settings().flow_http_max_timeout_seconds)
    try:
        authored = parse_authored_http_config(
            config, step_order=step_order, config_label=label
        )
    except TypedIOValidationException as exc:
        raise FlowStepValidationError(
            str(exc), step_order=step_order, code=exc.code, context=exc.context
        ) from None
    errors = validate_authored_config(
        authored, direction=direction, method=method, max_timeout=max_timeout
    )
    if errors:
        raise FlowStepValidationError(
            f"Step {step_order}: {label} validation failed: {errors[0].value}",
            step_order=step_order,
            code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
            context={"field": label},
        )
    templated = secret_fields_holding_templates(authored)
    if templated:
        raise credential_template_error(
            step_order=step_order, label=label, fields=templated
        )


def credential_template_error(
    *, step_order: int, label: str, fields: Sequence[str]
) -> FlowStepValidationError:
    return FlowStepValidationError(
        credential_template_message(step_order=step_order, label=label, fields=fields),
        step_order=step_order,
        code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
        context={
            "issue_code": FlowGraphIssueCode.FLOW_STEP_INVALID.value,
            "step_order": step_order,
            "field": f"{label}.{fields[0]}",
        },
    )
