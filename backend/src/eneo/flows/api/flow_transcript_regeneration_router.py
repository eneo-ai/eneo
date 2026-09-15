from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_api_common import (
    commit_flow_runtime_write_before_response,
    error_response,
)
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_models import FlowRunPublic
from eneo.flows.api.flow_runtime_paths import FLOW_RUN_TRANSCRIPT_REGENERATION_PATH
from eneo.flows.application.flow_dispatch import (
    dispatch_flow_run_recoverably_after_commit,
)
from eneo.flows.domain.flow_run_exceptions import FlowRunConcurrencyLimitReachedError
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_input_envelope import TRANSCRIPT_REGENERATION_KEY
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.main.models import GeneralError
from eneo.server.dependencies.container import get_container_for_explicit_transaction

router = APIRouter()


class FlowTranscriptRegenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_run_revision: int = Field(ge=1)
    expected_correction_revision: int | None = Field(
        ge=1,
        description="Last saved correction revision, or null when no set exists.",
    )
    segments_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class FlowTranscriptRegenerationPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: FlowRunPublic
    created: bool
    source_run_id: UUID
    correction_revision: int | None
    first_regenerated_step_id: UUID


@router.post(
    FLOW_RUN_TRANSCRIPT_REGENERATION_PATH,
    response_model=FlowTranscriptRegenerationPublic,
    status_code=201,
    operation_id="regenerate_flow_run_transcript",
    summary="Regenerate downstream output from a reviewed transcript",
    description="""
Create a new run of the source run's published flow version. The source run must
be completed, its first step must have structured transcription evidence, and
it may be followed by one speaker-mapping step. This prefix is imported as a
reviewed snapshot; all subsequent steps execute normally, including review gates.
No audio is transcribed or realigned by importing the prefix.

The source run, its summary and files stay unchanged. The new run stores source
run/step IDs, correction revision and source/reviewed-text hashes in its input
provenance and imported attempt records. Raw segments, word evidence and human
decisions remain separate. Unresolved spans are preserved.

Supply the original segments_hash and observed run/correction revisions.
The same Idempotency-Key and request replay the accepted run (200), even if
later corrections were saved. A new key against stale revisions is rejected.
A changed published version, unavailable source details or an unsupported
transcription layout must be resolved before retrying; no partial run is committed.
Creation, imported evidence and its required audit commit before dispatch.
Poll the returned run using the existing run endpoint.
""",
    responses={
        200: {
            "model": FlowTranscriptRegenerationPublic,
            "description": "Idempotent replay.",
        },
        400: error_response(
            description="Stale source/revision, changed publication, unsupported layout or conflicting idempotency key.",
            message="Stale source/revision, changed publication, unsupported layout or conflicting idempotency key.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
        ),
        403: error_response(
            description="The caller needs run and review access and source content access.",
            message="The caller needs run and review access and source content access.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
        ),
        404: error_response(
            description="The source flow, run or transcript is unavailable in tenant scope.",
            message="The source flow, run or transcript is unavailable in tenant scope.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
        ),
        429: error_response(
            description="Tenant concurrent-run capacity is exhausted.",
            message="Tenant concurrent-run capacity is exhausted.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
        ),
        503: error_response(
            description="Required audit failed; no new run was accepted.",
            message="Required audit failed; no new run was accepted.",
            eneo_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
        ),
    },
)
async def regenerate_flow_run_transcript(
    id: UUID,
    run_id: UUID,
    step_id: UUID,
    body: FlowTranscriptRegenerationRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    container: Container = Depends(
        get_container_for_explicit_transaction(
            with_user=True,
            with_upload_admission=True,
        )
    ),
) -> FlowTranscriptRegenerationPublic | JSONResponse:
    try:
        async with commit_flow_runtime_write_before_response(container):
            for action in (FlowApiAction.RUN, FlowApiAction.REVIEW):
                await flow_access_context.enforce_flow_scope(
                    request,
                    container,
                    flow_id=id,
                    required_access=action,
                    allow_service_key_principals=True,
                    require_published_for_service_key=True,
                )
            result = await container.flow_transcript_regeneration_service().regenerate(
                flow_id=id,
                run_id=run_id,
                step_id=step_id,
                expected_run_revision=body.expected_run_revision,
                expected_correction_revision=body.expected_correction_revision,
                segments_hash=body.segments_hash,
                idempotency_key=idempotency_key,
            )
            provenance = (result.run.input_payload_json or {})[
                TRANSCRIPT_REGENERATION_KEY
            ]
            public = FlowTranscriptRegenerationPublic(
                run=FlowAssembler().to_run_public(result.run),
                created=result.created,
                source_run_id=provenance["source_run_id"],
                correction_revision=provenance["correction_revision"],
                first_regenerated_step_id=provenance["first_regenerated_step_id"],
            )
    except FlowRunConcurrencyLimitReachedError:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "60"},
            content=GeneralError(
                message="Concurrent flow run limit reached for this tenant.",
                eneo_error_code=ErrorCodes.BAD_REQUEST,
                code=FlowApiErrorCode.RUN_CONCURRENCY_LIMIT_REACHED.value,
            ).model_dump(mode="json"),
        )
    if result.created:
        background_tasks.add_task(
            dispatch_flow_run_recoverably_after_commit,
            run_id=result.run.id,
            tenant_id=result.run.tenant_id,
            expected_revision=result.run.revision,
        )
    else:
        response.status_code = 200
    return public
