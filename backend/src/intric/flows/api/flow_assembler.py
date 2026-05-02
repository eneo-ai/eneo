from __future__ import annotations

from typing import Any, Sequence

from intric.flows.api.flow_models import (
    FlowPublic,
    FlowRunPublic,
    FlowRunStepPublic,
    FlowRunStepRerunResponse,
    FlowRuntimePathsPublic,
    FlowRuntimePublic,
    FlowSparsePublic,
    FlowStepCreateRequest,
)
from intric.flows.domain.flow import (
    Flow,
    FlowRun,
    FlowRunRerunInvalidatedStep,
    FlowRunRerunOperation,
    FlowSparse,
    FlowStep,
    FlowStepResult,
)
from intric.flows.flow_run_step_result_file import FlowRunStepResultFile
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
            review_policy=step.review_policy,
        )

    def to_public(self, flow: Flow) -> FlowPublic:
        redacted = self._redact_step_configs(flow)
        return FlowPublic.model_validate(redacted)

    def to_sparse_public(self, flow: FlowSparse) -> FlowSparsePublic:
        return FlowSparsePublic.model_validate(flow)

    def to_runtime_public(self, flow: Flow) -> FlowRuntimePublic:
        if flow.id is None:
            raise ValueError("Flow id must be present for runtime projection.")
        if flow.published_version is None:
            raise ValueError(
                "Published flow version must be present for runtime projection."
            )

        flow_id = str(flow.id)
        runtime_paths = FlowRuntimePathsPublic(
            run_contract=f"/api/v1/flows/{flow_id}/run-contract/",
            input_policy=f"/api/v1/flows/{flow_id}/input-policy/",
            graph=f"/api/v1/flows/{flow_id}/graph/",
            upload_flow_file=f"/api/v1/flows/{flow_id}/files/",
            upload_step_runtime_file_template=(
                f"/api/v1/flows/{flow_id}/steps/{{step_id}}/runtime-files/"
            ),
            create_run=f"/api/v1/flows/{flow_id}/runs/",
            list_runs=f"/api/v1/flows/{flow_id}/runs/",
            get_graph_for_run_template=f"/api/v1/flows/{flow_id}/graph/?run_id={{run_id}}",
            get_run_template=f"/api/v1/flows/{flow_id}/runs/{{run_id}}/",
            list_steps_template=f"/api/v1/flows/{flow_id}/runs/{{run_id}}/steps/",
            evidence_template=f"/api/v1/flows/{flow_id}/runs/{{run_id}}/evidence/",
            artifact_signed_url_template=(
                f"/api/v1/flows/{flow_id}/runs/{{run_id}}/artifacts/{{file_id}}/signed-url/"
            ),
        )
        return FlowRuntimePublic(
            id=flow.id,
            space_id=flow.space_id,
            name=flow.name,
            description=flow.description,
            published_version=flow.published_version,
            created_at=flow.created_at,
            updated_at=flow.updated_at,
            runtime_paths=runtime_paths,
        )

    def to_run_public(
        self,
        run: FlowRun,
        *,
        result_files: Sequence[FlowRunStepResultFile] = (),
    ) -> FlowRunPublic:
        return FlowRunPublic.model_validate(run).model_copy(
            update={"result_files": list(result_files)}
        )

    def to_step_public(
        self,
        result: FlowStepResult,
        *,
        diagnostics: Sequence[dict[str, Any]] = (),
        result_files: Sequence[FlowRunStepResultFile] = (),
    ) -> FlowRunStepPublic:
        return FlowRunStepPublic.model_validate(result).model_copy(
            update={
                "diagnostics": list(diagnostics),
                "result_files": list(result_files),
            }
        )

    def to_rerun_response(
        self,
        *,
        operation: FlowRunRerunOperation,
        run: FlowRun,
        invalidated_steps: Sequence[FlowRunRerunInvalidatedStep],
        result_files: Sequence[FlowRunStepResultFile] = (),
    ) -> FlowRunStepRerunResponse:
        return FlowRunStepRerunResponse(
            operation_id=operation.id,
            run=self.to_run_public(run, result_files=result_files),
            rerun_step_id=operation.rerun_step_id,
            new_attempt_no=operation.root_attempt_no,
            invalidated_step_ids=[step.step_id for step in invalidated_steps],
            status=operation.status,
        )

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
