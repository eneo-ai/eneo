"""Report stored word timings and staleness against the current attempt's source."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_transcript_source_service import (
    FlowTranscriptSourceService,
)
from eneo.flows.domain.transcript_words import FlowStepTranscriptWords
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_transcript_words_repo import (
    FlowTranscriptWordsRepository,
)
from eneo.main.exceptions import NotFoundException
from eneo.users.user import UserInDB


@dataclass(frozen=True, slots=True)
class FlowTranscriptWordsView:
    words: FlowStepTranscriptWords
    stale: bool


class FlowTranscriptWordsService:
    def __init__(
        self,
        *,
        user: UserInDB,
        transcript_words_repo: FlowTranscriptWordsRepository,
        access_policy: FlowRunAccessPolicy,
        flow_run_repo: FlowRunRepository,
        transcript_source_service: FlowTranscriptSourceService,
    ):
        self.user = user
        self.transcript_words_repo = transcript_words_repo
        self.access_policy = access_policy
        self.flow_run_repo = flow_run_repo
        self.transcript_source_service = transcript_source_service

    async def get_for_step(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        step_id: UUID,
    ) -> FlowTranscriptWordsView:
        run = await self.access_policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind="content",
        )
        words = await self.transcript_words_repo.get_for_step(
            run_id=run.id,
            step_id=step_id,
            tenant_id=self.user.tenant_id,
        )
        if words is None:
            raise NotFoundException("Flow run step transcript words not found.")
        step_result = await self.flow_run_repo.get_step_result(
            run_id=run.id,
            step_id=step_id,
            tenant_id=self.user.tenant_id,
        )
        reference = (
            await self.transcript_source_service.get_reference_for_attempt(
                flow_id=flow_id,
                run_id=run.id,
                step_id=step_id,
                attempt_no=step_result.current_attempt_no,
            )
            if step_result is not None and step_result.current_attempt_no is not None
            else None
        )
        current_hash = (
            reference.source_hash
            if reference is not None
            and reference.bounds.segments_omitted_reason is None
            else None
        )
        return FlowTranscriptWordsView(
            words=words, stale=words.segments_hash != current_hash
        )
