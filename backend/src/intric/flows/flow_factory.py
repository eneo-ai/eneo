from collections.abc import Sequence

from intric.database.tables.flow_tables import (
    FlowRuns,
    FlowStepAttempts,
    FlowStepResults,
    FlowSteps,
    Flows,
    FlowVersions,
)
from intric.flows.flow import (
    Flow,
    FlowRun,
    FlowSparse,
    FlowStep,
    FlowStepAttempt,
    FlowStepResult,
    FlowVersion,
)


class FlowFactory:
    def from_flow_db(
        self,
        flow_in_db: Flows,
        steps: Sequence[FlowSteps] | None = None,
    ) -> Flow:
        mapped_steps = [FlowStep.model_validate(step) for step in (steps or [])]
        base = FlowSparse.model_validate(flow_in_db)
        return Flow(**base.model_dump(), steps=mapped_steps)

    def from_flow_sparse_db(self, flow_in_db: Flows) -> FlowSparse:
        return FlowSparse.model_validate(flow_in_db)

    def from_flow_version_db(self, version_in_db: FlowVersions) -> FlowVersion:
        return FlowVersion.model_validate(version_in_db)

    def from_flow_run_db(self, run_in_db: FlowRuns) -> FlowRun:
        return FlowRun.model_validate(run_in_db)

    def from_flow_step_result_db(self, result_in_db: FlowStepResults) -> FlowStepResult:
        return FlowStepResult.model_validate(result_in_db)

    def from_flow_step_attempt_db(self, attempt_in_db: FlowStepAttempts) -> FlowStepAttempt:
        return FlowStepAttempt.model_validate(attempt_in_db)
