from __future__ import annotations

from datetime import datetime
from typing import Final, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.config import JsonDict

from eneo.authentication.auth_models import (
    FLOW_EVIDENCE_SERVICE_KEY_PERMISSION_RECIPE,
)

FLOW_ROOT_PATH: Final[str] = "/flows"

PUBLISHED_FLOW_RUNTIME_PATH: Final[str] = "/{id}/published/"
RUN_CONTRACT_PATH: Final[str] = "/{id}/run-contract/"
UPLOAD_STEP_RUNTIME_FILE_PATH: Final[str] = "/{id}/steps/{step_id}/runtime-files/"
DELETE_RUNTIME_FILE_PATH: Final[str] = "/{id}/runtime-files/{file_id}/"

FLOW_RUN_STATUS_CAPABILITIES_PATH: Final[str] = "/runs/status-capabilities/"
FLOW_RUNS_PATH: Final[str] = "/{id}/runs/"
FLOW_RUN_PATH: Final[str] = "/{id}/runs/{run_id}/"
FLOW_RUN_CANCEL_PATH: Final[str] = "/{id}/runs/{run_id}/cancel/"
FLOW_RUN_STEP_RERUN_PATH: Final[str] = "/{id}/runs/{run_id}/steps/{step_id}/rerun/"
FLOW_RUN_REDISPATCH_PATH: Final[str] = "/{id}/runs/{run_id}/redispatch/"

FLOW_REVIEW_ACTIVE_PATH: Final[str] = "/{id}/runs/{run_id}/review-checkpoints/active/"
FLOW_REVIEW_CHECKPOINT_PATH: Final[str] = (
    "/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/"
)
FLOW_REVIEW_APPROVE_PATH: Final[str] = (
    "/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/"
)
FLOW_REVIEW_REJECT_PATH: Final[str] = (
    "/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/"
)
FLOW_REVIEW_RESUME_PATH: Final[str] = (
    "/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/"
)

FLOW_RUN_STEPS_PATH: Final[str] = "/{id}/runs/{run_id}/steps/"
FLOW_GRAPH_PATH: Final[str] = "/{id}/graph/"
FLOW_RUN_ARTIFACT_SIGNED_URL_PATH: Final[str] = (
    "/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/"
)

FLOW_RUN_EVIDENCE_PATH: Final[str] = "/{id}/runs/{run_id}/evidence/"
FLOW_RUN_EVIDENCE_EXPORT_PATH: Final[str] = "/{id}/runs/{run_id}/evidence/export"

_EXAMPLE_FLOW_ID: Final[str] = "00000000-0000-0000-0000-000000000001"
_EXAMPLE_SPACE_ID: Final[str] = "00000000-0000-0000-0000-000000000020"
_DEFAULT_EXAMPLE_API_PREFIX: Final[str] = "/api/v1"


class FlowReviewCheckpointRuntimePathsPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    active_template: str = Field(
        description=(
            "GET template for the active review checkpoint on a run. Replace "
            "`{run_id}` with the run id returned by create_run."
        )
    )
    edit_template: str = Field(
        description=(
            "PATCH template for submitting a full corrected checkpoint payload. "
            "Replace `{run_id}` and `{checkpoint_id}` with values returned by "
            "create_run and active checkpoint polling. Send "
            "`expected_checkpoint_revision` plus the full corrected "
            "`current_payload_json` field from the active checkpoint response."
        )
    )
    approve_template: str = Field(
        description=(
            "POST template for approving a checkpoint. Replace `{run_id}` and "
            "`{checkpoint_id}` with values returned by create_run and active "
            "checkpoint polling, and send `expected_checkpoint_revision` from "
            "the latest checkpoint response."
        )
    )
    reject_template: str = Field(
        description=(
            "POST template for rejecting a checkpoint. Replace `{run_id}` and "
            "`{checkpoint_id}` with values returned by create_run and active "
            "checkpoint polling, then send `expected_checkpoint_revision` and a "
            "rejection reason."
        )
    )
    resume_template: str = Field(
        description=(
            "POST template for resuming a run after checkpoint approval. Replace "
            "`{run_id}` and `{checkpoint_id}` with values returned by create_run "
            "and active checkpoint polling, then send the approved checkpoint "
            "`expected_checkpoint_revision`."
        )
    )


class FlowRuntimePathsPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    run_contract: str = Field(
        description=(
            "GET path for the published run contract. Call this before creating a "
            "run to discover required inputs, review checkpoints, final output "
            "delivery, and the published version to pin."
        )
    )
    graph: str = Field(
        description=(
            "GET path for the published flow graph. Add the optional `run_id` query "
            "parameter after run creation to enrich the graph with runtime state."
        )
    )
    upload_step_runtime_file_template: str = Field(
        description=(
            "POST template for uploading files for a specific runtime step. Replace "
            "`{step_id}` with a step id from the run contract, then send "
            "`multipart/form-data` with the binary file in the `upload_file` field. "
            "Use the returned file id in `step_inputs[step_id].file_ids`; the "
            "same file id may be reused for other compatible runtime steps within "
            "this Flow."
        )
    )
    delete_runtime_file_template: str = Field(
        description=(
            "DELETE template for cleaning up an abandoned runtime upload before it "
            "is attached to a run. Replace `{file_id}` with the id returned by "
            "`upload_step_runtime_file_template` for this Flow; files already "
            "persisted in run input or output state return 409 conflict."
        )
    )
    create_run: str = Field(
        description=(
            "POST path for creating a run. The returned run id is committed before "
            "`201 Created` is returned, so clients can immediately poll "
            "`get_run_template`."
        )
    )
    list_runs: str = Field(
        description=(
            "GET path for listing visible runs for this flow. Service keys list only "
            "runs created by the same key."
        )
    )
    cancel_run_template: str = Field(
        description=(
            "POST template for cancelling a non-terminal run. Replace `{run_id}` "
            "with the id returned by create_run."
        )
    )
    rerun_step_template: str = Field(
        description=(
            "POST template for requesting a completed step rerun. Replace `{run_id}` "
            "and `{step_id}` with values from the run and step responses."
        )
    )
    redispatch_run_template: str = Field(
        description=(
            "POST template for redispatching a stale queued run. Replace `{run_id}` "
            "with the id returned by create_run; non-stale queued runs can return "
            "`redispatched_count: 0`."
        )
    )
    review_checkpoints: FlowReviewCheckpointRuntimePathsPublic = Field(
        description=(
            "Review checkpoint path templates for human-in-loop clients. These "
            "templates let web apps discover active checkpoint, edit, approve, "
            "reject, and resume URLs before a run reaches awaiting_review."
        )
    )
    get_graph_for_run_template: str = Field(
        description=(
            "GET template for the run-enriched graph. Replace `{run_id}` with the "
            "id returned by create_run."
        )
    )
    get_run_template: str = Field(
        description=(
            "GET template for polling run status and top-level output. Replace "
            "`{run_id}` with the id returned by create_run."
        )
    )
    list_steps_template: str = Field(
        description=(
            "GET template for inspecting ordered step outputs and result files. "
            "Replace `{run_id}` with the id returned by create_run."
        )
    )
    evidence_template: str = Field(
        description=(
            "GET template for rich run evidence. "
            f"{FLOW_EVIDENCE_SERVICE_KEY_PERMISSION_RECIPE} Service keys can inspect "
            "only their own runs."
        )
    )
    export_evidence_template: str = Field(
        description=(
            "GET template for downloading a redacted evidence JSON bundle. Replace "
            "`{run_id}` with the id returned by create_run; raw export requires a "
            "non-default `reason` query parameter."
        )
    )
    artifact_signed_url_template: str = Field(
        description=(
            "POST template for generating a signed artifact download URL. Replace "
            "`{run_id}` and `{file_id}` with values from run or step result files "
            "and send a SignedURLRequest body."
        )
    )


def _flow_runtime_public_schema_extra(schema: JsonDict) -> None:
    schema["example"] = build_flow_runtime_public_example()


class FlowRuntimePublic(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        json_schema_extra=_flow_runtime_public_schema_extra,
    )

    id: UUID
    space_id: UUID
    name: str
    description: str | None = None
    published_version: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    runtime_paths: FlowRuntimePathsPublic


def build_flow_runtime_paths(
    flow_id: UUID | str,
    *,
    api_prefix: str,
) -> FlowRuntimePathsPublic:
    flow_id_value = str(flow_id)
    graph_path = _flow_path(
        FLOW_GRAPH_PATH,
        flow_id=flow_id_value,
        api_prefix=api_prefix,
    )

    return FlowRuntimePathsPublic(
        run_contract=_flow_path(
            RUN_CONTRACT_PATH,
            flow_id=flow_id_value,
            api_prefix=api_prefix,
        ),
        graph=graph_path,
        upload_step_runtime_file_template=_flow_path(
            UPLOAD_STEP_RUNTIME_FILE_PATH,
            flow_id=flow_id_value,
            api_prefix=api_prefix,
        ),
        delete_runtime_file_template=_flow_path(
            DELETE_RUNTIME_FILE_PATH,
            flow_id=flow_id_value,
            api_prefix=api_prefix,
        ),
        create_run=_flow_path(
            FLOW_RUNS_PATH,
            flow_id=flow_id_value,
            api_prefix=api_prefix,
        ),
        list_runs=_flow_path(
            FLOW_RUNS_PATH,
            flow_id=flow_id_value,
            api_prefix=api_prefix,
        ),
        cancel_run_template=_flow_path(
            FLOW_RUN_CANCEL_PATH,
            flow_id=flow_id_value,
            api_prefix=api_prefix,
        ),
        rerun_step_template=_flow_path(
            FLOW_RUN_STEP_RERUN_PATH,
            flow_id=flow_id_value,
            api_prefix=api_prefix,
        ),
        redispatch_run_template=_flow_path(
            FLOW_RUN_REDISPATCH_PATH,
            flow_id=flow_id_value,
            api_prefix=api_prefix,
        ),
        review_checkpoints=FlowReviewCheckpointRuntimePathsPublic(
            active_template=_flow_path(
                FLOW_REVIEW_ACTIVE_PATH,
                flow_id=flow_id_value,
                api_prefix=api_prefix,
            ),
            edit_template=_flow_path(
                FLOW_REVIEW_CHECKPOINT_PATH,
                flow_id=flow_id_value,
                api_prefix=api_prefix,
            ),
            approve_template=_flow_path(
                FLOW_REVIEW_APPROVE_PATH,
                flow_id=flow_id_value,
                api_prefix=api_prefix,
            ),
            reject_template=_flow_path(
                FLOW_REVIEW_REJECT_PATH,
                flow_id=flow_id_value,
                api_prefix=api_prefix,
            ),
            resume_template=_flow_path(
                FLOW_REVIEW_RESUME_PATH,
                flow_id=flow_id_value,
                api_prefix=api_prefix,
            ),
        ),
        get_graph_for_run_template=f"{graph_path}?run_id={{run_id}}",
        get_run_template=_flow_path(
            FLOW_RUN_PATH,
            flow_id=flow_id_value,
            api_prefix=api_prefix,
        ),
        list_steps_template=_flow_path(
            FLOW_RUN_STEPS_PATH,
            flow_id=flow_id_value,
            api_prefix=api_prefix,
        ),
        evidence_template=_flow_path(
            FLOW_RUN_EVIDENCE_PATH,
            flow_id=flow_id_value,
            api_prefix=api_prefix,
        ),
        export_evidence_template=_flow_path(
            FLOW_RUN_EVIDENCE_EXPORT_PATH,
            flow_id=flow_id_value,
            api_prefix=api_prefix,
        ),
        artifact_signed_url_template=_flow_path(
            FLOW_RUN_ARTIFACT_SIGNED_URL_PATH,
            flow_id=flow_id_value,
            api_prefix=api_prefix,
        ),
    )


def build_flow_runtime_public_example(
    *,
    api_prefix: str = _DEFAULT_EXAMPLE_API_PREFIX,
) -> JsonDict:
    runtime_paths = build_flow_runtime_paths(
        _EXAMPLE_FLOW_ID,
        api_prefix=api_prefix,
    )
    return {
        "id": _EXAMPLE_FLOW_ID,
        "space_id": _EXAMPLE_SPACE_ID,
        "name": "Employee Review Summary",
        "description": "Transcribe a review conversation and return a PDF summary.",
        "published_version": 3,
        "created_at": "2026-03-17T09:30:00Z",
        "updated_at": "2026-03-17T10:00:00Z",
        "runtime_paths": cast(
            JsonDict,
            runtime_paths.model_dump(mode="json"),
        ),
    }


def build_published_flow_runtime_endpoint_template(*, api_prefix: str) -> str:
    return _flow_endpoint_template(
        PUBLISHED_FLOW_RUNTIME_PATH,
        api_prefix=api_prefix,
    )


def build_flow_endpoint_template(route_template: str, *, api_prefix: str) -> str:
    return _flow_endpoint_template(route_template, api_prefix=api_prefix)


def _flow_endpoint_template(route_template: str, *, api_prefix: str) -> str:
    return f"{_normalized_api_prefix(api_prefix)}{FLOW_ROOT_PATH}{route_template}"


def _flow_path(
    route_template: str,
    *,
    flow_id: str,
    api_prefix: str,
) -> str:
    return _flow_endpoint_template(
        route_template,
        api_prefix=api_prefix,
    ).replace("{id}", flow_id)


def _normalized_api_prefix(api_prefix: str) -> str:
    normalized = api_prefix.rstrip("/")
    if not normalized:
        return ""
    if normalized.startswith("/"):
        return normalized
    return f"/{normalized}"
