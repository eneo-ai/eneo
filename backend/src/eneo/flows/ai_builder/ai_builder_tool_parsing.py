from __future__ import annotations

import json
from typing import Any, cast


class ToolArgumentParseError(ValueError):
    """Raised when provider tool-call arguments are not a JSON object."""


def parse_tool_call_arguments(arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as error:
        raise ToolArgumentParseError(str(error)) from error
    if not isinstance(parsed, dict):
        raise ToolArgumentParseError("arguments must be a JSON object")
    return cast(dict[str, Any], parsed)


def extract_assumptions(arguments: dict[str, Any]) -> list[str]:
    raw = arguments.get("assumptions")
    if isinstance(raw, list):
        return [item for item in cast(list[Any], raw) if isinstance(item, str)]
    return []


def extract_reasoning(arguments: dict[str, Any]) -> str | None:
    raw = arguments.get("reasoning")
    return str(raw) if isinstance(raw, str) and raw else None


def extract_plan_rationale(arguments: dict[str, Any]) -> str | None:
    raw = arguments.get("plan_rationale")
    return str(raw) if isinstance(raw, str) and raw else None
