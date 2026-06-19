from collections.abc import Sequence

from intric.database.tables.flow_tables import (
    FlowRunRerunInvalidatedSteps,
    FlowRunRerunOperations,
    FlowRunReviewCheckpoints,
    FlowRuns,
    Flows,
    FlowStepAttempts,
    FlowStepResults,
    FlowSteps,
    FlowVersions,
)
from intric.flows.domain.flow import (
    Flow,
    FlowRun,
    FlowRunRerunInvalidatedStep,
    FlowRunRerunOperation,
    FlowRunReviewCheckpoint,
    FlowSparse,
    FlowStep,
    FlowStepAttempt,
    FlowStepResult,
    FlowVersion,
    RerunStepInputOverride,
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

    def from_flow_step_attempt_db(
        self, attempt_in_db: FlowStepAttempts
    ) -> FlowStepAttempt:
        return FlowStepAttempt.model_validate(attempt_in_db)

    def from_flow_run_rerun_operation_db(
        self,
        operation_in_db: FlowRunRerunOperations,
        *,
        root_step_input_override: RerunStepInputOverride | None,
    ) -> FlowRunRerunOperation:
        payload = {
            field_name: getattr(operation_in_db, field_name)
            for field_name in FlowRunRerunOperation.model_fields
            if field_name != "root_step_input_override"
        }
        payload["root_step_input_override"] = root_step_input_override
        return FlowRunRerunOperation.model_validate(payload)

    def from_flow_run_rerun_invalidated_step_db(
        self,
        invalidated_step_in_db: FlowRunRerunInvalidatedSteps,
    ) -> FlowRunRerunInvalidatedStep:
        return FlowRunRerunInvalidatedStep.model_validate(invalidated_step_in_db)

    def from_flow_run_review_checkpoint_db(
        self,
        checkpoint_in_db: FlowRunReviewCheckpoints,
    ) -> FlowRunReviewCheckpoint:
        return FlowRunReviewCheckpoint.model_validate(checkpoint_in_db)
