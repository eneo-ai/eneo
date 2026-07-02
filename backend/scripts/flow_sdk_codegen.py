from __future__ import annotations

import json
from collections.abc import Sequence


def object_freeze_string_array(name: str, values: Sequence[str]) -> list[str]:
    lines = [f"export const {name} = Object.freeze(["]
    for index, value in enumerate(values):
        comma = "," if index < len(values) - 1 else ""
        lines.append(f"  {json.dumps(value)}{comma}")
    lines.append("]);")
    return lines


def string_literal_union_lines(name: str, values: Sequence[str]) -> list[str]:
    union = " | ".join(json.dumps(value) for value in values)
    if len(f"  {union};") <= 100:
        return [f"export type {name} =", f"  {union};"]

    lines = [f"export type {name} ="]
    for index, value in enumerate(values):
        terminator = ";" if index == len(values) - 1 else ""
        lines.append(f"  | {json.dumps(value)}{terminator}")
    return lines
