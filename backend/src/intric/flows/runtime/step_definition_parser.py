from __future__ import annotations

from typing import Any
from uuid import UUID

from intric.database.tables.flow_tables import (
    FLOW_STEP_INPUT_TYPE_VALUES,
    FLOW_STEP_OUTPUT_TYPE_VALUES,
)
from intric.flows.output_modes import ALLOWED_OUTPUT_MODES, transcribe_only_violation
from intric.flows.runtime.models import RuntimeStep
from intric.flows.step_chain_rules import find_first_step_chain_violation
from intric.main.exceptions import BadRequestException

ALLOWED_INPUT_SOURCES = {"flow_input", "previous_step", "all_previous_steps", "http_get", "http_post"}
ALLOWED_INPUT_TYPES = set(FLOW_STEP_INPUT_TYPE_VALUES)
ALLOWED_OUTPUT_TYPES = set(FLOW_STEP_OUTPUT_TYPE_VALUES)


def parse_runtime_steps(definition_json: dict[str, Any]) -> list[RuntimeStep]:
    steps = definition_json.get("steps")
    if not isinstance(steps, list):
        raise BadRequestException("Flow definition snapshot is missing steps.")
    parsed: list[RuntimeStep] = []
    for item in steps:
        if not isinstance(item, dict):
            raise BadRequestException("Invalid step definition in flow snapshot.")
        input_source = str(item.get("input_source", "flow_input"))
        if input_source not in ALLOWED_INPUT_SOURCES:
            raise BadRequestException(f"Unsupported input source '{input_source}'.")
        raw_input_config = item.get("input_config")
        if input_source in {"http_get", "http_post"}:
            if not isinstance(raw_input_config, dict):
                raise BadRequestException("HTTP input source requires input_config object.")
            raw_headers = raw_input_config.get("headers")
            if raw_headers is not None and not isinstance(raw_headers, dict):
                raise BadRequestException("HTTP input_config.headers must be an object.")
        elif raw_input_config is not None and not isinstance(raw_input_config, dict):
            raise BadRequestException("Step input_config must be an object.")
        output_mode = str(item.get("output_mode", "pass_through"))
        if output_mode not in ALLOWED_OUTPUT_MODES:
            raise BadRequestException(f"Unsupported output mode '{output_mode}'.")
        output_type = str(item.get("output_type", "text"))
        input_type = str(item.get("input_type", "text"))
        if input_type not in ALLOWED_INPUT_TYPES:
            raise BadRequestException(f"Unsupported input type '{input_type}'.")
        if output_type not in ALLOWED_OUTPUT_TYPES:
            raise BadRequestException(f"Unsupported output type '{output_type}'.")
        raw_output_config = item.get("output_config")
        if raw_output_config is not None and not isinstance(raw_output_config, dict):
            raise BadRequestException("Webhook output_config must be an object.")
        if isinstance(raw_output_config, dict):
            if output_mode == "template_fill":
                bindings = raw_output_config.get("bindings")
                if not isinstance(bindings, dict):
                    raise BadRequestException("Template fill output_config.bindings must be an object.")
                if "template_file_id" not in raw_output_config:
                    raise BadRequestException(
                        "Template fill output_config.template_file_id is required."
                    )
                if output_type != "docx":
                    raise BadRequestException(
                        "Template fill output_mode requires output_type 'docx'."
                    )
            else:
                raw_headers = raw_output_config.get("headers")
                if raw_headers is not None and not isinstance(raw_headers, dict):
                    raise BadRequestException("Webhook output_config.headers must be an object.")
        try:
            step_id = UUID(str(item["step_id"]))
            assistant_id = UUID(str(item["assistant_id"]))
            step_order = int(item["step_order"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BadRequestException("Invalid step identifiers in flow snapshot.") from exc
        transcribe_only_error = transcribe_only_violation(
            step_order=step_order,
            input_type=input_type,
            output_type=output_type,
            output_mode=output_mode,
        )
        if transcribe_only_error is not None:
            raise BadRequestException(transcribe_only_error)
        parsed.append(
            RuntimeStep(
                step_id=step_id,
                step_order=step_order,
                assistant_id=assistant_id,
                user_description=str(item.get("user_description")).strip()
                if isinstance(item.get("user_description"), str)
                else None,
                input_source=input_source,
                input_bindings=item.get("input_bindings"),
                input_config=raw_input_config,
                output_mode=output_mode,
                output_config=raw_output_config,
                output_type=output_type,
                output_contract=item.get("output_contract"),
                input_type=input_type,
                input_contract=item.get("input_contract"),
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
