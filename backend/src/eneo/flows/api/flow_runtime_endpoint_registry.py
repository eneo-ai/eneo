from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import status

from eneo.flows.api.flow_runtime_paths import (
    DELETE_RUNTIME_FILE_PATH,
    FLOW_GRAPH_PATH,
    FLOW_REVIEW_ACTIVE_PATH,
    FLOW_REVIEW_APPROVE_PATH,
    FLOW_REVIEW_CHECKPOINT_PATH,
    FLOW_REVIEW_REJECT_PATH,
    FLOW_REVIEW_RESUME_PATH,
    FLOW_RUN_ARTIFACT_SIGNED_URL_PATH,
    FLOW_RUN_CANCEL_PATH,
    FLOW_RUN_EVIDENCE_EXPORT_PATH,
    FLOW_RUN_EVIDENCE_PATH,
    FLOW_RUN_PATH,
    FLOW_RUN_PROVIDER_CALLS_PATH,
    FLOW_RUN_REDISPATCH_PATH,
    FLOW_RUN_STATUS_CAPABILITIES_PATH,
    FLOW_RUN_STEP_RERUN_PATH,
    FLOW_RUN_STEPS_PATH,
    FLOW_RUNS_PATH,
    PUBLISHED_FLOW_RUNTIME_PATH,
    RUN_CONTRACT_PATH,
    UPLOAD_STEP_RUNTIME_FILE_PATH,
    build_flow_endpoint_template,
)

FlowRuntimeEndpointMethod = Literal["delete", "get", "patch", "post"]
FlowRuntimePathField = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FlowRuntimePathFieldProjection:
    field_path: FlowRuntimePathField
    query_suffix: str | None = None


@dataclass(frozen=True, slots=True)
class FlowRuntimeEndpointContract:
    route_path: str
    method: FlowRuntimeEndpointMethod
    operation_id: str
    success_status: int
    runtime_path_fields: tuple[FlowRuntimePathFieldProjection, ...] = ()

    def route_key(self) -> tuple[str, str]:
        return (self.route_path, self.method)

    def prefixed_route_key(self, *, api_prefix: str) -> tuple[str, str]:
        return (
            build_flow_endpoint_template(self.route_path, api_prefix=api_prefix),
            self.method,
        )


@dataclass(frozen=True, slots=True)
class FlowRuntimePathFieldOperation:
    operation_id: str
    method: FlowRuntimeEndpointMethod
    query_suffix: str | None = None


def _field(
    *field_path: str,
    query_suffix: str | None = None,
) -> FlowRuntimePathFieldProjection:
    return FlowRuntimePathFieldProjection(
        field_path=field_path, query_suffix=query_suffix
    )


FLOW_RUNTIME_ENDPOINT_CONTRACTS: tuple[FlowRuntimeEndpointContract, ...] = (
    FlowRuntimeEndpointContract(
        route_path=PUBLISHED_FLOW_RUNTIME_PATH,
        method="get",
        operation_id="get_published_flow_runtime",
        success_status=status.HTTP_200_OK,
    ),
    FlowRuntimeEndpointContract(
        route_path=RUN_CONTRACT_PATH,
        method="get",
        operation_id="get_flow_run_contract",
        success_status=status.HTTP_200_OK,
        runtime_path_fields=(_field("run_contract"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_GRAPH_PATH,
        method="get",
        operation_id="get_flow_graph",
        success_status=status.HTTP_200_OK,
        runtime_path_fields=(
            _field("graph"),
            _field("get_graph_for_run_template", query_suffix="?run_id={run_id}"),
        ),
    ),
    FlowRuntimeEndpointContract(
        route_path=UPLOAD_STEP_RUNTIME_FILE_PATH,
        method="post",
        operation_id="upload_flow_runtime_file",
        success_status=status.HTTP_201_CREATED,
        runtime_path_fields=(_field("upload_step_runtime_file_template"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=DELETE_RUNTIME_FILE_PATH,
        method="delete",
        operation_id="delete_flow_runtime_file",
        success_status=status.HTTP_204_NO_CONTENT,
        runtime_path_fields=(_field("delete_runtime_file_template"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_RUN_STATUS_CAPABILITIES_PATH,
        method="get",
        operation_id="get_flow_run_status_capabilities",
        success_status=status.HTTP_200_OK,
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_RUNS_PATH,
        method="post",
        operation_id="create_flow_run",
        success_status=status.HTTP_201_CREATED,
        runtime_path_fields=(_field("create_run"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_RUNS_PATH,
        method="get",
        operation_id="list_flow_runs",
        success_status=status.HTTP_200_OK,
        runtime_path_fields=(_field("list_runs"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_RUN_PATH,
        method="get",
        operation_id="get_flow_run",
        success_status=status.HTTP_200_OK,
        runtime_path_fields=(_field("get_run_template"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_REVIEW_ACTIVE_PATH,
        method="get",
        operation_id="get_active_flow_run_review_checkpoint",
        success_status=status.HTTP_200_OK,
        runtime_path_fields=(_field("review_checkpoints", "active_template"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_REVIEW_CHECKPOINT_PATH,
        method="patch",
        operation_id="edit_flow_run_review_checkpoint",
        success_status=status.HTTP_200_OK,
        runtime_path_fields=(_field("review_checkpoints", "edit_template"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_REVIEW_APPROVE_PATH,
        method="post",
        operation_id="approve_flow_run_review_checkpoint",
        success_status=status.HTTP_200_OK,
        runtime_path_fields=(_field("review_checkpoints", "approve_template"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_REVIEW_REJECT_PATH,
        method="post",
        operation_id="reject_flow_run_review_checkpoint",
        success_status=status.HTTP_200_OK,
        runtime_path_fields=(_field("review_checkpoints", "reject_template"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_REVIEW_RESUME_PATH,
        method="post",
        operation_id="resume_flow_run_review_checkpoint",
        success_status=status.HTTP_202_ACCEPTED,
        runtime_path_fields=(_field("review_checkpoints", "resume_template"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_RUN_CANCEL_PATH,
        method="post",
        operation_id="cancel_flow_run",
        success_status=status.HTTP_200_OK,
        runtime_path_fields=(_field("cancel_run_template"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_RUN_STEP_RERUN_PATH,
        method="post",
        operation_id="rerun_flow_run_step",
        success_status=status.HTTP_202_ACCEPTED,
        runtime_path_fields=(_field("rerun_step_template"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_RUN_REDISPATCH_PATH,
        method="post",
        operation_id="redispatch_flow_run",
        success_status=status.HTTP_200_OK,
        runtime_path_fields=(_field("redispatch_run_template"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_RUN_EVIDENCE_PATH,
        method="get",
        operation_id="get_flow_run_evidence",
        success_status=status.HTTP_200_OK,
        runtime_path_fields=(_field("evidence_template"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_RUN_PROVIDER_CALLS_PATH,
        method="get",
        operation_id="list_flow_run_provider_calls",
        success_status=status.HTTP_200_OK,
        runtime_path_fields=(_field("provider_calls_template"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_RUN_EVIDENCE_EXPORT_PATH,
        method="get",
        operation_id="export_flow_run_evidence",
        success_status=status.HTTP_200_OK,
        runtime_path_fields=(_field("export_evidence_template"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_RUN_STEPS_PATH,
        method="get",
        operation_id="list_flow_run_steps",
        success_status=status.HTTP_200_OK,
        runtime_path_fields=(_field("list_steps_template"),),
    ),
    FlowRuntimeEndpointContract(
        route_path=FLOW_RUN_ARTIFACT_SIGNED_URL_PATH,
        method="post",
        operation_id="generate_flow_run_artifact_signed_url",
        success_status=status.HTTP_200_OK,
        runtime_path_fields=(_field("artifact_signed_url_template"),),
    ),
)


def flow_runtime_endpoint_operation_ids(
    *,
    api_prefix: str,
) -> dict[tuple[str, str], str]:
    return {
        contract.prefixed_route_key(api_prefix=api_prefix): contract.operation_id
        for contract in FLOW_RUNTIME_ENDPOINT_CONTRACTS
    }


def flow_runtime_path_field_operations() -> dict[
    FlowRuntimePathField, FlowRuntimePathFieldOperation
]:
    return {
        projection.field_path: FlowRuntimePathFieldOperation(
            operation_id=contract.operation_id,
            method=contract.method,
            query_suffix=projection.query_suffix,
        )
        for contract in FLOW_RUNTIME_ENDPOINT_CONTRACTS
        for projection in contract.runtime_path_fields
    }


def flow_runtime_endpoint_by_operation_id() -> dict[str, FlowRuntimeEndpointContract]:
    return {
        contract.operation_id: contract for contract in FLOW_RUNTIME_ENDPOINT_CONTRACTS
    }


def flow_runtime_endpoint_by_path_field() -> dict[
    FlowRuntimePathField, FlowRuntimeEndpointContract
]:
    return {
        projection.field_path: contract
        for contract in FLOW_RUNTIME_ENDPOINT_CONTRACTS
        for projection in contract.runtime_path_fields
    }
