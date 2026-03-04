from __future__ import annotations

import json
from typing import Any

from intric.flows.output_processing import validate_against_contract
from intric.flows.type_policies import INPUT_TYPE_POLICIES, InputTypePolicy
from intric.main.exceptions import TypedIOValidationException


def validate_runtime_input_policy(
    *,
    step_order: int,
    input_type: str,
    input_source: str,
    raw_extracted_text: str,
    files: list[Any] | None = None,
) -> InputTypePolicy | None:
    """Validate runtime input policy constraints for a step."""
    policy = INPUT_TYPE_POLICIES.get(input_type)

    if policy and not policy.supported:
        raise TypedIOValidationException(
            f"Input type '{input_type}' is not yet supported in runtime execution.",
            code="typed_io_unsupported_type",
        )

    if input_type == "document" and input_source != "flow_input":
        raise TypedIOValidationException(
            f"Step {step_order}: input_type 'document' is not supported with input_source '{input_source}'.",
            code="typed_io_document_source_unsupported",
        )

    if policy and policy.requires_extraction and not raw_extracted_text.strip():
        raise TypedIOValidationException(
            f"Step {step_order}: {input_type} extraction produced empty text.",
            code="typed_io_empty_extraction",
        )

    if policy and policy.requires_files:
        all_files = files or []
        usable = [
            file
            for file in all_files
            if (getattr(file, "mimetype", None) or "").startswith("image/")
        ]
        if not usable:
            raise TypedIOValidationException(
                f"Step {step_order}: image input requires at least one valid image file.",
                code="typed_io_missing_required_files",
            )

        non_images = [
            getattr(file, "name", "unknown")
            for file in all_files
            if not (getattr(file, "mimetype", None) or "").startswith("image/")
        ]
        if non_images:
            raise TypedIOValidationException(
                f"Step {step_order}: non-image file(s) for image input: {non_images}",
                code="typed_io_invalid_file_type",
            )

    return policy


def validate_input_contract(
    *,
    step_order: int,
    input_type: str,
    input_contract: dict[str, Any] | None,
    text: str,
    structured: dict[str, Any] | list[Any] | None,
) -> dict[str, Any] | None:
    """Validate a resolved step input against input_contract and return validation metadata."""
    if input_contract is None:
        return None

    if input_type == "json":
        if structured is None:
            contract_validation = {
                "schema_type_hint": _schema_type_hint(input_contract),
                "parse_attempted": False,
                "parse_succeeded": False,
                "candidate_type": "str",
            }
            exc = TypedIOValidationException(
                f"Step {step_order}: input_type 'json' requires valid JSON input before contract validation.",
                code="typed_io_invalid_json_input",
            )
            setattr(exc, "contract_validation", contract_validation)
            raise exc

        contract_validation = {
            "schema_type_hint": _schema_type_hint(input_contract),
            "parse_attempted": False,
            "parse_succeeded": True,
            "candidate_type": type(structured).__name__,
        }
        try:
            validate_against_contract(
                structured,
                input_contract,
                label=f"Step {step_order} input",
            )
        except TypedIOValidationException as exc:
            setattr(exc, "contract_validation", contract_validation)
            raise
        return contract_validation

    if input_type == "text":
        candidate, contract_validation = _prepare_text_contract_candidate(
            text=text,
            schema=input_contract,
        )
        try:
            validate_against_contract(
                candidate,
                input_contract,
                label=f"Step {step_order} input",
            )
        except TypedIOValidationException as exc:
            setattr(exc, "contract_validation", contract_validation)
            raise
        return contract_validation

    return None


def _schema_type_hint(schema: dict[str, Any]) -> str:
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return raw_type
    if isinstance(raw_type, list):
        type_entries = sorted(str(item) for item in raw_type if isinstance(item, str))
        if type_entries:
            return "|".join(type_entries)
    if isinstance(schema.get("properties"), dict):
        return "object"
    if "items" in schema:
        return "array"
    return "unknown"


def _schema_expects_structured(schema: dict[str, Any]) -> bool:
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return raw_type in {"object", "array"}
    if isinstance(raw_type, list):
        return any(item in {"object", "array"} for item in raw_type if isinstance(item, str))
    return isinstance(schema.get("properties"), dict) or "items" in schema


def _prepare_text_contract_candidate(
    *,
    text: str,
    schema: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    parse_attempted = _schema_expects_structured(schema)
    parse_succeeded = False
    candidate: Any = text
    if parse_attempted:
        try:
            candidate = json.loads(text)
            parse_succeeded = True
        except (json.JSONDecodeError, ValueError):
            candidate = text

    return candidate, {
        "schema_type_hint": _schema_type_hint(schema),
        "parse_attempted": parse_attempted,
        "parse_succeeded": parse_succeeded,
        "candidate_type": type(candidate).__name__,
    }
