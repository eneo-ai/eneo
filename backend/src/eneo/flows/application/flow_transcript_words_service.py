"""Application service for a transcription step's stored word timings.

Words anchor to the structured transcript lines the step stored
(``input_payload_json["transcription"]["segments"]``) by segment index and
carry that array's content hash, so the service can report a row as stale
when the step was re-run after the words were written.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_transcript_corrections_service import (
    extract_transcription_segments,
)
from eneo.flows.domain.transcript_corrections import segments_content_hash
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
    ):
        self.user = user
        self.transcript_words_repo = transcript_words_repo
        self.access_policy = access_policy
        self.flow_run_repo = flow_run_repo

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
        segments = (
            extract_transcription_segments(step_result.input_payload_json)
            if step_result is not None
            else None
        )
        current_hash = segments_content_hash(segments) if segments else None
        return FlowTranscriptWordsView(
            words=words, stale=words.segments_hash != current_hash
        )
