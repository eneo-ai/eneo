from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from intric.flows.domain.flow import FlowPersistedJsonObject, FlowStep
from intric.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowMcpPolicy,
    FlowOutputMode,
    FlowOutputType,
)
from intric.flows.flow_review_policy import FlowStepReviewPolicy
from intric.main.exceptions import BadRequestException


class FlowStepValidationError(BadRequestException):
    def __init__(
        self,
        message: str,
        *,
        step_order: int,
        code: str | None = None,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message, code=code, context=context)
        self.step_order = step_order


@dataclass(frozen=True, slots=True)
class FlowStepGraphIssue:
    # `code` is the canonical diagnostic consumed by Builder; `exception_code`
    # preserves the legacy BadRequest/FlowStepValidationError `.code` surface.
    step_order: int | None
    code: str
    message: str
    exception_kind: Literal["bad_request", "flow_step"]
    exception_code: str | None = None
    context: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class FlowStepValidationView:
    step_order: int
    timeout_seconds: int | None
    user_description: str | None
    input_source: FlowInputSource
    input_type: FlowInputType
    input_contract: FlowPersistedJsonObject | None
    output_mode: FlowOutputMode
    output_type: FlowOutputType
    output_contract: FlowPersistedJsonObject | None
    input_bindings: FlowPersistedJsonObject | None
    mcp_policy: FlowMcpPolicy
    input_config: FlowPersistedJsonObject | None
    output_config: FlowPersistedJsonObject | None
    review_policy: FlowStepReviewPolicy | None


def flow_step_validation_view_from_flow_step(
    step: FlowStep,
) -> FlowStepValidationView:
    return FlowStepValidationView(
        step_order=step.step_order,
        timeout_seconds=step.timeout_seconds,
        user_description=step.user_description,
        input_source=step.input_source,
        input_type=step.input_type,
        input_contract=step.input_contract,
        output_mode=step.output_mode,
        output_type=step.output_type,
        output_contract=step.output_contract,
        input_bindings=step.input_bindings,
        mcp_policy=step.mcp_policy,
        input_config=step.input_config,
        output_config=step.output_config,
        review_policy=step.review_policy,
    )


def flow_step_validation_views_from_flow_steps(
    steps: Sequence[FlowStep],
) -> list[FlowStepValidationView]:
    return [flow_step_validation_view_from_flow_step(step) for step in steps]
