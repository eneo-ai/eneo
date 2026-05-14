from __future__ import annotations

from enum import Enum
from typing import Any, cast
from uuid import UUID

from intric.database.tables.flow_tables import (
    FLOW_STEP_INPUT_TYPE_VALUES,
    FLOW_STEP_OUTPUT_TYPE_VALUES,
)
from intric.flows.domain.flow import JsonObject
from intric.flows.enums import FlowOutputMode
from intric.flows.flow_review_policy import parse_flow_step_review_policy
from intric.flows.output_modes import ALLOWED_OUTPUT_MODES, transcribe_only_violation
from intric.flows.runtime.models import RuntimeStep
from intric.flows.runtime_input import build_runtime_input_config
from intric.flows.step_chain_rules import find_first_step_chain_violation
from intric.main.exceptions import BadRequestException

ALLOWED_INPUT_SOURCES = {
    "flow_input",
    "previous_step",
    "all_previous_steps",
    "http_get",
    "http_post",
}
ALLOWED_INPUT_TYPES = set(FLOW_STEP_INPUT_TYPE_VALUES)
ALLOWED_OUTPUT_TYPES = set(FLOW_STEP_OUTPUT_TYPE_VALUES)


def _optional_json_object(value: object) -> JsonObject | None:
    return cast(JsonObject, value) if isinstance(value, dict) else None


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadRequestException(f"{field_name} must be an integer.")
    if value <= 0:
        raise BadRequestException(f"{field_name} must be greater than zero.")
    return value


def _step_scoped_message(
    *,
    step_order: int,
    user_description: str | None,
    message: str,
) -> str:
    step_label = f"Step {step_order}"
    if user_description:
        step_label = f"{step_label} ({user_description})"
    exact_step_prefix = f"Step {step_order}: "
    if message.startswith(exact_step_prefix):
        field_message = message.removeprefix(exact_step_prefix)
    else:
        field_message = message.removeprefix("Step ")
    return f"{step_label}: {field_message}"


def _step_scoped_exception(
    exc: BadRequestException,
    *,
    step_order: int,
    user_description: str | None,
) -> BadRequestException:
    context = dict(exc.context or {})
    context["step_order"] = step_order
    if user_description is not None:
        context["step_description"] = user_description
    return BadRequestException(
        _step_scoped_message(
            step_order=step_order,
            user_description=user_description,
            message=str(exc),
        ),
        code=exc.code,
        context=context,
    )


def _step_order_from_snapshot(item_dict: dict[str, object]) -> int:
    step_order_value = item_dict["step_order"]
    if isinstance(step_order_value, int) and not isinstance(step_order_value, bool):
        return step_order_value
    return int(str(step_order_value))


def _optional_step_description(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def parse_runtime_steps(definition_json: dict[str, Any]) -> list[RuntimeStep]:
    steps = definition_json.get("steps")
    if not isinstance(steps, list):
        raise BadRequestException("Flow definition snapshot is missing steps.")
    steps_list = cast(list[Any], steps)
    parsed: list[RuntimeStep] = []
    for item in steps_list:
        if not isinstance(item, dict):
            raise BadRequestException("Invalid step definition in flow snapshot.")
        item_dict = cast(dict[str, object], item)
        user_description = _optional_step_description(item_dict.get("user_description"))
        try:
            step_order = _step_order_from_snapshot(item_dict)
        except (KeyError, TypeError, ValueError) as exc:
            raise BadRequestException(
                "Invalid step identifiers in flow snapshot."
            ) from exc
        try:
            input_source = _enum_value(item_dict.get("input_source", "flow_input"))
            if input_source not in ALLOWED_INPUT_SOURCES:
                raise BadRequestException(f"Unsupported input source '{input_source}'.")
            raw_input_config_raw: object = item_dict.get("input_config")
            if input_source in {"http_get", "http_post"}:
                if not isinstance(raw_input_config_raw, dict):
                    raise BadRequestException(
                        "HTTP input source requires input_config object."
                    )
                raw_input_config = cast(JsonObject, raw_input_config_raw)
                raw_headers = raw_input_config.get("headers")
                if raw_headers is not None and not isinstance(raw_headers, dict):
                    raise BadRequestException(
                        "HTTP input_config.headers must be an object."
                    )
            elif raw_input_config_raw is not None and not isinstance(
                raw_input_config_raw, dict
            ):
                raise BadRequestException("Step input_config must be an object.")
            else:
                raw_input_config = _optional_json_object(
                    cast(object, raw_input_config_raw)
                )
            build_runtime_input_config(raw_input_config)
            output_mode = _enum_value(item_dict.get("output_mode", "pass_through"))
            if output_mode not in ALLOWED_OUTPUT_MODES:
                raise BadRequestException(f"Unsupported output mode '{output_mode}'.")
            output_type = _enum_value(item_dict.get("output_type", "text"))
            input_type = _enum_value(item_dict.get("input_type", "text"))
            if input_type not in ALLOWED_INPUT_TYPES:
                raise BadRequestException(f"Unsupported input type '{input_type}'.")
            if output_type not in ALLOWED_OUTPUT_TYPES:
                raise BadRequestException(f"Unsupported output type '{output_type}'.")
            raw_output_config_raw: object = item_dict.get("output_config")
            if raw_output_config_raw is not None and not isinstance(
                raw_output_config_raw, dict
            ):
                raise BadRequestException("Webhook output_config must be an object.")
            raw_output_config = _optional_json_object(
                cast(object, raw_output_config_raw)
            )
            output_classification_override_raw: object = item_dict.get(
                "output_classification_override"
            )
            output_classification_override = (
                output_classification_override_raw
                if isinstance(output_classification_override_raw, int)
                else None
            )
            if isinstance(raw_output_config, dict):
                if output_mode == "template_fill":
                    bindings = raw_output_config.get("bindings")
                    if not isinstance(bindings, dict):
                        raise BadRequestException(
                            "Template fill output_config.bindings must be an object."
                        )
                    if (
                        "template_asset_id" not in raw_output_config
                        and "template_file_id" not in raw_output_config
                    ):
                        raise BadRequestException(
                            "Template fill output_config.template_asset_id or template_file_id is required."
                        )
                    if output_type != "docx":
                        raise BadRequestException(
                            "Template fill output_mode requires output_type 'docx'."
                        )
                else:
                    raw_headers = raw_output_config.get("headers")
                    if raw_headers is not None and not isinstance(raw_headers, dict):
                        raise BadRequestException(
                            "Webhook output_config.headers must be an object."
                        )
            try:
                step_id = UUID(str(item_dict["step_id"]))
                assistant_id = UUID(str(item_dict["assistant_id"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise BadRequestException(
                    "Invalid step identifiers in flow snapshot."
                ) from exc
            transcribe_only_error = transcribe_only_violation(
                step_order=step_order,
                input_type=input_type,
                output_type=output_type,
                output_mode=output_mode,
            )
            if transcribe_only_error is not None:
                raise BadRequestException(transcribe_only_error)
            runtime_input = build_runtime_input_config(raw_input_config)
            if (
                output_mode == "transcribe_only"
                and runtime_input.enabled
                and runtime_input.input_format != "audio"
            ):
                raise BadRequestException(
                    "Transcribe-only steps require runtime_input.input_format 'audio'."
                )
            review_policy = parse_flow_step_review_policy(
                raw_policy=item_dict.get("review_policy"),
                output_mode=FlowOutputMode(output_mode),
            )
            plan_step_ref_raw: object = item_dict.get("plan_step_ref")
            existing_step_ref_raw: object = item_dict.get("existing_step_ref")
            input_bindings = _optional_json_object(item_dict.get("input_bindings"))
            output_contract = _optional_json_object(item_dict.get("output_contract"))
            input_contract = _optional_json_object(item_dict.get("input_contract"))
            assistant_snapshot = _optional_json_object(
                item_dict.get("assistant_snapshot")
            )
            timeout_seconds = _optional_positive_int(
                item_dict.get("timeout_seconds"),
                "timeout_seconds",
            )
        except BadRequestException as exc:
            raise _step_scoped_exception(
                exc,
                step_order=step_order,
                user_description=user_description,
            ) from exc
        parsed.append(
            RuntimeStep(
                step_id=step_id,
                step_order=step_order,
                assistant_id=assistant_id,
                user_description=user_description,
                plan_step_ref=str(plan_step_ref_raw).strip()
                if isinstance(plan_step_ref_raw, str) and str(plan_step_ref_raw).strip()
                else None,
                existing_step_ref=str(existing_step_ref_raw).strip()
                if isinstance(existing_step_ref_raw, str)
                and str(existing_step_ref_raw).strip()
                else None,
                input_source=input_source,
                input_bindings=input_bindings,
                input_config=raw_input_config,
                output_mode=output_mode,
                output_config=raw_output_config,
                output_classification_override=output_classification_override,
                output_type=output_type,
                output_contract=output_contract,
                input_type=input_type,
                input_contract=input_contract,
                assistant_snapshot=assistant_snapshot,
                review_policy=review_policy,
                timeout_seconds=timeout_seconds,
            )
        )
    step_orders = [step.step_order for step in parsed]
    if len(step_orders) != len(set(step_orders)):
        raise BadRequestException("Duplicate step_order detected in flow snapshot.")
    expected_orders = list(range(1, len(parsed) + 1))
    if step_orders != expected_orders:
        raise BadRequestException("Step order must be contiguous and start at 1.")
    chain_violation = find_first_step_chain_violation(parsed)
    if chain_violation is not None:
        raise BadRequestException(chain_violation.message)
    return parsed


def _enum_value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)
