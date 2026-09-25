"""Durable live transcripts; each socket write owns one short transaction."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import sessionmanager
from eneo.database.tables.flow_tables import FlowLiveTranscripts, Flows
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.runtime.live_transcription.tickets import LiveTranscriptionGrant
from eneo.main.exceptions import ConflictException, NotFoundException


@dataclass(frozen=True, slots=True)
class LiveTranscriptPurgeCounts:
    candidate_count: int
    purged_count: int


@dataclass(frozen=True, slots=True)
class LiveTranscriptScope:
    tenant_id: UUID
    user_id: UUID | None
    flow_id: UUID
    flow_version: int
    step_id: UUID
    model_id: UUID | None

    def matches(self, row: FlowLiveTranscripts) -> bool:
        return (
            row.tenant_id == self.tenant_id
            and row.user_id == self.user_id
            and row.flow_id == self.flow_id
            and row.flow_version == self.flow_version
            and row.step_id == self.step_id
            and row.model_id == self.model_id
            and (row.expires_at is None or row.expires_at > datetime.now(timezone.utc))
        )


class LiveTranscriptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, transcript_id: UUID, *, tenant_id: UUID, lock_for_binding: bool = False
    ) -> FlowLiveTranscripts | None:
        statement = sa.select(FlowLiveTranscripts).where(
            FlowLiveTranscripts.id == transcript_id,
            FlowLiveTranscripts.tenant_id == tenant_id,
        )
        if lock_for_binding:
            if not self.session.in_transaction():
                raise RuntimeError(
                    "Live transcript binding requires an active transaction."
                )
            statement = statement.with_for_update(
                of=FlowLiveTranscripts
            ).execution_options(populate_existing=True)
        return await self.session.scalar(statement)

    async def bind(
        self, transcript_id: UUID, *, file_id: UUID, scope: LiveTranscriptScope
    ) -> None:
        row = await self.get(
            transcript_id, tenant_id=scope.tenant_id, lock_for_binding=True
        )
        if row is None or not scope.matches(row):
            raise NotFoundException(
                "Live transcript not found.",
                code=FlowApiErrorCode.RUN_LIVE_TRANSCRIPT_NOT_FOUND.value,
            )
        if row.bound_file_id is not None and row.bound_file_id != file_id:
            raise ConflictException(
                "Live transcript is already bound to another file.",
                code=FlowApiErrorCode.RUN_LIVE_TRANSCRIPT_ALREADY_BOUND.value,
            )
        row.bound_file_id = file_id
        await self.session.flush()

    async def create(
        self,
        grant: LiveTranscriptionGrant,
        *,
        text: str,
        segments: list[dict[str, str | float]] | None,
        received_audio_seconds: float,
    ) -> UUID:
        if grant.recording_id is None:
            raise ValueError("A live transcript requires a recording identity.")
        days = (
            await self.session.execute(
                sa.select(Tenants.flow_runtime_upload_abandonment_days).where(
                    Tenants.id == grant.tenant_id
                )
            )
        ).scalar_one()
        now = datetime.now(timezone.utc)
        statement = (
            sa.insert(FlowLiveTranscripts)
            .values(
                tenant_id=grant.tenant_id,
                user_id=grant.user_id,
                flow_id=grant.flow_id,
                flow_version=grant.flow_version,
                step_id=grant.step_id,
                model_id=grant.model_id,
                recording_id=grant.recording_id,
                text=text,
                segments=segments,
                received_audio_seconds=received_audio_seconds,
                created_at=now,
                expires_at=now + timedelta(days=days) if days is not None else None,
            )
            .returning(FlowLiveTranscripts.id)
        )
        return (await self.session.execute(statement)).scalar_one()

    async def delete_expired_unbound(
        self,
        *,
        tenant_id: UUID,
        now: datetime,
        limit: int,
        dry_run: bool,
        space_id: UUID | None = None,
        flow_id: UUID | None = None,
    ) -> LiveTranscriptPurgeCounts:
        candidates = (
            sa.select(FlowLiveTranscripts.id)
            .join(
                Flows,
                sa.and_(
                    Flows.id == FlowLiveTranscripts.flow_id,
                    Flows.tenant_id == FlowLiveTranscripts.tenant_id,
                ),
            )
            .where(
                FlowLiveTranscripts.tenant_id == tenant_id,
                FlowLiveTranscripts.bound_file_id.is_(None),
                FlowLiveTranscripts.expires_at <= now,
            )
            .order_by(FlowLiveTranscripts.expires_at, FlowLiveTranscripts.id)
            .limit(limit)
        )
        if space_id is not None:
            candidates = candidates.where(Flows.space_id == space_id)
        if flow_id is not None:
            candidates = candidates.where(FlowLiveTranscripts.flow_id == flow_id)
        if not dry_run:
            candidates = candidates.with_for_update(
                of=FlowLiveTranscripts, skip_locked=True
            )
        ids = list(await self.session.scalars(candidates))
        purged_count = 0
        if ids and not dry_run:
            purged_ids = await self.session.scalars(
                sa.delete(FlowLiveTranscripts)
                .where(
                    FlowLiveTranscripts.id.in_(ids),
                    FlowLiveTranscripts.tenant_id == tenant_id,
                    FlowLiveTranscripts.bound_file_id.is_(None),
                )
                .returning(FlowLiveTranscripts.id)
            )
            purged_count = len(purged_ids.all())
        return LiveTranscriptPurgeCounts(
            candidate_count=len(ids), purged_count=purged_count
        )


async def persist_live_transcript(
    grant: LiveTranscriptionGrant,
    *,
    text: str,
    segments: list[dict[str, str | float]] | None,
    received_audio_seconds: float,
) -> UUID:
    async with sessionmanager.session() as session, session.begin():
        transcript_id = await LiveTranscriptRepository(session).create(
            grant,
            text=text,
            segments=segments,
            received_audio_seconds=received_audio_seconds,
        )
    return transcript_id
