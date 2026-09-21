"""Resolve immutable transcript evidence under the run's content access policy."""

from uuid import UUID

from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.domain.transcript_source import (
    MissingTranscriptSourceError,
    OmittedTranscriptSource,
    PresentTranscriptSource,
    TranscriptComponentOmissions,
    TranscriptSourceState,
    UnavailablePreRowTranscriptSource,
    transcript_source_reference,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_transcript_source_repo import (
    FlowTranscriptSourceRepository,
)
from eneo.main.exceptions import NotFoundException
from eneo.users.user import UserInDB


class FlowTranscriptSourceService:
    def __init__(
        self,
        *,
        user: UserInDB,
        access_policy: FlowRunAccessPolicy,
        flow_run_repo: FlowRunRepository,
        transcript_source_repo: FlowTranscriptSourceRepository,
    ):
        self.user = user
        self.access_policy = access_policy
        self.flow_run_repo = flow_run_repo
        self.transcript_source_repo = transcript_source_repo

    async def get_for_attempt(
        self, *, flow_id: UUID, run_id: UUID, step_id: UUID, attempt_no: int
    ) -> TranscriptSourceState:
        run = await self.access_policy.load_run(
            run_id=run_id, flow_id=flow_id, access_kind="content"
        )
        attempt = await self.flow_run_repo.get_step_attempt(
            run_id=run.id,
            step_id=step_id,
            attempt_no=attempt_no,
            tenant_id=self.user.tenant_id,
        )
        if attempt is None:
            raise NotFoundException("Flow run step attempt not found.")
        reference = transcript_source_reference(attempt.input_payload_json)
        if reference is None:
            return UnavailablePreRowTranscriptSource()
        if (reference.run_id, reference.step_id, reference.attempt_no) != (
            run.id,
            step_id,
            attempt_no,
        ):
            raise ValueError(
                "Transcript source reference does not belong to its attempt."
            )
        source = await self.transcript_source_repo.get_for_attempt(
            tenant_id=self.user.tenant_id,
            run_id=reference.run_id,
            step_id=reference.step_id,
            attempt_no=reference.attempt_no,
        )
        if source is None:
            raise MissingTranscriptSourceError(reference)
        if (
            source.source_hash != reference.source_hash
            or source.bounds != reference.bounds
        ):
            raise ValueError(
                "Transcript source does not match its immutable reference."
            )
        if source.bounds.segments_omitted_reason is not None:
            return OmittedTranscriptSource(
                reason=source.bounds.segments_omitted_reason, bounds=source.bounds
            )
        return PresentTranscriptSource(
            source=source,
            component_omissions=TranscriptComponentOmissions(
                detail=source.bounds.detail_omitted_reason,
                words=source.bounds.words_omitted_reason,
            ),
        )
