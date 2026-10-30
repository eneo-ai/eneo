"""The output contract one example answer implies.

The same reading the editors make ("Skapa från exempel", web-next's
``contract-from-example.ts`` and apps/web's ``outputContractFromExample.ts``):
an object whose keys are all required fields, each typed by its value. Every
number is typed "number" (one whole number does not show a field is always
whole); a list is typed by its first element; an empty list leaves its
elements open, a null reads as text or empty, and a list whose elements
differ gets its first element's type, each with a note for the author. Only
``type``, ``properties``, ``required`` and ``items`` are written, keywords
every contract dialect the core accepts reads alike. Pure.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Literal, cast

EXAMPLE_LEVELS = 4
"""Container levels an example is read to, the root object being the first."""
EXAMPLE_MAX_CHARACTERS = 200_000
EXAMPLE_MAX_FIELDS = 500
MAX_SAFE_INTEGER = 2**53 - 1

ExampleProblem = Literal[
    "syntax", "not_object", "no_fields", "inexact_number", "too_large"
]
ExampleNote = Literal["empty_list", "null_value", "mixed_list"]

Fields = list[tuple[str, dict[str, Any]]]


class ExampleProblemError(ValueError):
    """The text gives no contract; ``problem`` says why."""

    def __init__(self, problem: ExampleProblem):
        super().__init__(problem)
        self.problem: ExampleProblem = problem


@dataclass(frozen=True)
class ExampleField:
    name: str
    schema: dict[str, Any]
    # False for a name a later step cannot read as a reference.
    variable: bool


@dataclass(frozen=True)
class ExampleContract:
    contract: dict[str, Any]
    fields: tuple[ExampleField, ...]
    notes: tuple[ExampleNote, ...]


class _Walk:
    """What one reading gathers: the notes, the field count, an inexact number."""

    def __init__(self) -> None:
        self.notes: set[ExampleNote] = set()
        self.fields = 0
        self.inexact = False


def is_variable_path_segment(name: str) -> bool:
    """Whether a field name can be read as ``{{step_N.output.structured.<name>}}``."""
    return bool(name) and name.strip() == name and not any(c in name for c in ".{}")


def _inexact_number(value: int | float) -> bool:
    """A number JSON cannot hold exactly, which would make the example a misread one."""
    if isinstance(value, float):
        return not math.isfinite(value)
    return abs(value) > MAX_SAFE_INTEGER


def contract_from_example(text: str) -> ExampleContract:
    """The contract ``text`` (a JSON object) implies, or ExampleProblemError."""
    if len(text) > EXAMPLE_MAX_CHARACTERS:
        raise ExampleProblemError("too_large")
    try:
        value: object = json.loads(text)
    except ValueError as error:
        raise ExampleProblemError("syntax") from error
    if not isinstance(value, dict):
        raise ExampleProblemError("not_object")
    entries = _entries(cast("dict[object, object]", value))
    if not entries:
        raise ExampleProblemError("no_fields")
    walk = _Walk()
    fields = _read_fields(entries, 2, walk)
    if walk.fields > EXAMPLE_MAX_FIELDS:
        raise ExampleProblemError("too_large")
    if walk.inexact:
        raise ExampleProblemError("inexact_number")
    return ExampleContract(
        contract=_object_schema(fields),
        fields=tuple(
            ExampleField(
                name=name, schema=schema, variable=is_variable_path_segment(name)
            )
            for name, schema in fields
        ),
        notes=tuple(sorted(walk.notes)),
    )


def _entries(value: dict[object, object]) -> list[tuple[str, object]]:
    return [(str(key), item) for key, item in value.items()]


def _items(value: list[object]) -> list[object]:
    return list(value)


def _read_fields(entries: list[tuple[str, object]], level: int, walk: _Walk) -> Fields:
    walk.fields += len(entries)
    return [(name, _schema_of(item, level, walk)) for name, item in entries]


def _object_schema(fields: Fields) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {name: schema for name, schema in fields},
        "required": [name for name, _ in fields],
    }


def _element_kind(value: object) -> str:
    """What decides an element's schema at its own level: its kind, and an object's keys."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object:" + json.dumps(
            sorted(name for name, _ in _entries(cast("dict[object, object]", value)))
        )
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _schema_of(value: object, level: int, walk: _Walk) -> dict[str, Any]:
    if value is None:
        walk.notes.add("null_value")
        return {"type": ["string", "null"]}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, (int, float)):
        if _inexact_number(value):
            walk.inexact = True
        return {"type": "number"}
    if isinstance(value, list):
        items = _items(cast("list[object]", value))
        if level > EXAMPLE_LEVELS:
            return {"type": "array"}
        if not items:
            walk.notes.add("empty_list")
            return {"type": "array"}
        first = _element_kind(items[0])
        if any(_element_kind(element) != first for element in items):
            walk.notes.add("mixed_list")
        return {"type": "array", "items": _schema_of(items[0], level + 1, walk)}
    if isinstance(value, dict):
        entries = _entries(cast("dict[object, object]", value))
        if level > EXAMPLE_LEVELS or not entries:
            return {"type": "object"}
        return _object_schema(_read_fields(entries, level + 1, walk))
    return {"type": "string"}
