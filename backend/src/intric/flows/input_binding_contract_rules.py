from __future__ import annotations

from collections.abc import Mapping
from typing import cast

FLOW_INPUT_BINDING_UNSUPPORTED_KEY = "flow_input_binding_unsupported_key"
SUPPORTED_INPUT_BINDING_KEYS = frozenset({"question"})


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
