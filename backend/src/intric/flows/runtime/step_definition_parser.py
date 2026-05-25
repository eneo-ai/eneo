from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, TypeGuard, cast
from uuid import UUID

from intric.database.tables.flow_tables import (
    FLOW_STEP_INPUT_TYPE_VALUES,
    FLOW_STEP_OUTPUT_TYPE_VALUES,
)
from intric.flows.domain.flow import JsonObject
from intric.flows.enums import FlowOutputMode
from intric.flows.flow_review_policy import parse_flow_step_review_policy
from intric.flows.input_binding_contract_rules import (
    input_contract_conflicts_with_question_binding,
)
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


@dataclass(frozen=True)
class _StepIdentity:
    step_id: UUID
    step_order: int
    assistant_id: UUID
    user_description: str | None


@dataclass(frozen=True)
class _StepInputFields:
    input_source: str
    input_type: str
    input_config: JsonObject | None
    input_bindings: JsonObject | None
    input_contract: JsonObject | None


@dataclass(frozen=True)
class _StepOutputFields:
    output_mode: str
    output_type: str
    output_config: JsonObject | None
    output_contract: JsonObject | None
    output_classification_override: int | None


@dataclass(frozen=True)
class _StepOptionalFields:
    plan_step_ref: str | None
    existing_step_ref: str | None
    assistant_snapshot: JsonObject | None
    timeout_seconds: int | None


def _is_json_object(value: object) -> TypeGuard[JsonObject]:
    return isinstance(value, dict)


def _optional_json_object(value: object) -> JsonObject | None:
    return value if _is_json_object(value) else None


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


def _step_order_from_snapshot(item_dict: Mapping[str, object]) -> int:
    step_order_value = item_dict["step_order"]
    if isinstance(step_order_value, int) and not isinstance(step_order_value, bool):
        return step_order_value
    return int(str(step_order_value))


def _optional_step_description(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _field_string(value: object, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _parse_step_identity(
    item: Mapping[str, object],
    *,
    step_order: int,
    user_description: str | None,
) -> _StepIdentity:
    try:
        step_id = UUID(str(item["step_id"]))
        assistant_id = UUID(str(item["assistant_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise BadRequestException("Invalid step identifiers in flow snapshot.") from exc
    return _StepIdentity(
        step_id=step_id,
        step_order=step_order,
        assistant_id=assistant_id,
        user_description=user_description,
    )


def _parse_input_fields(item: Mapping[str, object]) -> _StepInputFields:
    input_source = _field_string(item.get("input_source"), "flow_input")
    if input_source not in ALLOWED_INPUT_SOURCES:
        raise BadRequestException(f"Unsupported input source '{input_source}'.")

    raw_input_config = _parse_input_config(
        raw_input_config=item.get("input_config"),
        input_source=input_source,
    )
    build_runtime_input_config(raw_input_config)

    input_type = _field_string(item.get("input_type"), "text")
    if input_type not in ALLOWED_INPUT_TYPES:
        raise BadRequestException(f"Unsupported input type '{input_type}'.")

    return _StepInputFields(
        input_source=input_source,
        input_type=input_type,
        input_config=raw_input_config,
        input_bindings=_optional_json_object(item.get("input_bindings")),
        input_contract=_optional_json_object(item.get("input_contract")),
    )


def _validate_input_contract_binding_compatibility(
    input_fields: _StepInputFields,
) -> None:
    if not input_contract_conflicts_with_question_binding(
        input_bindings=input_fields.input_bindings,
        input_contract=input_fields.input_contract,
    ):
        return
    raise BadRequestException(
        "input_contract cannot validate input_bindings.question because the "
        "question binding supplies the complete rendered step input. Remove "
        "input_contract or remove input_bindings.question.",
        code="flow_input_contract_inapplicable",
        context={
            "field": "input_contract",
            "conflict": "input_bindings.question",
        },
    )


def _parse_input_config(
    *,
    raw_input_config: object,
    input_source: str,
) -> JsonObject | None:
    if input_source in {"http_get", "http_post"}:
        if not _is_json_object(raw_input_config):
            raise BadRequestException("HTTP input source requires input_config object.")
        raw_headers = raw_input_config.get("headers")
        if raw_headers is not None and not isinstance(raw_headers, dict):
            raise BadRequestException("HTTP input_config.headers must be an object.")
        return raw_input_config

    if raw_input_config is None:
        return None
    if not _is_json_object(raw_input_config):
        raise BadRequestException("Step input_config must be an object.")
    return raw_input_config


def _parse_output_fields(item: Mapping[str, object]) -> _StepOutputFields:
    output_mode = _field_string(item.get("output_mode"), "pass_through")
    if output_mode not in ALLOWED_OUTPUT_MODES:
        raise BadRequestException(f"Unsupported output mode '{output_mode}'.")

    output_type = _field_string(item.get("output_type"), "text")
    if output_type not in ALLOWED_OUTPUT_TYPES:
        raise BadRequestException(f"Unsupported output type '{output_type}'.")

    raw_output_config = _parse_output_config(
        raw_output_config=item.get("output_config"),
        output_mode=output_mode,
        output_type=output_type,
    )
    output_classification_override_raw = item.get("output_classification_override")
    output_classification_override = (
        output_classification_override_raw
        if isinstance(output_classification_override_raw, int)
        else None
    )
    return _StepOutputFields(
        output_mode=output_mode,
        output_type=output_type,
        output_config=raw_output_config,
        output_contract=_optional_json_object(item.get("output_contract")),
        output_classification_override=output_classification_override,
    )


def _parse_output_config(
    *,
    raw_output_config: object,
    output_mode: str,
    output_type: str,
) -> JsonObject | None:
    if raw_output_config is None:
        return None
    if not _is_json_object(raw_output_config):
        raise BadRequestException("Webhook output_config must be an object.")
    output_config = raw_output_config

    if output_mode == "template_fill":
        bindings = output_config.get("bindings")
        if not isinstance(bindings, dict):
            raise BadRequestException(
                "Template fill output_config.bindings must be an object."
            )
        if (
            "template_asset_id" not in output_config
            and "template_file_id" not in output_config
        ):
            raise BadRequestException(
                "Template fill output_config.template_asset_id or template_file_id is required."
            )
        if output_type != "docx":
            raise BadRequestException(
                "Template fill output_mode requires output_type 'docx'."
            )
        return output_config

    raw_headers = output_config.get("headers")
    if raw_headers is not None and not isinstance(raw_headers, dict):
        raise BadRequestException("Webhook output_config.headers must be an object.")
    return output_config


def _parse_optional_fields(item: Mapping[str, object]) -> _StepOptionalFields:
    plan_step_ref = _non_empty_string(item.get("plan_step_ref"))
    existing_step_ref = _non_empty_string(item.get("existing_step_ref"))
    return _StepOptionalFields(
        plan_step_ref=plan_step_ref,
        existing_step_ref=existing_step_ref,
        assistant_snapshot=_optional_json_object(item.get("assistant_snapshot")),
        timeout_seconds=_optional_positive_int(
            item.get("timeout_seconds"),
            "timeout_seconds",
        ),
    )


def _non_empty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def parse_runtime_steps(definition_json: Mapping[str, object]) -> list[RuntimeStep]:
    steps = definition_json.get("steps")
    if not isinstance(steps, list):
        raise BadRequestException("Flow definition snapshot is missing steps.")
    parsed: list[RuntimeStep] = []
    for item in cast(list[object], steps):
        if not isinstance(item, dict):
            raise BadRequestException("Invalid step definition in flow snapshot.")
        item_dict = cast(Mapping[str, object], item)
        user_description = _optional_step_description(item_dict.get("user_description"))
        try:
            step_order = _step_order_from_snapshot(item_dict)
        except (KeyError, TypeError, ValueError) as exc:
            raise BadRequestException(
                "Invalid step identifiers in flow snapshot."
            ) from exc
        try:
            identity = _parse_step_identity(
                item_dict,
                step_order=step_order,
                user_description=user_description,
            )
            input_fields = _parse_input_fields(item_dict)
            _validate_input_contract_binding_compatibility(input_fields)
            output_fields = _parse_output_fields(item_dict)
            transcribe_only_error = transcribe_only_violation(
                step_order=identity.step_order,
                input_type=input_fields.input_type,
                output_type=output_fields.output_type,
                output_mode=output_fields.output_mode,
            )
            if transcribe_only_error is not None:
                raise BadRequestException(transcribe_only_error)
            runtime_input = build_runtime_input_config(input_fields.input_config)
            if (
                output_fields.output_mode == "transcribe_only"
                and runtime_input.enabled
                and runtime_input.input_format != "audio"
            ):
                raise BadRequestException(
                    "Transcribe-only steps require runtime_input.input_format 'audio'."
                )
            review_policy = parse_flow_step_review_policy(
                raw_policy=item_dict.get("review_policy"),
                output_mode=FlowOutputMode(output_fields.output_mode),
            )
            optional_fields = _parse_optional_fields(item_dict)
        except BadRequestException as exc:
            raise _step_scoped_exception(
                exc,
                step_order=step_order,
                user_description=user_description,
            ) from exc
        parsed.append(
            RuntimeStep(
                step_id=identity.step_id,
                step_order=identity.step_order,
                assistant_id=identity.assistant_id,
                user_description=identity.user_description,
                plan_step_ref=optional_fields.plan_step_ref,
                existing_step_ref=optional_fields.existing_step_ref,
                input_source=input_fields.input_source,
                input_bindings=input_fields.input_bindings,
                input_config=input_fields.input_config,
                output_mode=output_fields.output_mode,
                output_config=output_fields.output_config,
                output_classification_override=(
                    output_fields.output_classification_override
                ),
                output_type=output_fields.output_type,
                output_contract=output_fields.output_contract,
                input_type=input_fields.input_type,
                input_contract=input_fields.input_contract,
                assistant_snapshot=optional_fields.assistant_snapshot,
                review_policy=review_policy,
                timeout_seconds=optional_fields.timeout_seconds,
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
