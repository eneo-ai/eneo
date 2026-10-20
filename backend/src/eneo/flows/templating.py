"""Deterministic text substitution for flow step inputs.

A template names what it reads with double-brace references:

- ``{{form.<key>}}``: a run input (form field) value.
- ``{{steps.<key>}}``: the text output of an earlier step.
- ``{{steps.<key>.json.<path>}}``: a value inside an earlier step's JSON
  output, dotted path, list indexes as numbers (``items.0.title``).
- ``{{previous}}``: the text output of the step just before this one.

Rendering is plain substitution: no expressions, no conditionals, no model.
Unknown references are a definition error, caught at authoring time by
:func:`eneo.flows.definition.validate_definition`, so rendering never
silently drops them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, cast

REFERENCE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.\-]+)\s*\}\}")

# Form field keys and step keys: short, lower-case identifiers the model can
# repeat reliably and that read well in a template.
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True)
class Reference:
    """One parsed ``{{...}}`` reference."""

    raw: str
    source: str  # "form" | "steps" | "previous"
    key: str | None = None  # form field key or step key
    json_path: tuple[str, ...] = ()  # only for steps.<key>.json.<path>

    @property
    def wants_json(self) -> bool:
        return self.source == "steps" and bool(self.json_path)


class TemplateError(ValueError):
    """A template references something it cannot read."""


def parse_reference(raw: str) -> Reference:
    parts = raw.split(".")
    if parts == ["previous"]:
        return Reference(raw=raw, source="previous")
    if len(parts) == 2 and parts[0] == "form":
        return Reference(raw=raw, source="form", key=parts[1])
    if len(parts) == 2 and parts[0] == "steps":
        return Reference(raw=raw, source="steps", key=parts[1])
    if len(parts) >= 4 and parts[0] == "steps" and parts[2] == "json":
        return Reference(
            raw=raw, source="steps", key=parts[1], json_path=tuple(parts[3:])
        )
    raise TemplateError(
        f"Unknown reference '{{{{{raw}}}}}'. Use {{{{form.<key>}}}}, "
        "{{steps.<key>}}, {{steps.<key>.json.<path>}} or {{previous}}."
    )


def extract_references(template: str) -> list[Reference]:
    """Every reference in ``template``, in order of appearance."""
    return [
        parse_reference(match.group(1))
        for match in REFERENCE_PATTERN.finditer(template)
    ]


@dataclass
class StepOutput:
    """What later steps can read from a finished step."""

    text: str = ""
    value: Any = None  # parsed JSON output when the step produced JSON


@dataclass
class TemplateContext:
    form: dict[str, str] = field(default_factory=dict[str, str])
    steps: dict[str, StepOutput] = field(default_factory=dict[str, StepOutput])
    previous: str = ""


def _json_lookup(value: Any, path: tuple[str, ...], raw: str) -> Any:
    current: Any = value
    for part in path:
        if isinstance(current, dict):
            mapping = cast(dict[str, Any], current)
            if part not in mapping:
                raise TemplateError(f"'{{{{{raw}}}}}': key '{part}' is missing.")
            current = mapping[part]
        elif isinstance(current, list):
            items = cast(list[Any], current)
            try:
                current = items[int(part)]
            except (ValueError, IndexError) as exc:
                raise TemplateError(
                    f"'{{{{{raw}}}}}': '{part}' is not a valid list index."
                ) from exc
        else:
            raise TemplateError(
                f"'{{{{{raw}}}}}': cannot read '{part}' from a scalar value."
            )
    return current


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def resolve_reference(reference: Reference, context: TemplateContext) -> str:
    if reference.source == "previous":
        return context.previous
    if reference.source == "form":
        assert reference.key is not None
        if reference.key not in context.form:
            raise TemplateError(f"Form field '{reference.key}' has no value.")
        return context.form[reference.key]
    assert reference.key is not None
    output = context.steps.get(reference.key)
    if output is None:
        raise TemplateError(f"Step '{reference.key}' has not produced output.")
    if not reference.wants_json:
        return output.text
    if output.value is None:
        raise TemplateError(
            f"Step '{reference.key}' produced no JSON to read "
            f"'{{{{{reference.raw}}}}}' from."
        )
    return _as_text(_json_lookup(output.value, reference.json_path, reference.raw))


def render_template(template: str, context: TemplateContext) -> str:
    """Substitute every reference in ``template`` from ``context``."""

    def _substitute(match: re.Match[str]) -> str:
        return resolve_reference(parse_reference(match.group(1)), context)

    return REFERENCE_PATTERN.sub(_substitute, template)
