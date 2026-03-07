from __future__ import annotations

from intric.flows.flow import FlowStepResult, FlowStepResultStatus
from intric.flows.runtime.models import RunExecutionState, RuntimeStep


def build_run_execution_state(
    *,
    steps: list[RuntimeStep],
    persisted_results: list[FlowStepResult],
) -> RunExecutionState:
    completed = {
        result.step_order: result
        for result in persisted_results
        if result.status == FlowStepResultStatus.COMPLETED
    }
    sorted_completed = sorted(completed.values(), key=lambda result: result.step_order)
    segments = [
        f"<step_{result.step_order}_output>\n{str((result.output_payload_json or {}).get('text', ''))}\n"
        f"</step_{result.step_order}_output>\n"
        for result in sorted_completed
    ]
    return RunExecutionState(
        completed_by_order=completed,
        prior_results=list(sorted_completed),
        all_previous_segments=segments,
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
        step_names_by_order={
            step.step_order: step.user_description.strip()
            for step in steps
            if isinstance(step.user_description, str) and step.user_description.strip()
        },
    )
