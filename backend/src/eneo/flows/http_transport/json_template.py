"""A JSON body template: JSON text with ``{{ references }}`` written in it.

The template is read as it was authored, the way every reader of a template's
references reads it (lineage, classification, step rewriting), and what a
reference may become follows from where it stands:

- inside quotes it is text, and arrives as exactly that text in that string;
- outside quotes it is one JSON value of its own type.

A filled value is never read as template or JSON structure, so run data cannot
add to the body the author wrote.
"""

import json
import math
from collections.abc import Callable, Iterator
from re import Match

from eneo.flows.http_transport.errors import HttpRenderedBodyNotJsonError
from eneo.flows.variable_resolver import TEMPLATE_VARIABLE_PATTERN
from eneo.json_types import JsonValue

# What stands in for a reference when the authored structure is checked. Neither
# can join the authored text it meets: no hex digit or escape character inside
# quotes, and nothing a number could continue outside them.
_HOLE_INSIDE_QUOTES = "x"
_HOLE_OUTSIDE_QUOTES = "[]"


def render_json_template(
    template: str,
    *,
    text_of: Callable[[str], str],
    value_of: Callable[[str], object] | None,
) -> JsonValue:
    """The JSON value ``template`` becomes.

    ``text_of`` takes a reference as written, ``{{ a.b }}``, and ``value_of``
    its expression, ``a.b``. Without ``value_of``, what stands outside quotes
    is read from its text.
    """
    if not is_json_template(template):
        raise HttpRenderedBodyNotJsonError()

    def filled(reference: Match[str], quoted: bool) -> str:
        text = text_of(reference.group(0))
        if quoted:
            return _inside_quotes(text)
        if value_of is None:
            return _outside_quotes(text)
        return _outside_quotes(value_of(reference.group(1).strip()))

    return _parsed_body(_filled(template, filled))


def is_json_template(template: str) -> bool:
    """Whether any filling of ``template`` can give a JSON body: each reference
    at a place a whole value or text can stand, and the rest of it JSON."""
    try:
        _parsed_body(
            _filled(
                template,
                lambda _, quoted: (
                    _HOLE_INSIDE_QUOTES if quoted else _HOLE_OUTSIDE_QUOTES
                ),
            )
        )
    except HttpRenderedBodyNotJsonError:
        return False
    return True


def _filled(template: str, fill: Callable[[Match[str], bool], str]) -> str:
    parts: list[str] = []
    position = 0
    for reference, quoted in _references(template):
        parts += template[position : reference.start()], fill(reference, quoted)
        position = reference.end()
    parts.append(template[position:])
    return "".join(parts)


def _references(template: str) -> Iterator[tuple[Match[str], bool]]:
    """Each reference in ``template``, and whether it stands inside quotes."""
    in_string = False
    escaped = False
    position = 0
    for reference in TEMPLATE_VARIABLE_PATTERN.finditer(template):
        for character in template[position : reference.start()]:
            if escaped:
                escaped = False
            elif in_string and character == "\\":
                escaped = True
            elif character == '"':
                in_string = not in_string
        position = reference.end()
        yield reference, in_string


def _inside_quotes(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)[1:-1]


def _outside_quotes(value: object) -> str:
    try:
        if isinstance(value, str):
            # Text outside quotes is JSON that a step gave as text.
            value = _json_value(value)
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError, RecursionError):
        raise HttpRenderedBodyNotJsonError() from None


def _parsed_body(text: str) -> JsonValue:
    try:
        body = _json_value(text)
    except (ValueError, RecursionError):
        raise HttpRenderedBodyNotJsonError() from None
    if body is None:
        # A request's json_body of None means that the step has no body.
        raise HttpRenderedBodyNotJsonError()
    return body


def _json_value(text: str) -> JsonValue:
    """``text`` as strict JSON, which has no NaN or infinity for HTTP to carry."""
    return json.loads(text, parse_constant=_not_a_number, parse_float=_finite)


def _not_a_number(constant: str) -> float:
    raise ValueError(constant)


def _finite(text: str) -> float:
    number = float(text)
    if not math.isfinite(number):
        raise ValueError(text)
    return number
