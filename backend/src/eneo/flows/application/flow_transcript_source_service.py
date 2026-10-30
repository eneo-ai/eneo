"""Resolve immutable transcript evidence under the run's content access policy."""

from collections.abc import Sequence
from typing import TypeVar
from uuid import UUID

from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.domain.flow import (
    FlowRunStatusSnapshot,
    FlowStepAttempt,
    FlowStepResult,
)
from eneo.flows.domain.transcript_source import (
    MissingTranscriptSourceError,
    OmittedTranscriptSource,
    PresentTranscriptSource,
    PresentTranscriptSourceSlice,
    TranscriptComponentOmissions,
    TranscriptSource,
    TranscriptSourceBounds,
    TranscriptSourceExportRow,
    TranscriptSourcePageState,
    TranscriptSourceReference,
    TranscriptSourceSlice,
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

_Stored = TypeVar(
    "_Stored", TranscriptSourceReference, TranscriptSource, TranscriptSourceSlice
)


def _require_own_reference(
    reference: TranscriptSourceReference,
    *,
    run_id: UUID,
    step_id: UUID,
    attempt_no: int,
) -> None:
    if (reference.run_id, reference.step_id, reference.attempt_no) != (
        run_id,
        step_id,
        attempt_no,
    ):
        raise ValueError("Transcript source reference does not belong to its attempt.")


def _matching_source(
    reference: TranscriptSourceReference, stored: _Stored | None
) -> _Stored:
    """What is stored for ``reference``, refused when it is missing or is not
    the immutable source the reference names."""
    if stored is None:
        raise MissingTranscriptSourceError(reference)
    if stored.source_hash != reference.source_hash or stored.bounds != reference.bounds:
        raise ValueError("Transcript source does not match its immutable reference.")
    return stored


def _source_or_omitted(
    reference: TranscriptSourceReference, stored: _Stored | None
) -> _Stored | OmittedTranscriptSource:
    """The stored source or page ``reference`` names, or its omitted state when
    its lines were not stored; refused as ``_matching_source`` refuses."""
    source = _matching_source(reference, stored)
    reason = source.bounds.segments_omitted_reason
    if reason is not None:
        return OmittedTranscriptSource(reason=reason, bounds=source.bounds)
    return source


def _component_omissions(
    bounds: TranscriptSourceBounds,
) -> TranscriptComponentOmissions:
    return TranscriptComponentOmissions(
        detail=bounds.detail_omitted_reason, words=bounds.words_omitted_reason
    )


def _attempt_reference(attempt: FlowStepAttempt) -> TranscriptSourceReference | None:
    reference = transcript_source_reference(attempt.input_payload_json)
    if reference is not None:
        _require_own_reference(
            reference,
            run_id=attempt.flow_run_id,
            step_id=attempt.step_id,
            attempt_no=attempt.attempt_no,
        )
    return reference


async def resolve_transcript_source_reference(
    *, attempt: FlowStepAttempt, transcript_source_repo: FlowTranscriptSourceRepository
) -> TranscriptSourceReference | None:
    """Validate a canonical attempt already scoped by its API or worker caller."""
    reference = _attempt_reference(attempt)
    if reference is None:
        return None
    _matching_source(
        reference,
        await transcript_source_repo.get_reference_for_attempt(
            tenant_id=attempt.tenant_id,
            run_id=reference.run_id,
            step_id=reference.step_id,
            attempt_no=reference.attempt_no,
        ),
    )
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
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        step_results: Sequence[FlowStepResult],
        history: bool = False,
    ) -> dict[UUID, TranscriptSourceReference]:
        await self.access_policy.load_run_status(
            run_id=run_id, flow_id=flow_id, access_kind="content", history=history
        )
        projections = await self.transcript_source_repo.get_references_for_attempts(
            run_id=run_id,
            tenant_id=self.user.tenant_id,
            step_attempts=[
                (result.step_id, result.current_attempt_no)
                for result in step_results
                if result.current_attempt_no is not None
            ],
        )
        references: dict[UUID, TranscriptSourceReference] = {}
        for projection in projections:
            reference = projection.reference
            _require_own_reference(
                reference,
                run_id=run_id,
                step_id=projection.step_id,
                attempt_no=projection.attempt_no,
            )
            _matching_source(reference, projection.stored_reference)
            references[projection.step_id] = reference
        return references

    async def _load_attempt(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        history: bool,
    ) -> FlowStepAttempt:
        run = await self.access_policy.load_run_status(
            run_id=run_id, flow_id=flow_id, access_kind="content", history=history
        )
        return await self._attempt_of(run=run, step_id=step_id, attempt_no=attempt_no)

    async def _attempt_of(
        self, *, run: FlowRunStatusSnapshot, step_id: UUID, attempt_no: int
    ) -> FlowStepAttempt:
        attempt = await self.flow_run_repo.get_step_attempt(
            run_id=run.id,
            step_id=step_id,
            attempt_no=attempt_no,
            tenant_id=self.user.tenant_id,
        )
        if attempt is None:
            raise NotFoundException("Flow run step attempt not found.")
        return attempt

    async def get_reference_for_run_attempt(
        self, *, run: FlowRunStatusSnapshot, step_id: UUID, attempt_no: int
    ) -> TranscriptSourceReference | None:
        """The validated source reference of an attempt in a run the caller
        has already authorized for content; ``run`` is not authorized again."""
        attempt = await self._attempt_of(
            run=run, step_id=step_id, attempt_no=attempt_no
        )
        return await resolve_transcript_source_reference(
            attempt=attempt, transcript_source_repo=self.transcript_source_repo
        )

    async def get_for_attempt(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        history: bool = False,
    ) -> TranscriptSourceState:
        attempt = await self._load_attempt(
            flow_id=flow_id,
            run_id=run_id,
            step_id=step_id,
            attempt_no=attempt_no,
            history=history,
        )
        reference = _attempt_reference(attempt)
        if reference is None:
            return UnavailablePreRowTranscriptSource()
        source = _source_or_omitted(
            reference,
            await self.transcript_source_repo.get_for_attempt(
                tenant_id=self.user.tenant_id,
                run_id=reference.run_id,
                step_id=reference.step_id,
                attempt_no=reference.attempt_no,
            ),
        )
        if isinstance(source, OmittedTranscriptSource):
            return source
        return PresentTranscriptSource(
            source=source, component_omissions=_component_omissions(source.bounds)
        )

    async def get_page_for_attempt(
        self,
        *,
        run: FlowRunStatusSnapshot,
        step_id: UUID,
        attempt_no: int,
        start: int,
        limit: int,
    ) -> TranscriptSourcePageState:
        """``get_for_attempt`` for one page of lines, from absolute index
        ``start``, refused and degraded exactly as the whole source is. The
        caller has already authorized ``run`` for content; it is not authorized
        again."""
        attempt = await self.transcript_source_repo.get_page_for_attempt(
            tenant_id=self.user.tenant_id,
            run_id=run.id,
            step_id=step_id,
            attempt_no=attempt_no,
            start=start,
            limit=limit,
        )
        if attempt is None:
            raise NotFoundException("Flow run step attempt not found.")
        reference = attempt.reference
        if reference is None:
            return UnavailablePreRowTranscriptSource()
        _require_own_reference(
            reference, run_id=run.id, step_id=step_id, attempt_no=attempt_no
        )
        page = _source_or_omitted(reference, attempt.page)
        if isinstance(page, OmittedTranscriptSource):
            return page
        return PresentTranscriptSourceSlice(
            page=page, component_omissions=_component_omissions(page.bounds)
        )
