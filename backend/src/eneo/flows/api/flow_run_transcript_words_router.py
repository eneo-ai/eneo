from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status

from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_api_common import (
    FLOW_RUN_FORBIDDEN_DESCRIPTION,
    error_response,
)
from eneo.flows.api.flow_models import (
    FlowTranscriptWordsPublic,
    TranscriptSegmentWordsPublic,
    TranscriptWordPublic,
)
from eneo.flows.api.flow_runtime_paths import FLOW_RUN_STEP_TRANSCRIPT_WORDS_PATH
from eneo.flows.application.flow_transcript_words_service import (
    FlowTranscriptWordsView,
)
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.server.dependencies.container import get_container

router = APIRouter()

_FLOW_RUN_TRANSCRIPT_WORDS_DESCRIPTION = """
Word timings behind one transcription step's structured transcript lines.

Each entry addresses a segment by its index in `transcription.segments` (from the
step's `input_payload_json` in the steps listing) and lists that segment's words in
order with `start`/`end` seconds relative to the segment's audio file. `probability`
is the service's placement confidence; its meaning follows `alignment`: on the
`forced` rung a word scored exactly `0.0` was interpolated over its window rather
than found in the audio and should be shown as uncertain.

Words exist only when the step stored segments and the service produced word
timings; otherwise the endpoint returns `404`. A response flagged `stale` anchors to
a transcript that has since been replaced (step re-run) and must not be used.

Current content visibility follows run-detail visibility: callers can inspect their own
runs, tenant admins can inspect runs across the tenant, trusted in-space operators can
inspect content for runs in their space, and service-key principals can inspect only
their own runs.
    """


def _present_transcript_words(
    view: FlowTranscriptWordsView,
) -> FlowTranscriptWordsPublic:
    return FlowTranscriptWordsPublic(
        flow_run_id=view.words.flow_run_id,
        step_id=view.words.step_id,
        segments_hash=view.words.segments_hash,
        alignment=view.words.alignment,
        stale=view.stale,
        segments=[
            TranscriptSegmentWordsPublic(
                segment_index=int(entry["segment_index"]),
                words=[
                    TranscriptWordPublic.model_validate(word)
                    for word in entry.get("words", [])
                ],
            )
            for entry in view.words.words_json
        ],
        created_at=view.words.created_at,
        updated_at=view.words.updated_at,
    )


@router.get(
    FLOW_RUN_STEP_TRANSCRIPT_WORDS_PATH,
    response_model=FlowTranscriptWordsPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_run_transcript_words",
    summary="Get flow run transcript word timings",
    description=_FLOW_RUN_TRANSCRIPT_WORDS_DESCRIPTION,
    responses={
        403: error_response(
            description=FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description=(
                "Run not found for this flow and tenant, or the step stored no "
                "word timings."
            ),
            message="Flow run step transcript words not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def get_flow_run_transcript_words(
    id: Annotated[
        UUID, Path(description="Identifier of the flow that owns the requested run.")
    ],
    run_id: Annotated[
        UUID, Path(description="Identifier of the run the transcription step ran in.")
    ],
    step_id: Annotated[UUID, Path(description="Identifier of the transcription step.")],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await flow_access_context.enforce_flow_scope(
        request,
        container,
        flow_id=id,
        required_access=FlowApiAction.VIEW,
        allow_service_key_principals=True,
    )
    view = await container.flow_transcript_words_service().get_for_step(
        flow_id=id,
        run_id=run_id,
        step_id=step_id,
    )
    return _present_transcript_words(view)
