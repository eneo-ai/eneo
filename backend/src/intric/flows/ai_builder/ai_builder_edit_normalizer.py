from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeAlias, cast

from pydantic import BaseModel

from intric.flows.ai_builder.ai_builder_edit_effective_steps import (
    EffectiveStepState,
    apply_effective_step_operation,
    build_effective_step_states,
    effective_step_index,
    output_type_is_json,
    resolve_insert_index,
)
from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    FlowEditDraft,
    StepEditOperation,
    StepPatch,
)
from intric.flows.ai_builder.ai_builder_form_fields import effective_form_field_names
from intric.flows.ai_builder.ai_builder_mechanical_refs import (
    clean_raw_form_field_refs,
    clean_raw_previous_field_refs,
)
from intric.flows.ai_builder.ai_builder_new_step_models import (
    DocumentDeliveryMode,
    PreviousFieldRef,
)
from intric.flows.ai_builder.ai_builder_structured_field_normalizer import (
    normalize_structured_field_list,
)
from intric.flows.ai_builder.ai_builder_structured_field_paths import (
    missing_structured_output_path,
)
from intric.flows.flow import FlowStep
from intric.flows.flow_review_policy import FlowStepReviewMode
from intric.main.logging import get_logger

_ADDITIVE_PATCH_FIELDS = frozenset({"uses_previous_fields", "uses_form_fields"})
_STEP_PATCH_FIELDS = frozenset(StepPatch.model_fields)
_REVIEW_MODE_OUTPUT_MODE_ALIASES = frozenset(
    mode.value for mode in FlowStepReviewMode
)
_OUTPUT_MODE_DOCUMENT_DELIVERY_ALIASES: dict[str, DocumentDeliveryMode] = {
    "generated": "generated"
}
logger = get_logger(__name__)
JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


@dataclass(frozen=True, slots=True)
class DuplicateModifyConflict:
    target_ref: str
    field_name: str


@dataclass(frozen=True, slots=True)
class EditDraftCanonicalizationResult:
    draft: FlowEditDraft
    conflicts: tuple[DuplicateModifyConflict, ...]


def normalize_loose_edit_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Normalize loose edit output before strict Pydantic parsing.

    Edit-mode LLM output should express intended changes. Exact form-variable
    and previous-field wiring is backend-owned mechanics, so malformed nested
    binding hints are treated as absent instead of forcing a repair round. Add
    operations also share create-mode structured-field coercion because a new
    edit step uses the same `NewStepDraft` contract as a create-mode step.
    """

    operations = arguments.get("operations")
    if not isinstance(operations, list):
        return arguments

    changed = False
    updated_operations: list[Any] = []
    for raw_operation in cast(list[Any], operations):
        if not isinstance(raw_operation, dict):
            updated_operations.append(raw_operation)
            continue

        operation = cast(dict[str, Any], raw_operation)
        updated_operation = dict(operation)
        raw_add_payload = operation.get("add_payload")
        if isinstance(raw_add_payload, dict):
            add_payload = cast(dict[str, Any], raw_add_payload)
            cleaned_payload = _normalize_loose_add_payload(add_payload)
            if cleaned_payload != add_payload:
                changed = True
                updated_operation["add_payload"] = cleaned_payload

        raw_patch = operation.get("patch")
        if isinstance(raw_patch, dict):
            patch = cast(dict[str, Any], raw_patch)
            cleaned_patch = _normalize_loose_patch(patch)
            if cleaned_patch != patch:
                changed = True
                updated_operation["patch"] = cleaned_patch
        updated_operations.append(updated_operation)

    if not changed:
        return arguments
    return {**arguments, "operations": updated_operations}


def normalize_edit_draft_mechanics(
    draft: FlowEditDraft,
    *,
    current_steps: list[FlowStep],
    current_metadata_json: dict[str, object] | None,
) -> FlowEditDraft:
    """Normalize backend-owned edit wiring before strict edit validation."""

    effective_steps = build_effective_step_states(current_steps)
    available_form_fields = effective_form_field_names(
        current_metadata_json,
        draft.form_operations,
    )
    valid_step_refs = {f"existing_step_{step.step_order}" for step in current_steps}
    removed_step_orders = {
        _step_order_from_ref(op.target_ref)
        for op in draft.operations
        if op.op == "remove"
        and op.target_ref in valid_step_refs
        and _step_order_from_ref(op.target_ref) > 0
    }

    changed = False
    normalized_operations: list[StepEditOperation] = []
    for operation in draft.operations:
        normalized_operation = operation
        if operation.op == "add" and operation.add_payload is not None:
            insert_index = resolve_insert_index(
                op=operation,
                working_steps=effective_steps,
            )
            add_payload = _normalize_add_payload_refs(
                operation.add_payload,
                available_form_fields=available_form_fields,
                max_prior_order=insert_index,
                effective_steps=effective_steps,
                removed_step_orders=removed_step_orders,
            )
            if add_payload != operation.add_payload:
                changed = True
                normalized_operation = operation.model_copy(
                    update={"add_payload": add_payload}
                )

        elif operation.op == "modify" and operation.patch is not None:
            target_index = (
                effective_step_index(effective_steps, operation.target_ref)
                if operation.target_ref is not None
                else None
            )
            if target_index is not None:
                patch = _normalize_patch_refs(
                    operation.patch,
                    available_form_fields=available_form_fields,
                    max_prior_order=target_index,
                    effective_steps=effective_steps,
                    removed_step_orders=removed_step_orders,
                )
                if patch != operation.patch:
                    changed = True
                    normalized_operation = operation.model_copy(update={"patch": patch})

        normalized_operations.append(normalized_operation)
        apply_effective_step_operation(
            op=normalized_operation,
            working_steps=effective_steps,
        )

    if not changed:
        return draft
    return draft.model_copy(update={"operations": normalized_operations})


def canonicalize_duplicate_modify_operations(
    draft: FlowEditDraft,
) -> EditDraftCanonicalizationResult:
    removed_targets = {
        operation.target_ref
        for operation in draft.operations
        if operation.op == "remove" and operation.target_ref is not None
    }
    emitted_removes: set[str] = set()
    operations: list[StepEditOperation] = []
    modify_indexes_by_target: dict[str, int] = {}
    conflicts: list[DuplicateModifyConflict] = []
    changed = False

    for operation in draft.operations:
        target_ref = operation.target_ref
        if target_ref is not None and target_ref in removed_targets:
            if operation.op == "remove" and target_ref not in emitted_removes:
                operations.append(operation)
                emitted_removes.add(target_ref)
                continue
            changed = True
            continue

        if operation.op != "modify" or operation.target_ref is None:
            operations.append(operation)
            continue
        if operation.patch is None:
            operations.append(operation)
            continue

        existing_index = modify_indexes_by_target.get(operation.target_ref)
        if existing_index is None:
            modify_indexes_by_target[operation.target_ref] = len(operations)
            operations.append(operation)
            continue

        existing_operation = operations[existing_index]
        if existing_operation.patch is None:
            operations.append(operation)
            continue

        merged_patch = _merge_compatible_step_patches(
            existing_operation.patch,
            operation.patch,
            target_ref=operation.target_ref,
            conflicts=conflicts,
        )
        if merged_patch is None:
            operations.append(operation)
            continue

        changed = True
        operations[existing_index] = existing_operation.model_copy(
            update={"patch": merged_patch}
        )

    if conflicts:
        return EditDraftCanonicalizationResult(draft=draft, conflicts=tuple(conflicts))
    if not changed:
        return EditDraftCanonicalizationResult(draft=draft, conflicts=())
    return EditDraftCanonicalizationResult(
        draft=draft.model_copy(update={"operations": operations}),
        conflicts=(),
    )


def format_duplicate_modify_conflicts(
    conflicts: tuple[DuplicateModifyConflict, ...],
) -> str:
    by_target: dict[str, list[str]] = {}
    for conflict in conflicts:
        by_target.setdefault(conflict.target_ref, []).append(conflict.field_name)

    parts = [
        f"{target_ref}: {', '.join(sorted(set(field_names)))}"
        for target_ref, field_names in sorted(by_target.items())
    ]
    return (
        "Edit validation failed: multiple modify operations target the same step "
        "with conflicting patch fields. Merge compatible changes into one modify "
        "operation per step and choose one value for each conflicting field: "
        + "; ".join(parts)
    )


def _merge_compatible_step_patches(
    first: StepPatch,
    second: StepPatch,
    *,
    target_ref: str,
    conflicts: list[DuplicateModifyConflict],
) -> StepPatch | None:
    merged_data = cast(
        dict[str, object],
        first.model_dump(mode="json", exclude_unset=True),
    )
    local_conflicts: list[DuplicateModifyConflict] = []
    changed = False

    for field_name in second.model_fields_set:
        assert field_name in _STEP_PATCH_FIELDS, field_name

        second_value = getattr(second, field_name)
        if field_name not in first.model_fields_set:
            merged_data[field_name] = _jsonable_patch_value(second_value)
            changed = True
            continue

        first_value = getattr(first, field_name)
        if field_name in _ADDITIVE_PATCH_FIELDS:
            merged_value = _merge_additive_patch_values(first_value, second_value)
            if merged_value is None:
                local_conflicts.append(
                    DuplicateModifyConflict(
                        target_ref=target_ref,
                        field_name=field_name,
                    )
                )
                continue
            merged_data[field_name] = merged_value
            changed = True
            continue

        if _jsonable_patch_value(first_value) != _jsonable_patch_value(second_value):
            local_conflicts.append(
                DuplicateModifyConflict(target_ref=target_ref, field_name=field_name)
            )

    if local_conflicts:
        conflicts.extend(local_conflicts)
        return None
    if not changed:
        return first
    return StepPatch.model_validate(merged_data)


def _merge_additive_patch_values(
    first: object,
    second: object,
) -> list[JsonValue] | None:
    if not isinstance(first, list) or not isinstance(second, list):
        return None

    merged: list[JsonValue] = []
    seen: set[str] = set()
    for value in [*cast(list[object], first), *cast(list[object], second)]:
        jsonable_value = _jsonable_patch_value(value)
        key = json.dumps(jsonable_value, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        merged.append(jsonable_value)
    return merged


def _jsonable_patch_value(value: object) -> JsonValue:
    if isinstance(value, BaseModel):
        return _jsonable_patch_value(
            cast(
                dict[str, object],
                value.model_dump(mode="json", exclude_unset=True),
            )
        )
    if isinstance(value, Enum):
        return _jsonable_patch_value(value.value)
    if isinstance(value, list):
        return [_jsonable_patch_value(item) for item in cast(list[object], value)]
    if isinstance(value, dict):
        typed_value = cast(dict[object, object], value)
        return {
            str(key): _jsonable_patch_value(child)
            for key, child in sorted(
                typed_value.items(),
                key=lambda item: str(item[0]),
            )
        }
    if value is None or isinstance(value, bool | int | float | str):
        return value
    raise TypeError(f"Unsupported StepPatch value type: {type(value).__name__}")


def _strip_malformed_payload_refs(payload: dict[str, Any]) -> dict[str, Any]:
    changed = False
    updated = dict(payload)

    if "uses_previous_fields" in payload:
        cleaned_refs = clean_raw_previous_field_refs(
            payload.get("uses_previous_fields")
        )
        if cleaned_refs != payload.get("uses_previous_fields"):
            changed = True
            if cleaned_refs:
                updated["uses_previous_fields"] = cleaned_refs
            else:
                updated.pop("uses_previous_fields", None)

    if "uses_form_fields" in payload:
        cleaned_fields = clean_raw_form_field_refs(payload.get("uses_form_fields"))
        if cleaned_fields != payload.get("uses_form_fields"):
            changed = True
            if cleaned_fields:
                updated["uses_form_fields"] = cleaned_fields
            else:
                updated.pop("uses_form_fields", None)

    return updated if changed else payload


def _normalize_loose_patch(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned_payload = _strip_malformed_payload_refs(payload)
    updated = dict(cleaned_payload)
    changed = cleaned_payload != payload

    raw_output_mode = cleaned_payload.get("output_mode")
    output_mode_symbol = _normalized_loose_symbol(raw_output_mode)
    if output_mode_symbol in _REVIEW_MODE_OUTPUT_MODE_ALIASES:
        if "review_mode" not in updated or updated.get("review_mode") is None:
            updated["review_mode"] = output_mode_symbol
        updated.pop("output_mode", None)
        changed = True
        logger.info("ai_builder_edit_output_mode_moved_to_review_mode")
    elif output_mode_symbol in _OUTPUT_MODE_DOCUMENT_DELIVERY_ALIASES:
        if (
            "document_delivery_mode" not in updated
            or updated.get("document_delivery_mode") is None
        ):
            updated["document_delivery_mode"] = _OUTPUT_MODE_DOCUMENT_DELIVERY_ALIASES[
                output_mode_symbol
            ]
        updated.pop("output_mode", None)
        changed = True
        logger.info("ai_builder_edit_output_mode_moved_to_document_delivery_mode")

    return updated if changed else payload


def _normalized_loose_symbol(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized or None


def _normalize_loose_add_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned_payload = _strip_malformed_payload_refs(payload)
    updated = dict(cleaned_payload)
    changed = cleaned_payload != payload

    if "output_fields" in cleaned_payload:
        normalized_fields = normalize_structured_field_list(
            cleaned_payload.get("output_fields")
        )
        if normalized_fields:
            if normalized_fields != cleaned_payload.get("output_fields"):
                changed = True
                updated["output_fields"] = normalized_fields
        else:
            changed = True
            updated.pop("output_fields", None)

    return updated if changed else payload


def _normalize_add_payload_refs(
    payload: AddStepPayload,
    *,
    available_form_fields: set[str],
    max_prior_order: int,
    effective_steps: list[EffectiveStepState],
    removed_step_orders: set[int],
) -> AddStepPayload:
    safe_previous_refs = _safe_previous_field_refs(
        refs=payload.uses_previous_fields,
        max_prior_order=max_prior_order,
        effective_steps=effective_steps,
        removed_step_orders=removed_step_orders,
    )
    safe_form_fields = _safe_form_fields(
        refs=payload.uses_form_fields,
        available_form_fields=available_form_fields,
    )
    if (
        safe_previous_refs == payload.uses_previous_fields
        and safe_form_fields == payload.uses_form_fields
    ):
        return payload
    return payload.model_copy(
        update={
            "uses_form_fields": safe_form_fields,
            "uses_previous_fields": safe_previous_refs,
        }
    )


def _normalize_patch_refs(
    patch: StepPatch,
    *,
    available_form_fields: set[str],
    max_prior_order: int,
    effective_steps: list[EffectiveStepState],
    removed_step_orders: set[int],
) -> StepPatch:
    updates: dict[str, object] = {}
    remove_fields: set[str] = set()

    if (
        "uses_previous_fields" in patch.model_fields_set
        and patch.uses_previous_fields is not None
    ):
        safe_previous_refs = _safe_previous_field_refs(
            refs=patch.uses_previous_fields,
            max_prior_order=max_prior_order,
            effective_steps=effective_steps,
            removed_step_orders=removed_step_orders,
        )
        if safe_previous_refs != patch.uses_previous_fields:
            if safe_previous_refs or not patch.uses_previous_fields:
                updates["uses_previous_fields"] = safe_previous_refs
            else:
                remove_fields.add("uses_previous_fields")

    if (
        "uses_form_fields" in patch.model_fields_set
        and patch.uses_form_fields is not None
    ):
        safe_form_fields = _safe_form_fields(
            refs=patch.uses_form_fields,
            available_form_fields=available_form_fields,
        )
        if safe_form_fields != patch.uses_form_fields:
            if safe_form_fields or not patch.uses_form_fields:
                updates["uses_form_fields"] = safe_form_fields
            else:
                remove_fields.add("uses_form_fields")

    if not updates and not remove_fields:
        return patch
    return _replace_patch_fields(
        patch,
        updates=updates,
        remove_fields=remove_fields,
    )


def _replace_patch_fields(
    patch: StepPatch,
    *,
    updates: dict[str, object],
    remove_fields: set[str],
) -> StepPatch:
    if not remove_fields:
        return patch.model_copy(update=updates)

    payload = patch.model_dump(mode="python", exclude_unset=True)
    for field_name in remove_fields:
        payload.pop(field_name, None)
    payload.update(updates)
    return StepPatch.model_validate(payload)


def _safe_form_fields(
    *,
    refs: list[str],
    available_form_fields: set[str],
) -> list[str]:
    return [field_name for field_name in refs if field_name in available_form_fields]


def _safe_previous_field_refs(
    *,
    refs: list[PreviousFieldRef],
    max_prior_order: int,
    effective_steps: list[EffectiveStepState],
    removed_step_orders: set[int],
) -> list[PreviousFieldRef]:
    safe_refs: list[PreviousFieldRef] = []
    seen: set[tuple[int, str]] = set()
    max_safe_order = min(max_prior_order, len(effective_steps))
    for field_ref in refs:
        if field_ref.from_step < 1 or field_ref.from_step > max_safe_order:
            continue
        if field_ref.from_step in removed_step_orders:
            continue

        target_step = effective_steps[field_ref.from_step - 1]
        if not output_type_is_json(target_step.output_type):
            continue
        if target_step.output_contract is None:
            continue
        if (
            missing_structured_output_path(
                target_step.output_contract,
                field_ref.field_path,
                require_array_index=True,
            )
            is not None
        ):
            continue

        key = (field_ref.from_step, field_ref.field_path)
        if key in seen:
            continue
        seen.add(key)
        safe_refs.append(field_ref)
    return safe_refs


def _step_order_from_ref(step_ref: str | None) -> int:
    if step_ref is None:
        return 0
    raw = step_ref.removeprefix("existing_step_")
    return int(raw) if raw.isdigit() else 0


__all__ = [
    "DuplicateModifyConflict",
    "EditDraftCanonicalizationResult",
    "canonicalize_duplicate_modify_operations",
    "format_duplicate_modify_conflicts",
    "normalize_loose_edit_arguments",
    "normalize_edit_draft_mechanics",
]
