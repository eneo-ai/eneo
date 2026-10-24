"""Insert-only transcript snapshots; the caller owns their publication transaction."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import FlowStepAttempts, FlowStepTranscriptSources
from eneo.flows.domain.transcript_source import (
    TranscriptSource,
    TranscriptSourceBounds,
    TranscriptSourceExportRow,
    TranscriptSourceReference,
    TranscriptSourceSlice,
    transcript_source_reference,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository

# jsonpath subscripts are 32-bit; a page starting past this addresses only
# indexes no jsonb array reaches, so it is clamped and stays empty.
_MAX_JSONPATH_SUBSCRIPT = 2**31 - 1


@dataclass(frozen=True, slots=True)
class TranscriptSourceExportMeasurement:
    row_count: int
    stored_json_bytes: int
    logical_json_bytes: int


@dataclass(frozen=True, slots=True)
class TranscriptSourceAttemptReference:
    step_id: UUID
    attempt_no: int
    reference: TranscriptSourceReference
    stored_reference: TranscriptSourceReference | None


@dataclass(frozen=True, slots=True)
class TranscriptSourceAttemptPage:
    """One attempt's source marker and a page of the row stored for it.

    ``reference`` is None for an attempt from before source rows; ``page`` is
    None when no row is stored, and is not read without a marker."""

    reference: TranscriptSourceReference | None
    page: TranscriptSourceSlice | None


def _attempt_transcription() -> sa.ColumnElement[Any]:
    """The attempt input's ``transcription``, inside the v1 envelope or not."""
    payload = FlowStepAttempts.input_payload_json
    return sa.cast(
        sa.case(
            (
                payload["schema_version"].astext == "flow-step-attempt-input.v1",
                payload["resolved_input"]["transcription"],
            ),
            else_=payload["transcription"],
        ),
        JSONB,
    )


def _has_source_marker(transcription: sa.ColumnElement[Any]) -> sa.ColumnElement[bool]:
    return sa.and_(
        sa.func.jsonb_typeof(transcription) == "object",
        transcription.has_key("source"),
    )


def _attempt_source_row() -> sa.ColumnElement[bool]:
    return sa.and_(
        FlowStepTranscriptSources.tenant_id == FlowStepAttempts.tenant_id,
        FlowStepTranscriptSources.flow_run_id == FlowStepAttempts.flow_run_id,
        FlowStepTranscriptSources.step_id == FlowStepAttempts.step_id,
        FlowStepTranscriptSources.attempt_no == FlowStepAttempts.attempt_no,
    )


def _marker_reference(marker: object) -> TranscriptSourceReference:
    reference = transcript_source_reference({"transcription": {"source": marker}})
    assert reference is not None
    return reference


class FlowTranscriptSourceRepository:
    def __init__(self, *, session: AsyncSession):
        self.session = session

    async def get_references_for_attempts(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        step_attempts: Sequence[tuple[UUID, int]],
    ) -> list[TranscriptSourceAttemptReference]:
        if not step_attempts:
            return []
        transcription = _attempt_transcription()
        rows = (
            await self.session.execute(
                sa.select(
                    FlowStepAttempts.step_id,
                    FlowStepAttempts.attempt_no,
                    transcription["source"].label("reference"),
                    FlowStepTranscriptSources.id.label("source_id"),
                    FlowStepTranscriptSources.source_hash,
                    *(
                        getattr(FlowStepTranscriptSources, name)
                        for name in TranscriptSourceBounds.model_fields
                    ),
                )
                .select_from(FlowStepAttempts)
                .outerjoin(FlowStepTranscriptSources, _attempt_source_row())
                .where(
                    FlowStepAttempts.tenant_id == tenant_id,
                    FlowStepAttempts.flow_run_id == run_id,
                    sa.tuple_(
                        FlowStepAttempts.step_id, FlowStepAttempts.attempt_no
                    ).in_(step_attempts),
                    _has_source_marker(transcription),
                )
            )
        ).mappings()
        references: list[TranscriptSourceAttemptReference] = []
        for row in rows:
            reference = _marker_reference(row["reference"])
            stored = (
                TranscriptSourceReference(
                    run_id=run_id,
                    step_id=row["step_id"],
                    attempt_no=row["attempt_no"],
                    source_hash=row["source_hash"],
                    bounds=TranscriptSourceBounds.model_validate(
                        {
                            name: row[name]
                            for name in TranscriptSourceBounds.model_fields
                        }
                    ),
                )
                if row["source_id"] is not None
                else None
            )
            references.append(
                TranscriptSourceAttemptReference(
                    step_id=row["step_id"],
                    attempt_no=row["attempt_no"],
                    reference=reference,
                    stored_reference=stored,
                )
            )
        return references

    async def get_page_for_attempt(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        start: int,
        limit: int,
    ) -> TranscriptSourceAttemptPage | None:
        """The attempt's marker and lines ``start`` to ``start + limit - 1`` of
        its source, in one statement; None when the attempt does not exist.

        Only the page is sent and decoded; the database still reads the whole
        stored array to slice it. A stored value that is not an array of
        objects is read whole a second time, so it is refused, or read as no
        lines, exactly as ``get_for_attempt`` does."""
        transcription = _attempt_transcription()
        segments = FlowStepTranscriptSources.segments_json
        page_range = {
            "a": min(start, _MAX_JSONPATH_SUBSCRIPT),
            "b": min(start + limit - 1, _MAX_JSONPATH_SUBSCRIPT),
        }
        row = (
            (
                await self.session.execute(
                    sa.select(
                        _has_source_marker(transcription).label("has_marker"),
                        transcription["source"].label("reference"),
                        FlowStepTranscriptSources.id.label("source_id"),
                        FlowStepTranscriptSources.source_hash,
                        *(
                            getattr(FlowStepTranscriptSources, name)
                            for name in TranscriptSourceBounds.model_fields
                        ),
                        segments.is_(None).label("segments_null"),
                        # Each call reads the whole stored array, so one call
                        # both counts it and is null for anything but an array
                        # of objects.
                        sa.func.jsonb_path_query_first(
                            segments,
                            sa.cast(
                                sa.literal(
                                    "strict $ ? (!exists(@[*] ? "
                                    '(@.type() != "object"))).size()'
                                ),
                                JSONPATH,
                            ),
                            sa.literal({}, JSONB),
                            sa.true(),
                            type_=JSONB,
                        ).label("total"),
                        # Lax jsonpath clamps the range to the array.
                        sa.func.jsonb_path_query_array(
                            segments,
                            sa.cast(sa.literal("$[$a to $b]"), JSONPATH),
                            sa.bindparam("page_range", page_range, JSONB),
                            type_=JSONB,
                        ).label("segments"),
                        (
                            FlowStepTranscriptSources.detail_json
                            if start == 0
                            else sa.null()
                        ).label("speaker_review"),
                    )
                    .select_from(FlowStepAttempts)
                    .outerjoin(FlowStepTranscriptSources, _attempt_source_row())
                    .where(
                        FlowStepAttempts.tenant_id == tenant_id,
                        FlowStepAttempts.flow_run_id == run_id,
                        FlowStepAttempts.step_id == step_id,
                        FlowStepAttempts.attempt_no == attempt_no,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        if not row["has_marker"]:
            return TranscriptSourceAttemptPage(reference=None, page=None)
        reference = _marker_reference(row["reference"])
        if row["source_id"] is None:
            return TranscriptSourceAttemptPage(reference=reference, page=None)
        if row["segments_null"]:
            total, page = 0, None
        elif row["total"] is None:
            # The whole read refuses this row; only JSON null gets past it, and
            # reads as no lines.
            await self.get_for_attempt(
                tenant_id=tenant_id,
                run_id=run_id,
                step_id=step_id,
                attempt_no=attempt_no,
            )
            total, page = 0, None
        else:
            total, page = row["total"], row["segments"]
        return TranscriptSourceAttemptPage(
            reference=reference,
            page=TranscriptSourceSlice(
                start=start,
                total=total,
                segments=page,
                speaker_review=row["speaker_review"],
                source_hash=row["source_hash"],
                bounds=TranscriptSourceBounds.model_validate(
                    {name: row[name] for name in TranscriptSourceBounds.model_fields}
                ),
            ),
        )

    async def count_for_export(
        self, *, tenant_id: UUID, run_id: UUID, ceiling: int
    ) -> int:
        candidates = (
            sa.select(FlowStepTranscriptSources.id)
            .where(
                FlowStepTranscriptSources.tenant_id == tenant_id,
                FlowStepTranscriptSources.flow_run_id == run_id,
            )
            .limit(ceiling + 1)
            .subquery()
        )
        return int(
            await self.session.scalar(
                sa.select(sa.func.count()).select_from(candidates)
            )
            or 0
        )

    async def measure_for_export(
        self, *, tenant_id: UUID, run_id: UUID, candidate_limit: int
    ) -> TranscriptSourceExportMeasurement:
        columns = (
            FlowStepTranscriptSources.segments_json,
            FlowStepTranscriptSources.detail_json,
        )
        candidates = (
            sa.select(
                sum(
                    (
                        sa.func.coalesce(sa.func.pg_column_size(column), 0)
                        for column in columns
                    ),
                    sa.literal(0),
                ).label("stored"),
                sum(
                    (
                        sa.func.coalesce(
                            sa.func.octet_length(sa.cast(column, sa.Text)), 0
                        )
                        for column in columns
                    ),
                    sa.literal(0),
                ).label("logical"),
            )
            .where(
                FlowStepTranscriptSources.tenant_id == tenant_id,
                FlowStepTranscriptSources.flow_run_id == run_id,
            )
            .limit(candidate_limit)
            .subquery()
        )
        row = (
            await self.session.execute(
                sa.select(
                    sa.func.count(),
                    sa.func.coalesce(sa.func.sum(candidates.c.stored), 0),
                    sa.func.coalesce(sa.func.sum(candidates.c.logical), 0),
                )
            )
        ).one()
        return TranscriptSourceExportMeasurement(
            row_count=int(row[0]),
            stored_json_bytes=int(row[1]),
            logical_json_bytes=int(row[2]),
        )

    async def list_for_export(
        self, *, tenant_id: UUID, run_id: UUID, limit: int
    ) -> list[TranscriptSourceExportRow]:
        rows = await self.session.scalars(
            sa.select(FlowStepTranscriptSources)
            .where(
                FlowStepTranscriptSources.tenant_id == tenant_id,
                FlowStepTranscriptSources.flow_run_id == run_id,
            )
            .order_by(
                FlowStepTranscriptSources.step_id, FlowStepTranscriptSources.attempt_no
            )
            .limit(limit)
        )
        return [
            TranscriptSourceExportRow(
                id=row.id,
                tenant_id=row.tenant_id,
                flow_id=row.flow_id,
                run_id=row.flow_run_id,
                step_id=row.step_id,
                attempt_no=row.attempt_no,
                created_at=row.created_at,
                source_hash=row.source_hash,
                segments=row.segments_json,
                speaker_review=row.detail_json,
                bounds=TranscriptSourceBounds.model_validate(row, from_attributes=True),
            )
            for row in rows
        ]

    async def get_reference_for_attempt(
        self, *, tenant_id: UUID, run_id: UUID, step_id: UUID, attempt_no: int
    ) -> TranscriptSourceReference | None:
        row = (
            (
                await self.session.execute(
                    sa.select(
                        FlowStepTranscriptSources.source_hash,
                        *(
                            getattr(FlowStepTranscriptSources, name)
                            for name in TranscriptSourceBounds.model_fields
                        ),
                    ).where(
                        FlowStepTranscriptSources.tenant_id == tenant_id,
                        FlowStepTranscriptSources.flow_run_id == run_id,
                        FlowStepTranscriptSources.step_id == step_id,
                        FlowStepTranscriptSources.attempt_no == attempt_no,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return TranscriptSourceReference(
            run_id=run_id,
            step_id=step_id,
            attempt_no=attempt_no,
            source_hash=row["source_hash"],
            bounds=TranscriptSourceBounds.model_validate(
                {name: row[name] for name in TranscriptSourceBounds.model_fields}
            ),
        )

    async def insert(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        reference: TranscriptSourceReference,
        source: TranscriptSource,
    ) -> None:
        if (
            reference.source_hash != source.source_hash
            or reference.bounds != source.bounds
        ):
            raise ValueError("Transcript source does not match its reference.")
        await FlowRunRepository(session=self.session).lock_execution_ownership(
            run_id=reference.run_id, tenant_id=tenant_id
        )
        await self.session.execute(
            sa.insert(FlowStepTranscriptSources).values(
                tenant_id=tenant_id,
                flow_id=flow_id,
                flow_run_id=reference.run_id,
                step_id=reference.step_id,
                attempt_no=reference.attempt_no,
                source_hash=source.source_hash,
                segments_json=source.segments,
                detail_json=source.speaker_review,
                **source.bounds.model_dump(mode="json"),
            )
        )

    async def get_for_attempt(
        self, *, tenant_id: UUID, run_id: UUID, step_id: UUID, attempt_no: int
    ) -> TranscriptSource | None:
        row = await self.session.scalar(
            sa.select(FlowStepTranscriptSources).where(
                FlowStepTranscriptSources.tenant_id == tenant_id,
                FlowStepTranscriptSources.flow_run_id == run_id,
                FlowStepTranscriptSources.step_id == step_id,
                FlowStepTranscriptSources.attempt_no == attempt_no,
            )
        )
        if row is None:
            return None
        return TranscriptSource(
            segments=row.segments_json,
            speaker_review=row.detail_json,
            source_hash=row.source_hash,
            bounds=TranscriptSourceBounds.model_validate(row, from_attributes=True),
        )
