"""Resolve immutable transcript evidence under the run's content access policy."""

from collections.abc import Sequence
from uuid import UUID

from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.domain.flow import FlowStepAttempt, FlowStepResult
from eneo.flows.domain.transcript_source import (
    MissingTranscriptSourceError,
    OmittedTranscriptSource,
    PresentTranscriptSource,
    TranscriptComponentOmissions,
    TranscriptSourceExportRow,
    TranscriptSourceReference,
    TranscriptSourceState,
    UnavailablePreRowTranscriptSource,
    transcript_source_reference,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_transcript_source_repo import (
    FlowTranscriptSourceRepository,
    TranscriptSourceExportMeasurement,
)
from eneo.main.exceptions import FileTooLargeException, NotFoundException
from eneo.users.user import UserInDB


def _attempt_reference(attempt: FlowStepAttempt) -> TranscriptSourceReference | None:
    reference = transcript_source_reference(attempt.input_payload_json)
    if reference is not None and (
        reference.run_id,
        reference.step_id,
        reference.attempt_no,
    ) != (attempt.flow_run_id, attempt.step_id, attempt.attempt_no):
        raise ValueError("Transcript source reference does not belong to its attempt.")
    return reference


async def resolve_transcript_source_reference(
    *, attempt: FlowStepAttempt, transcript_source_repo: FlowTranscriptSourceRepository
) -> TranscriptSourceReference | None:
    """Validate a canonical attempt already scoped by its API or worker caller."""
    reference = _attempt_reference(attempt)
    if reference is None:
        return None
    stored = await transcript_source_repo.get_reference_for_attempt(
        tenant_id=attempt.tenant_id,
        run_id=reference.run_id,
        step_id=reference.step_id,
        attempt_no=reference.attempt_no,
    )
    if stored is None:
        raise MissingTranscriptSourceError(reference)
    if stored != reference:
        raise ValueError("Transcript source does not match its immutable reference.")
    return reference


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

    async def count_for_export(self, *, run_id: UUID, ceiling: int) -> int:
        return await self.transcript_source_repo.count_for_export(
            tenant_id=self.user.tenant_id, run_id=run_id, ceiling=ceiling
        )

    async def measure_for_export(
        self, *, run_id: UUID, candidate_limit: int
    ) -> TranscriptSourceExportMeasurement:
        return await self.transcript_source_repo.measure_for_export(
            tenant_id=self.user.tenant_id,
            run_id=run_id,
            candidate_limit=candidate_limit,
        )

    async def get_for_export(
        self, *, run_id: UUID, limit: int, attempts: Sequence[FlowStepAttempt]
    ) -> list[TranscriptSourceExportRow]:
        rows = await self.transcript_source_repo.list_for_export(
            tenant_id=self.user.tenant_id, run_id=run_id, limit=limit + 1
        )
        if len(rows) > limit:
            raise FileTooLargeException(
                "Flow evidence export contains too many transcript source rows.",
                code=FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE.value,
                context={
                    "section": "transcript_sources",
                    "limit": "section_rows",
                    "max_section_rows": limit,
                },
            )
        by_attempt = {(row.step_id, row.attempt_no): row for row in rows}
        for attempt in attempts:
            reference = _attempt_reference(attempt)
            if reference is None:
                continue
            source = by_attempt.get((reference.step_id, reference.attempt_no))
            if source is None:
                raise MissingTranscriptSourceError(reference)
            if (
                source.run_id != reference.run_id
                or source.source_hash != reference.source_hash
                or source.bounds != reference.bounds
            ):
                raise ValueError(
                    "Transcript source does not match its immutable reference."
                )
        return rows

    async def get_references_for_step_results(
        self, *, flow_id: UUID, run_id: UUID, step_results: Sequence[FlowStepResult]
    ) -> dict[UUID, TranscriptSourceReference]:
        await self.access_policy.load_run(
            run_id=run_id, flow_id=flow_id, access_kind="content"
        )
        references: dict[UUID, TranscriptSourceReference] = {}
        for result in step_results:
            if result.current_attempt_no is None:
                continue
            attempt = await self.flow_run_repo.get_step_attempt(
                run_id=run_id,
                tenant_id=self.user.tenant_id,
                step_id=result.step_id,
                attempt_no=result.current_attempt_no,
            )
            if attempt is None:
                continue
            reference = await resolve_transcript_source_reference(
                attempt=attempt, transcript_source_repo=self.transcript_source_repo
            )
            if reference is None:
                continue
            references[result.step_id] = reference
        return references

    async def _load_attempt(
        self, *, flow_id: UUID, run_id: UUID, step_id: UUID, attempt_no: int
    ) -> FlowStepAttempt:
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
        return attempt

    async def get_reference_for_attempt(
        self, *, flow_id: UUID, run_id: UUID, step_id: UUID, attempt_no: int
    ) -> TranscriptSourceReference | None:
        attempt = await self._load_attempt(
            flow_id=flow_id, run_id=run_id, step_id=step_id, attempt_no=attempt_no
        )
        return await resolve_transcript_source_reference(
            attempt=attempt, transcript_source_repo=self.transcript_source_repo
        )

    async def get_for_attempt(
        self, *, flow_id: UUID, run_id: UUID, step_id: UUID, attempt_no: int
    ) -> TranscriptSourceState:
        attempt = await self._load_attempt(
            flow_id=flow_id, run_id=run_id, step_id=step_id, attempt_no=attempt_no
        )
        reference = _attempt_reference(attempt)
        if reference is None:
            return UnavailablePreRowTranscriptSource()
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
