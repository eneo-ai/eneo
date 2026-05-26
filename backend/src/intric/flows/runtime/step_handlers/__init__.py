from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, TypeAlias

from intric.flows.enums import FlowOutputMode
from intric.flows.runtime.step_handlers.http_post import HttpPostStepHandler
from intric.flows.runtime.step_handlers.pass_through import PassThroughStepHandler
from intric.flows.runtime.step_handlers.template_fill import TemplateFillStepHandler
from intric.flows.runtime.step_handlers.transcribe_only import TranscribeOnlyStepHandler
from intric.main.exceptions import TypedIOValidationException

StepHandlerClass: TypeAlias = (
    type[PassThroughStepHandler]
    | type[HttpPostStepHandler]
    | type[TranscribeOnlyStepHandler]
    | type[TemplateFillStepHandler]
)

STEP_HANDLER_REGISTRY: Final[Mapping[FlowOutputMode, StepHandlerClass]] = (
    MappingProxyType(
        {
            FlowOutputMode.PASS_THROUGH: PassThroughStepHandler,
            FlowOutputMode.HTTP_POST: HttpPostStepHandler,
            FlowOutputMode.TRANSCRIBE_ONLY: TranscribeOnlyStepHandler,
            FlowOutputMode.TEMPLATE_FILL: TemplateFillStepHandler,
        }
    )
)


def resolve_handler_mode(output_mode: str) -> FlowOutputMode:
    try:
        mode = FlowOutputMode(output_mode)
    except ValueError as exc:
        raise TypedIOValidationException(
            f"Unsupported output mode '{output_mode}'.",
            code="flow_unsupported_output_mode",
        ) from exc
    if mode not in STEP_HANDLER_REGISTRY:
        raise TypedIOValidationException(
            f"Unsupported output mode '{output_mode}'.",
            code="flow_unsupported_output_mode",
        )
    return mode


__all__ = [
    "STEP_HANDLER_REGISTRY",
    "StepHandlerClass",
    "resolve_handler_mode",
]
