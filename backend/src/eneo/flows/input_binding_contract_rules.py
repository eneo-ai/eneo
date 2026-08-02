from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, cast

FLOW_INPUT_BINDING_UNSUPPORTED_KEY = "flow_input_binding_unsupported_key"
SOURCE_REFS_BINDING_KEY = "source_refs"
SUPPORTED_INPUT_BINDING_KEYS = frozenset({"question", SOURCE_REFS_BINDING_KEY})
SourceRefOutput = Literal["text", "structured"]
InputContractBindingConflict = Literal["question", "source_refs"]
_SOURCE_REF_OUTPUTS: frozenset[SourceRefOutput] = frozenset(("text", "structured"))
_SOURCE_REF_KEYS = frozenset(
    {"step_ref", "output", "field_path", "label", "item_template"}
)
_ITEM_TEMPLATE_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class InputBindingContractError(ValueError):
    def __init__(self, message: str, *, key: str = SOURCE_REFS_BINDING_KEY) -> None:
        self.key = key
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class SourceRefBinding:
    step_ref: str
    output: SourceRefOutput
    field_path: tuple[str, ...] = ()
    label: str | None = None
    item_template: str | None = None

    def template_expression(self) -> str:
        path = ".".join(("output", self.output, *self.field_path))
        return f"{{{{ {self.step_ref}.{path} }}}}"

    def dedupe_key(self) -> tuple[str, str | None]:
        return (self.template_expression(), self.item_template)

    def rendered_section(self) -> str:
        expression = self.template_expression()
        if self.label is None:
            return expression
        return f"{self.label}: {expression}"

    def binding_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "step_ref": self.step_ref,
            "output": self.output,
        }
        if self.field_path:
            payload["field_path"] = ".".join(self.field_path)
        if self.label is not None:
            payload["label"] = self.label
        if self.item_template is not None:
            payload["item_template"] = self.item_template
        return payload


def dedupe_source_refs(
    source_refs: Iterable[SourceRefBinding],
) -> tuple[SourceRefBinding, ...]:
    deduped: list[SourceRefBinding] = []
    indexes_by_expression: dict[tuple[str, str | None], int] = {}
    for ref in source_refs:
        key = ref.dedupe_key()
        existing_index = indexes_by_expression.get(key)
        if existing_index is None:
            indexes_by_expression[key] = len(deduped)
            deduped.append(ref)
            continue
        existing = deduped[existing_index]
        if existing.label is None and ref.label is not None:
            deduped[existing_index] = ref
    return tuple(deduped)


def duplicate_source_ref_expressions(input_bindings: object) -> tuple[str, ...]:
    source_refs = source_ref_bindings(input_bindings)
    seen: set[tuple[str, str | None]] = set()
    duplicates: list[str] = []
    duplicate_seen: set[tuple[str, str | None]] = set()
    for ref in source_refs:
        key = ref.dedupe_key()
        if key not in seen:
            seen.add(key)
            continue
        if key not in duplicate_seen:
            duplicates.append(ref.template_expression())
            duplicate_seen.add(key)
    return tuple(duplicates)


def item_template_field_names(
    template: str,
    *,
    index: int | None = None,
) -> tuple[str, ...]:
    """Return field names from the intentionally tiny item-template grammar."""

    fields: list[str] = []
    position = 0
    while position < len(template):
        char = template[position]
        if char == "{":
            if position + 1 < len(template) and template[position + 1] == "{":
                raise InputBindingContractError(
                    _item_template_error_message(
                        index=index,
                        detail="must use single braces, not '{{'.",
                    )
                )
            close_position = template.find("}", position + 1)
            if close_position == -1:
                raise InputBindingContractError(
                    _item_template_error_message(
                        index=index,
                        detail="contains an unclosed field.",
                    )
                )
            field_name = template[position + 1 : close_position].strip()
            if not _ITEM_TEMPLATE_FIELD_NAME.fullmatch(field_name):
                raise InputBindingContractError(
                    _item_template_error_message(
                        index=index,
                        detail=(
                            "fields must be simple ASCII identifiers like "
                            "{section_title}."
                        ),
                    )
                )
            fields.append(field_name)
            position = close_position + 1
            continue
        if char == "}":
            raise InputBindingContractError(
                _item_template_error_message(
                    index=index,
                    detail="contains an unopened closing brace.",
                )
            )
        position += 1

    if not fields:
        raise InputBindingContractError(
            _item_template_error_message(
                index=index,
                detail="must reference at least one item field.",
            )
        )
    return tuple(fields)


def question_binding(input_bindings: object) -> str | None:
    """Return only the raw runtime `question` binding."""

    if not isinstance(input_bindings, Mapping):
        return None
    bindings = cast(Mapping[object, object], input_bindings)
    question = bindings.get("question")
    if isinstance(question, str) and question.strip():
        return question
    return None


def effective_question_binding(input_bindings: object) -> str | None:
    """Return the authoring-effective question after lowering `source_refs`."""

    lowered = lower_source_refs_to_question_binding(input_bindings)
    return question_binding(lowered)


def input_contract_binding_conflict(
    *,
    input_bindings: object,
    input_contract: object,
    input_type: str | None = None,
) -> InputContractBindingConflict | None:
    if input_contract is None:
        return None
    if question_binding(input_bindings) is not None:
        return "question"
    try:
        refs = source_ref_bindings(input_bindings)
    except InputBindingContractError:
        # Binding validation reports the more precise malformed-ref error.
        return None
    if not refs:
        return None
    if input_type != "json" or any(
        ref.output != "structured" or ref.item_template is not None for ref in refs
    ):
        return "source_refs"
    return None


def is_structured_projection_binding(
    *,
    input_bindings: object,
    input_type: str | None,
) -> bool:
    if input_type != "json" or question_binding(input_bindings) is not None:
        return False
    refs = source_ref_bindings(input_bindings)
    return bool(refs) and all(
        ref.output == "structured" and ref.item_template is None for ref in refs
    )


def derive_structured_projection_contract(
    *,
    input_bindings: object,
    source_contracts_by_step_ref: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if question_binding(input_bindings) is not None:
        raise InputBindingContractError(
            "Structured JSON source_refs cannot be combined with input_bindings.question."
        )
    refs = source_ref_bindings(input_bindings)
    if not refs:
        raise InputBindingContractError(
            "Structured JSON projection requires at least one source_ref."
        )
    projected: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    projection_containers: set[tuple[str, ...]] = set()
    for ref in refs:
        if ref.output != "structured" or ref.item_template is not None:
            raise InputBindingContractError(
                "Structured JSON projection accepts only structured source_refs "
                "without item_template."
            )
        if not ref.field_path:
            raise InputBindingContractError(
                "Structured JSON projection source_refs must select an explicit field_path."
            )
        source_contract = source_contracts_by_step_ref.get(ref.step_ref)
        if source_contract is None:
            raise InputBindingContractError(
                f"Structured JSON projection source step '{ref.step_ref}' has no output contract."
            )
        selected_schema = _schema_at_projection_path(
            source_contract=source_contract,
            field_path=ref.field_path,
            source_step_ref=ref.step_ref,
        )
        _insert_projected_schema(
            projected=projected,
            field_path=ref.field_path,
            selected_schema=selected_schema,
            source_step_ref=ref.step_ref,
            projection_containers=projection_containers,
        )
    return projected


def _schema_at_projection_path(
    *,
    source_contract: Mapping[str, Any],
    field_path: tuple[str, ...],
    source_step_ref: str,
) -> Mapping[str, Any]:
    current = source_contract
    for segment in field_path:
        if current.get("type") != "object":
            raise InputBindingContractError(
                f"source_ref field_path '{'.'.join(field_path)}' for "
                f"'{source_step_ref}' crosses a non-object schema."
            )
        properties = current.get("properties")
        if not isinstance(properties, Mapping):
            raise InputBindingContractError(
                f"source_ref field_path '{'.'.join(field_path)}' for "
                f"'{source_step_ref}' crosses an object without properties."
            )
        next_schema = properties.get(segment)
        if not isinstance(next_schema, Mapping):
            raise InputBindingContractError(
                f"source_ref field_path '{'.'.join(field_path)}' is absent from "
                f"'{source_step_ref}' output contract."
            )
        current = cast(Mapping[str, Any], next_schema)
    return current


def _insert_projected_schema(
    *,
    projected: dict[str, Any],
    field_path: tuple[str, ...],
    selected_schema: Mapping[str, Any],
    source_step_ref: str,
    projection_containers: set[tuple[str, ...]],
) -> None:
    current = projected
    traversed: tuple[str, ...] = ()
    for segment in field_path[:-1]:
        traversed = (*traversed, segment)
        properties = cast(dict[str, Any], current["properties"])
        existing = properties.get(segment)
        if existing is None:
            existing = {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            }
            properties[segment] = existing
            projection_containers.add(traversed)
        elif traversed not in projection_containers:
            raise InputBindingContractError(
                f"source_ref path collision at '{'.'.join(traversed)}' while "
                f"projecting '{source_step_ref}'."
            )
        current_required = cast(list[str], current.setdefault("required", []))
        if segment not in current_required:
            current_required.append(segment)
        current = cast(dict[str, Any], existing)

    leaf = field_path[-1]
    properties = cast(dict[str, Any], current["properties"])
    if leaf in properties:
        raise InputBindingContractError(
            f"source_ref path collision at '{'.'.join(field_path)}' while "
            f"projecting '{source_step_ref}'."
        )
    properties[leaf] = deepcopy(dict(selected_schema))
    current_required = cast(list[str], current.setdefault("required", []))
    if leaf not in current_required:
        current_required.append(leaf)


def source_ref_bindings(input_bindings: object) -> tuple[SourceRefBinding, ...]:
    if not isinstance(input_bindings, Mapping):
        return ()
    bindings = cast(Mapping[object, object], input_bindings)
    if SOURCE_REFS_BINDING_KEY not in bindings:
        return ()
    raw_refs = bindings.get(SOURCE_REFS_BINDING_KEY)
    if not isinstance(raw_refs, list):
        raise InputBindingContractError("input_bindings.source_refs must be a list.")

    parsed: list[SourceRefBinding] = []
    for index, raw_ref in enumerate(cast(list[object], raw_refs)):
        parsed.append(_parse_source_ref(raw_ref, index=index))
    return tuple(parsed)


def lower_source_refs_to_question_binding(
    input_bindings: object,
) -> dict[str, object] | None:
    if not isinstance(input_bindings, Mapping):
        return None
    bindings = dict(cast(Mapping[str, object], input_bindings))
    if SOURCE_REFS_BINDING_KEY not in bindings:
        return bindings

    source_refs = source_ref_bindings(bindings)
    sections: list[str] = []
    question = question_binding(bindings)
    if question is not None:
        sections.append(question)
    sections.extend(ref.rendered_section() for ref in source_refs)

    bindings.pop(SOURCE_REFS_BINDING_KEY, None)
    if sections:
        bindings["question"] = "\n\n".join(sections)
    return bindings or None


def validate_source_refs_binding(input_bindings: object) -> None:
    source_ref_bindings(input_bindings)


def unsupported_input_binding_key(input_bindings: object) -> str | None:
    if not isinstance(input_bindings, Mapping):
        return None
    bindings = cast(Mapping[object, object], input_bindings)
    for key in bindings:
        if not isinstance(key, str):
            return str(key)
        if key not in SUPPORTED_INPUT_BINDING_KEYS:
            return key
    return None


def _parse_source_ref(raw_ref: object, *, index: int) -> SourceRefBinding:
    if not isinstance(raw_ref, Mapping):
        raise InputBindingContractError(
            f"input_bindings.source_refs[{index}] must be an object."
        )
    ref = cast(Mapping[object, object], raw_ref)
    for key in ref:
        if not isinstance(key, str) or key not in _SOURCE_REF_KEYS:
            raise InputBindingContractError(
                f"input_bindings.source_refs[{index}] has unsupported key '{key}'."
            )
    step_ref = _required_string(ref.get("step_ref"), index=index, field="step_ref")
    output = _source_ref_output(ref.get("output"), index=index)
    field_path = _field_path(ref.get("field_path"), index=index)
    if output == "text" and field_path:
        raise InputBindingContractError(
            "input_bindings.source_refs"
            f"[{index}].field_path is only valid for structured output."
        )
    label = _optional_label(ref.get("label"), index=index)
    item_template = _item_template(ref.get("item_template"), index=index)
    return SourceRefBinding(
        step_ref=step_ref,
        output=output,
        field_path=field_path,
        label=label,
        item_template=item_template,
    )


def _required_string(value: object, *, index: int, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputBindingContractError(
            f"input_bindings.source_refs[{index}].{field} must be a non-empty string."
        )
    return value.strip()


def _source_ref_output(value: object, *, index: int) -> SourceRefOutput:
    output = _required_string(value, index=index, field="output")
    if output not in _SOURCE_REF_OUTPUTS:
        raise InputBindingContractError(
            "input_bindings.source_refs"
            f"[{index}].output must be 'text' or 'structured'."
        )
    return output


def _field_path(value: object, *, index: int) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, str) or not value.strip():
        raise InputBindingContractError(
            "input_bindings.source_refs"
            f"[{index}].field_path must be a non-empty dot path when supplied."
        )
    parts = tuple(part.strip() for part in value.split("."))
    if any(not part for part in parts):
        raise InputBindingContractError(
            f"input_bindings.source_refs[{index}].field_path contains an empty segment."
        )
    if "{{" in value or "}}" in value:
        raise InputBindingContractError(
            f"input_bindings.source_refs[{index}].field_path must not contain templates."
        )
    return parts


def _optional_label(value: object, *, index: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InputBindingContractError(
            f"input_bindings.source_refs[{index}].label must be a non-empty string."
        )
    label = value.strip()
    if "{{" in label or "}}" in label:
        raise InputBindingContractError(
            f"input_bindings.source_refs[{index}].label must not contain templates."
        )
    return label


def _item_template(value: object, *, index: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InputBindingContractError(
            f"input_bindings.source_refs[{index}].item_template must be a non-empty string."
        )
    template = value.strip()
    item_template_field_names(template, index=index)
    return template


def _item_template_error_message(*, index: int | None, detail: str) -> str:
    prefix = "input_bindings.source_refs.item_template"
    if index is not None:
        prefix = f"input_bindings.source_refs[{index}].item_template"
    return f"{prefix} {detail}"
