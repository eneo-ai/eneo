from __future__ import annotations

from eneo.flows.enums import FlowOutputMode
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import TypedIOValidationException


def resolve_handler_mode(output_mode: str) -> FlowOutputMode:
    try:
        return FlowOutputMode(output_mode)
    except ValueError as exc:
        raise TypedIOValidationException(
            f"Unsupported output mode '{output_mode}'.",
            code=FlowApiErrorCode.UNSUPPORTED_OUTPUT_MODE.value,
        ) from exc


__all__ = [
    "resolve_handler_mode",
]
