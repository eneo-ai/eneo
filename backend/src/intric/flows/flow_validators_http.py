from __future__ import annotations

from typing import Any

from intric.flows.domain.flow import FlowStep, JsonObject
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException


def validate_http_input_config(*, step: FlowStep) -> None:
    if step.input_type in {"document", "file", "image", "audio"}:
        raise BadRequestException(
            f"Step {step.step_order}: input_type '{step.input_type}' is not supported with input_source '{step.input_source}'."
        )
    method = "GET" if step.input_source == "http_get" else "POST"
    validate_http_config_dispatch(
        step_order=step.step_order,
        label="input_config",
        config=step.input_config,
        method=method,
        direction="input",
    )
    if isinstance(step.input_config, dict) and step.input_source == "http_get":
        if "body_template" in step.input_config or "body_json" in step.input_config:
            raise BadRequestException(
                f"Step {step.step_order}: input_config body fields are only allowed for input_source 'http_post'."
            )


def validate_http_output_config(*, step: FlowStep) -> None:
    validate_http_config_dispatch(
        step_order=step.step_order,
        label="output_config",
        config=step.output_config,
        method="POST",
        direction="output",
    )


def validate_http_config_dispatch(
    *,
    step_order: int,
    label: str,
    config: JsonObject | None,
    method: str,
    direction: str,
) -> None:
    from intric.flows.http_transport import is_authored_config as _is_authored

    if isinstance(config, dict) and _is_authored(config):
        validate_authored_http_config(
            step_order=step_order,
            label=label,
            config=config,
            method=method,
            direction=direction,
        )
    else:
        validate_http_config_common(
            step_order=step_order,
            label=label,
            config=config,
            method=f"http_{method.lower()}" if method in ("GET", "POST") else method,
        )


def validate_authored_http_config(
    *,
    step_order: int,
    label: str,
    config: dict[str, Any],
    method: str,
    direction: str,
) -> None:
    from intric.flows.http_transport import HttpAuthoredConfig, validate_authored_config

    max_timeout = float(get_settings().flow_http_max_timeout_seconds)
    try:
        authored = HttpAuthoredConfig.model_validate(config)
    except Exception as exc:
        raise BadRequestException(
            f"Step {step_order}: {label} is not a valid HTTP config: {exc}"
        ) from exc
    errors = validate_authored_config(
        authored, direction=direction, method=method, max_timeout=max_timeout
    )
    if errors:
        raise BadRequestException(
            f"Step {step_order}: {label} validation failed: {errors[0].value}"
        )


def validate_http_config_common(
    *,
    step_order: int,
    label: str,
    config: JsonObject | None,
    method: str,
) -> None:
    if not isinstance(config, dict):
        raise BadRequestException(
            f"Step {step_order}: {label} must be an object when using HTTP {method}."
        )
    url_value = config.get("url")
    if not isinstance(url_value, str) or not url_value.strip():
        raise BadRequestException(
            f"Step {step_order}: {label}.url is required for HTTP {method}."
        )
    headers = config.get("headers")
    if headers is not None and not isinstance(headers, dict):
        raise BadRequestException(
            f"Step {step_order}: {label}.headers must be an object."
        )
    timeout_value = config.get("timeout_seconds")
    if timeout_value is not None:
        if not isinstance(timeout_value, (int, float)):
            raise BadRequestException(
                f"Step {step_order}: {label}.timeout_seconds must be a number."
            )
        if timeout_value <= 0:
            raise BadRequestException(
                f"Step {step_order}: {label}.timeout_seconds must be greater than zero."
            )
        max_timeout = float(get_settings().flow_http_max_timeout_seconds)
        if float(timeout_value) > max_timeout:
            raise BadRequestException(
                f"Step {step_order}: {label}.timeout_seconds cannot exceed {max_timeout:g}."
            )
    response_format = config.get("response_format")
    if response_format is not None and str(response_format) not in {"text", "json"}:
        raise BadRequestException(
            f"Step {step_order}: {label}.response_format must be 'text' or 'json'."
        )
    body_template = config.get("body_template")
    if body_template is not None and not isinstance(body_template, str):
        raise BadRequestException(
            f"Step {step_order}: {label}.body_template must be a string."
        )
    body_json = config.get("body_json")
    if body_json is not None and not isinstance(body_json, (dict, list)):
        raise BadRequestException(
            f"Step {step_order}: {label}.body_json must be an object or array."
        )
    if body_template is not None and body_json is not None:
        raise BadRequestException(
            f"Step {step_order}: {label} cannot define both body_template and body_json."
        )
