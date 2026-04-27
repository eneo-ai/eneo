from __future__ import annotations

from enum import Enum
from typing import Any, cast
from uuid import UUID

from intric.database.tables.flow_tables import (
    FLOW_STEP_INPUT_TYPE_VALUES,
    FLOW_STEP_OUTPUT_TYPE_VALUES,
)
from intric.flows.domain.flow import JsonObject
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
            raw_input_config = _optional_json_object(cast(object, raw_input_config_raw))
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
        raw_output_config = _optional_json_object(cast(object, raw_output_config_raw))
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
            step_order_value = item_dict["step_order"]
            step_order = (
                step_order_value
                if isinstance(step_order_value, int)
                and not isinstance(step_order_value, bool)
                else int(str(step_order_value))
            )
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
        user_description_raw: object = item_dict.get("user_description")
        plan_step_ref_raw: object = item_dict.get("plan_step_ref")
        existing_step_ref_raw: object = item_dict.get("existing_step_ref")
        input_bindings = _optional_json_object(item_dict.get("input_bindings"))
        output_contract = _optional_json_object(item_dict.get("output_contract"))
        input_contract = _optional_json_object(item_dict.get("input_contract"))
        assistant_snapshot = _optional_json_object(item_dict.get("assistant_snapshot"))
        parsed.append(
            RuntimeStep(
                step_id=step_id,
                step_order=step_order,
                assistant_id=assistant_id,
                user_description=str(user_description_raw).strip()
                if isinstance(user_description_raw, str)
                else None,
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
