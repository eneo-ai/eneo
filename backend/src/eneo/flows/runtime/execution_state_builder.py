from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from eneo.flows.domain.flow import FlowStepResult, FlowStepResultStatus
from eneo.flows.domain.review_edit_references import ReviewedResult, ReviewedResultKey
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep
from eneo.flows.step_lineage import build_step_ref_mapping


def build_run_execution_state(
    *,
    steps: list[RuntimeStep],
    persisted_results: list[FlowStepResult],
    flow_id: UUID | None = None,
    reviewed_results: Mapping[ReviewedResultKey, ReviewedResult] | None = None,
) -> RunExecutionState:
    completed = {
        result.step_order: result
        for result in persisted_results
        if result.status == FlowStepResultStatus.COMPLETED
    }
    sorted_completed = sorted(completed.values(), key=lambda result: result.step_order)
    return RunExecutionState(
        flow_id=flow_id,
        completed_by_order=completed,
        prior_results=list(sorted_completed),
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
        step_names_by_order={
            step.step_order: step.user_description.strip()
            for step in steps
            if isinstance(step.user_description, str) and step.user_description.strip()
        },
        step_ref_mapping=build_step_ref_mapping(steps),
        reviewed_results=dict(reviewed_results or {}),
    )
