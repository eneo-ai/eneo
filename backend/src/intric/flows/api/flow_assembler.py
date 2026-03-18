from __future__ import annotations

from typing import Any

from intric.flows.flow import Flow, FlowRun, FlowSparse, FlowStep
from intric.flows.api.flow_models import (
    FlowPublic,
    FlowRunPublic,
    FlowSparsePublic,
    FlowStepCreateRequest,
)
from intric.flows.http_transport import (
    HttpAuthoredConfig,
    is_authored_config,
    redact_authored_config,
)


class FlowAssembler:
    def to_domain_step(self, step: FlowStepCreateRequest) -> FlowStep:
        return FlowStep(
            assistant_id=step.assistant_id,
            step_order=step.step_order,
            user_description=step.user_description,
            input_source=step.input_source,
            input_type=step.input_type,
            input_contract=step.input_contract,
            output_mode=step.output_mode,
            output_type=step.output_type,
            output_contract=step.output_contract,
            input_bindings=step.input_bindings,
            output_classification_override=step.output_classification_override,
            mcp_policy=step.mcp_policy,
            input_config=step.input_config,
            output_config=step.output_config,
        )

    def to_public(self, flow: Flow) -> FlowPublic:
        redacted = self._redact_step_configs(flow)
        return FlowPublic.model_validate(redacted)

    def to_sparse_public(self, flow: FlowSparse) -> FlowSparsePublic:
        return FlowSparsePublic.model_validate(flow)

    def to_run_public(self, run: FlowRun) -> FlowRunPublic:
        return FlowRunPublic.model_validate(run)

    @staticmethod
    def _redact_step_configs(flow: Flow) -> Flow:
        """Replace encrypted secrets with sentinel values in authored HTTP configs."""
        redacted_steps = [
            step.model_copy(
                update={
                    "input_config": _redact_config(step.input_config),
                    "output_config": _redact_config(step.output_config),
                },
                deep=True,
            )
            for step in flow.steps
        ]
        return flow.model_copy(update={"steps": redacted_steps}, deep=True)


def _redact_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if config is None or not is_authored_config(config):
        return config
    authored = HttpAuthoredConfig.model_validate(config)
    redacted = redact_authored_config(authored)
    return redacted.model_dump(mode="json")
