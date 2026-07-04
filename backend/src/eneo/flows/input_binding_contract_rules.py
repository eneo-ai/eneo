from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

FLOW_INPUT_BINDING_UNSUPPORTED_KEY = "flow_input_binding_unsupported_key"
SOURCE_REFS_BINDING_KEY = "source_refs"
SUPPORTED_INPUT_BINDING_KEYS = frozenset({"question"})
SourceRefOutput = Literal["text", "structured"]
_SOURCE_REF_OUTPUTS: frozenset[SourceRefOutput] = frozenset(("text", "structured"))
_SOURCE_REF_KEYS = frozenset({"step_ref", "output", "field_path", "label"})


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

    def template_expression(self) -> str:
        path = ".".join(("output", self.output, *self.field_path))
        return f"{{{{ {self.step_ref}.{path} }}}}"

    def rendered_section(self) -> str:
        expression = self.template_expression()
        if self.label is None:
            return expression
        return f"{self.label}: {expression}"


def question_binding(input_bindings: object) -> str | None:
    if not isinstance(input_bindings, Mapping):
        return None
    bindings = cast(Mapping[object, object], input_bindings)
    question = bindings.get("question")
    if isinstance(question, str) and question.strip():
        return question
    return None


def input_contract_conflicts_with_question_binding(
    *,
    input_bindings: object,
    input_contract: object,
) -> bool:
    return input_contract is not None and question_binding(input_bindings) is not None


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
    return SourceRefBinding(
        step_ref=step_ref,
        output=output,
        field_path=field_path,
        label=label,
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
