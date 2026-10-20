"""The run-side paths a published flow exposes, as API consumers discover them.

``GET /flows/{id}/published/`` answers with the flow's metadata and these
paths, so a client integrates against what the server says rather than a
hand-written list. The path templates keep the names the previous flows API
used; templates for paths that are not served yet (graph, evidence,
provider calls, redispatch, transcript words) are left out rather than
pointing at a 404.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

FLOW_ROOT_PATH: Final[str] = "/flows"

PUBLISHED_FLOW_RUNTIME_PATH: Final[str] = "/{id}/published/"
RUN_CONTRACT_PATH: Final[str] = "/{id}/run-contract/"
UPLOAD_RUNTIME_FILE_PATH: Final[str] = "/{id}/runtime-files/"
DELETE_RUNTIME_FILE_PATH: Final[str] = "/{id}/runtime-files/{file_id}/"
FLOW_RUNS_PATH: Final[str] = "/{id}/runs/"
FLOW_RUN_PATH: Final[str] = "/{id}/runs/{run_id}/"
FLOW_RUN_STATUS_PATH: Final[str] = "/{id}/runs/{run_id}/status/"
FLOW_RUN_CANCEL_PATH: Final[str] = "/{id}/runs/{run_id}/cancel/"
FLOW_RUN_STEPS_PATH: Final[str] = "/{id}/runs/{run_id}/steps/"
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
FLOW_REVIEW_APPROVE_AND_CONTINUE_PATH: Final[str] = (
    "/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve-and-continue/"
)
FLOW_RUN_ARTIFACT_SIGNED_URL_PATH: Final[str] = (
    "/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/"
)
FLOW_RUN_INPUT_FILE_SIGNED_URL_PATH: Final[str] = (
    "/{id}/runs/{run_id}/input-files/{file_id}/signed-url/"
)


class FlowReviewCheckpointRuntimePathsPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_template: str = Field(
        description="GET template for the active review checkpoint of a run."
    )
    edit_template: str = Field(
        description=(
            "PATCH template that replaces the reviewed output; send "
            "expected_checkpoint_revision and current_payload_json."
        )
    )
    approve_template: str = Field(
        description="POST template that approves a checkpoint without resuming."
    )
    reject_template: str = Field(
        description="POST template that rejects a checkpoint and fails the run."
    )
    resume_template: str = Field(
        description="POST template that resumes a run after approval."
    )
    approve_and_continue_template: str = Field(
        description="POST template that approves and resumes in one request."
    )


class FlowRuntimePathsPublic(BaseModel):
    """Every run-side path of one published flow, with ``{run_id}``-style
    placeholders where a client fills in ids it got from earlier calls."""

    model_config = ConfigDict(extra="forbid")

    run_contract: str = Field(
        description="GET path for the published run contract (inputs, reviews, output)."
    )
    upload_runtime_file: str = Field(
        description=(
            "POST path for uploading a file to give a run (multipart/form-data, "
            "field upload_file). Bind the returned id to a file form field in "
            "the run request."
        )
    )
    delete_runtime_file_template: str = Field(
        description="DELETE template for an upload no run has used yet."
    )
    create_run: str = Field(
        description="POST path for starting a run; send an Idempotency-Key header."
    )
    list_runs: str = Field(description="GET path for the flow's runs, newest first.")
    cancel_run_template: str = Field(description="POST template that cancels a run.")
    get_run_template: str = Field(
        description="GET template for a run with its inputs, outputs and steps."
    )
    get_run_status_template: str = Field(
        description="GET template for polling a run's status only."
    )
    list_steps_template: str = Field(
        description="GET template for a run's steps with their outputs and files."
    )
    review_checkpoints: FlowReviewCheckpointRuntimePathsPublic
    artifact_signed_url_template: str = Field(
        description=(
            "POST template that mints a signed download URL for a file a run "
            "produced; send a SignedURLRequest body."
        )
    )
    input_file_signed_url_template: str = Field(
        description=(
            "POST template that mints a signed download URL for a file a run "
            "was given; send a SignedURLRequest body."
        )
    )


class FlowRuntimePublic(BaseModel):
    """What an API consumer reads about a published flow."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    space_id: UUID
    name: str
    description: str | None = None
    published_version: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    runtime_paths: FlowRuntimePathsPublic


def _normalized_api_prefix(api_prefix: str) -> str:
    normalized = api_prefix.rstrip("/")
    if not normalized:
        return ""
    return normalized if normalized.startswith("/") else f"/{normalized}"


def flow_endpoint_template(route_template: str, *, api_prefix: str) -> str:
    return f"{_normalized_api_prefix(api_prefix)}{FLOW_ROOT_PATH}{route_template}"


def _flow_path(route_template: str, *, flow_id: str, api_prefix: str) -> str:
    return flow_endpoint_template(route_template, api_prefix=api_prefix).replace(
        "{id}", flow_id
    )


def build_flow_runtime_paths(
    flow_id: UUID | str, *, api_prefix: str
) -> FlowRuntimePathsPublic:
    def path(route_template: str) -> str:
        return _flow_path(route_template, flow_id=str(flow_id), api_prefix=api_prefix)

    return FlowRuntimePathsPublic(
        run_contract=path(RUN_CONTRACT_PATH),
        upload_runtime_file=path(UPLOAD_RUNTIME_FILE_PATH),
        delete_runtime_file_template=path(DELETE_RUNTIME_FILE_PATH),
        create_run=path(FLOW_RUNS_PATH),
        list_runs=path(FLOW_RUNS_PATH),
        cancel_run_template=path(FLOW_RUN_CANCEL_PATH),
        get_run_template=path(FLOW_RUN_PATH),
        get_run_status_template=path(FLOW_RUN_STATUS_PATH),
        list_steps_template=path(FLOW_RUN_STEPS_PATH),
        review_checkpoints=FlowReviewCheckpointRuntimePathsPublic(
            active_template=path(FLOW_REVIEW_ACTIVE_PATH),
            edit_template=path(FLOW_REVIEW_CHECKPOINT_PATH),
            approve_template=path(FLOW_REVIEW_APPROVE_PATH),
            reject_template=path(FLOW_REVIEW_REJECT_PATH),
            resume_template=path(FLOW_REVIEW_RESUME_PATH),
            approve_and_continue_template=path(FLOW_REVIEW_APPROVE_AND_CONTINUE_PATH),
        ),
        artifact_signed_url_template=path(FLOW_RUN_ARTIFACT_SIGNED_URL_PATH),
        input_file_signed_url_template=path(FLOW_RUN_INPUT_FILE_SIGNED_URL_PATH),
    )
