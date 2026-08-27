from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from secrets import token_hex
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.affected_rows import affected_row_count
from eneo.database.database import DatabaseSessionManager, sessionmanager
from eneo.database.tables.file_icon_backfill_table import (
    FileIconBackfillCampaign,
    FileIconBackfillItems,
)
from eneo.database.tables.files_table import Files
from eneo.database.tables.icons_table import Icons
from eneo.database.tables.object_content_policy_table import (
    ObjectContentDeploymentPolicy,
)
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    IconContentReferences,
    ObjectContents,
)
from eneo.object_content.content import (
    CapturedContent,
    ContentAccessClass,
    ContentIntent,
    ContentState,
    ContentTooLargeError,
    ObjectContentIdempotencyConflictError,
    ObjectContentIntegrityError,
    ObjectContentStateError,
    StorageKind,
)
from eneo.object_content.content_service import ObjectContentService

_MEBIBYTE = 1024 * 1024
_GIBIBYTE = 1024 * _MEBIBYTE
_ADVISORY_LOCK_CLASS = 1_162_757_455  # ASCII "ENEO"
_ADVISORY_LOCK_ID = 1_179_206_214  # ASCII "FIBF"


class FileIconBackfillSettings(BaseSettings):
    """Fixed worker bounds and the explicit one-time inline capacity grant."""

    model_config = SettingsConfigDict(
        env_prefix="FILE_ICON_BACKFILL_",
        env_file=None,
        extra="forbid",
    )

    auto_inline_max_bytes: int = Field(default=5 * _GIBIBYTE, ge=0)
    inline_capacity_ack: int = Field(default=0, ge=0)
    batch_rows: int = Field(default=100, ge=1, le=1000)
    batch_bytes: int = Field(default=32 * _MEBIBYTE, ge=1)
    lease_seconds: int = Field(default=300, ge=1)
    resume_revision: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)


class FileIconBackfillState(StrEnum):
    WAITING_FOR_CAPACITY = "waiting_for_capacity"
    WAITING_FOR_OBJECT_STORE = "waiting_for_object_store"
    ACTIVE = "active"
    HALTED = "halted"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class FileIconBackfillResult:
    state: FileIconBackfillState
    target_kind: StorageKind | None
    claimed_count: int
    completed_count: int
    cancelled_count: int
    failed_count: int
    detail: str | None


@dataclass(frozen=True, slots=True)
class _Campaign:
    state: FileIconBackfillState
    target_kind: StorageKind | None
    detail: str | None


@dataclass(frozen=True, slots=True)
class _WorkItem:
    id: int
    owner_kind: str
    owner_id: UUID
    variant: str
    ordinal: int
    tenant_id: UUID
    payload_size_estimate: int
    lease_owner: str


@dataclass(frozen=True, slots=True)
class _LegacySource:
    payload: bytes | None
    media_type: str
    created_by_user_id: UUID | None


@dataclass(frozen=True, slots=True)
class _ExistingReference:
    content_id: UUID
    state: ContentState
    page_number: int | None = None
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None


class _OwnerDeleted(Exception):
    pass


class _LegacySourceMissing(Exception):
    pass


class _LeaseLost(Exception):
    pass


async def _one_chunk(payload: bytes) -> AsyncIterator[bytes]:
    yield payload


class _FileIconBackfillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def campaign_or_start(
        self,
        settings: FileIconBackfillSettings,
    ) -> _Campaign:
        campaign = await self._session.scalar(
            sa.select(FileIconBackfillCampaign).with_for_update()
        )
        if campaign is not None:
            if campaign.state == FileIconBackfillState.ACTIVE.value:
                policy_target = await self.policy_target()
                if campaign.target_kind != policy_target.value:
                    campaign.state = FileIconBackfillState.HALTED.value
                    campaign.resume_cursor_id = None
                    campaign.halt_reason = (
                        "The deployment storage target changed after the File/Icon "
                        "backfill campaign started"
                    )
                    await self._session.flush()
            if (
                campaign.state == FileIconBackfillState.HALTED.value
                and settings.resume_revision > campaign.resume_revision
            ):
                policy_target = await self.policy_target()
                if campaign.target_kind == policy_target.value:
                    campaign.state = FileIconBackfillState.ACTIVE.value
                    campaign.halt_reason = None
                    campaign.resume_revision = settings.resume_revision
                    campaign.resume_cursor_id = 0
            if (
                campaign.state == FileIconBackfillState.ACTIVE.value
                and campaign.resume_cursor_id is not None
                and not await self._has_actionable_items()
            ):
                await self._resume_failed_batch(campaign, settings.batch_rows)
            await self._session.flush()
            return _Campaign(
                state=FileIconBackfillState(campaign.state),
                target_kind=StorageKind(campaign.target_kind),
                detail=campaign.halt_reason,
            )

        if not await self.has_ledger_items():
            return await self._insert_campaign(
                state=FileIconBackfillState.COMPLETE,
                resume_revision=settings.resume_revision,
            )

        policy_target = await self.policy_target()
        if policy_target is StorageKind.OBJECT_STORE:
            return _Campaign(
                state=FileIconBackfillState.WAITING_FOR_OBJECT_STORE,
                target_kind=StorageKind.OBJECT_STORE,
                detail="The object-store backfill adapter is not active in this release",
            )

        required_bytes = await self.capacity_required_bytes()
        capacity_granted = (
            required_bytes <= settings.auto_inline_max_bytes
            or settings.inline_capacity_ack >= required_bytes
        )
        if not capacity_granted:
            return _Campaign(
                state=FileIconBackfillState.WAITING_FOR_CAPACITY,
                target_kind=StorageKind.POSTGRES_INLINE,
                detail=(
                    "The upgrade is complete and existing File/Icon content remains "
                    "readable, but legacy adoption is waiting for an inline capacity "
                    f"decision. The backfill estimates {required_bytes} bytes; set "
                    "FILE_ICON_BACKFILL_INLINE_CAPACITY_ACK to at least that value "
                    "after reserving payload, WAL, and safety headroom"
                ),
            )
        return await self._insert_campaign(
            state=FileIconBackfillState.ACTIVE,
            resume_revision=settings.resume_revision,
        )

    async def _insert_campaign(
        self,
        *,
        state: FileIconBackfillState,
        resume_revision: int,
    ) -> _Campaign:
        statement = (
            insert(FileIconBackfillCampaign)
            .values(
                id=uuid4(),
                target_kind=StorageKind.POSTGRES_INLINE.value,
                destination_revision=None,
                state=state.value,
                resume_revision=resume_revision,
            )
            .on_conflict_do_nothing()
        )
        await self._session.execute(statement)
        row = (
            await self._session.scalars(
                sa.select(FileIconBackfillCampaign).with_for_update()
            )
        ).one()
        return _Campaign(
            state=FileIconBackfillState(row.state),
            target_kind=StorageKind(row.target_kind),
            detail=row.halt_reason,
        )

    async def policy_target(self) -> StorageKind:
        target = await self._session.scalar(
            sa.select(ObjectContentDeploymentPolicy.new_write_storage_target).where(
                ObjectContentDeploymentPolicy.id == 1
            )
        )
        if target is None:
            raise RuntimeError("Object-content deployment policy is missing")
        return StorageKind(target)

    async def has_campaign(self) -> bool:
        return bool(
            await self._session.scalar(
                sa.select(sa.exists().where(FileIconBackfillCampaign.id.is_not(None)))
            )
        )

    async def has_ledger_items(self) -> bool:
        return bool(
            await self._session.scalar(
                sa.select(sa.exists().where(FileIconBackfillItems.id.is_not(None)))
            )
        )

    async def claim(
        self,
        settings: FileIconBackfillSettings,
    ) -> tuple[_WorkItem, ...]:
        now = await self._database_now()
        candidates = (
            await self._session.scalars(
                sa.select(FileIconBackfillItems)
                .where(
                    sa.or_(
                        FileIconBackfillItems.state == "pending",
                        sa.and_(
                            FileIconBackfillItems.state == "leased",
                            FileIconBackfillItems.lease_expires_at <= now,
                        ),
                    )
                )
                .order_by(FileIconBackfillItems.id)
                .limit(settings.batch_rows)
                .with_for_update(skip_locked=True)
            )
        ).all()
        selected: list[FileIconBackfillItems] = []
        estimated_bytes = 0
        for candidate in candidates:
            next_bytes = estimated_bytes + candidate.payload_size_estimate
            if selected and next_bytes > settings.batch_bytes:
                break
            selected.append(candidate)
            estimated_bytes = next_bytes

        lease_owner = token_hex(16)
        lease_expires_at = now + timedelta(seconds=settings.lease_seconds)
        work: list[_WorkItem] = []
        for item in selected:
            item.state = "leased"
            item.lease_owner = lease_owner
            item.lease_expires_at = lease_expires_at
            item.last_error_code = None
            item.last_error_detail = None
            item.updated_at = now
            work.append(
                _WorkItem(
                    id=item.id,
                    owner_kind=item.owner_kind,
                    owner_id=item.owner_id,
                    variant=item.variant,
                    ordinal=item.ordinal,
                    tenant_id=item.tenant_id,
                    payload_size_estimate=item.payload_size_estimate,
                    lease_owner=lease_owner,
                )
            )
        await self._session.flush()
        return tuple(work)

    async def _resume_failed_batch(
        self,
        campaign: FileIconBackfillCampaign,
        batch_rows: int,
    ) -> None:
        candidates = (
            await self._session.scalars(
                sa.select(FileIconBackfillItems)
                .where(
                    FileIconBackfillItems.state == "failed",
                    FileIconBackfillItems.lease_expires_at.is_(None),
                    FileIconBackfillItems.failure_revision < campaign.resume_revision,
                    FileIconBackfillItems.id > campaign.resume_cursor_id,
                )
                # Keep the constant lease key so the claim index supplies id order.
                .order_by(
                    FileIconBackfillItems.lease_expires_at,
                    FileIconBackfillItems.id,
                )
                .limit(batch_rows + 1)
                .with_for_update()
            )
        ).all()
        batch = candidates[:batch_rows]
        now = await self._database_now()
        for item in batch:
            item.state = "pending"
            item.attempts = 0
            item.last_error_code = None
            item.last_error_detail = None
            item.failure_revision = None
            item.lease_owner = None
            item.lease_expires_at = None
            item.updated_at = now
        campaign.resume_cursor_id = (
            batch[-1].id if len(candidates) > batch_rows else None
        )

    async def begin_attempt(self, item: _WorkItem) -> int:
        ledger = await self._leased_item(item)
        ledger.attempts += 1
        ledger.updated_at = datetime.now(UTC)
        await self._session.flush()
        return ledger.attempts

    async def legacy_source(self, item: _WorkItem) -> _LegacySource:
        if item.owner_kind == "file":
            if item.variant == "transcription":
                payload_column = Files.legacy_transcription
                media_type = "text/plain"
            elif item.variant == "original":
                payload_column = Files.legacy_blob
                media_type = None
            elif item.variant == "extracted_text":
                payload_column = Files.legacy_text
                media_type = "text/plain"
            elif item.variant in {"derived_page", "legacy_image"}:
                payload_column = Files.legacy_blob
                media_type = None
            else:
                raise _LegacySourceMissing
            row = (
                await self._session.execute(
                    sa.select(
                        Files.user_id,
                        Files.tenant_id,
                        Files.mimetype,
                        payload_column.label("payload"),
                    ).where(Files.id == item.owner_id)
                )
            ).one_or_none()
            if row is None:
                raise _OwnerDeleted
            if row.tenant_id != item.tenant_id:
                raise _LegacySourceMissing
            payload = row.payload
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            return _LegacySource(
                payload=payload,
                media_type=media_type or row.mimetype or "application/octet-stream",
                created_by_user_id=row.user_id,
            )

        if item.owner_kind == "icon" and item.variant == "primary":
            row = (
                await self._session.execute(
                    sa.select(
                        Icons.tenant_id,
                        Icons.legacy_blob,
                        Icons.legacy_mimetype,
                    ).where(Icons.id == item.owner_id)
                )
            ).one_or_none()
            if row is None:
                raise _OwnerDeleted
            if row.tenant_id != item.tenant_id:
                raise _LegacySourceMissing
            return _LegacySource(
                payload=row.legacy_blob,
                media_type=row.legacy_mimetype or "application/octet-stream",
                created_by_user_id=None,
            )
        raise _LegacySourceMissing

    async def source_or_complete(
        self,
        item: _WorkItem,
    ) -> _LegacySource | None:
        existing = await self._existing_reference(item)
        if existing is None or existing.state is not ContentState.AVAILABLE:
            return await self.legacy_source(item)
        if not await self._lock_owner(item):
            raise _OwnerDeleted
        existing = await self._existing_reference(item, lock=True)
        if existing is None or existing.state is not ContentState.AVAILABLE:
            return await self.legacy_source(item)
        ledger = await self._leased_item(item)
        ledger.state = "done"
        ledger.content_id = existing.content_id
        ledger.failure_revision = None
        self._clear_lease(ledger)
        await self._session.flush()
        return None

    async def complete_inline(
        self,
        item: _WorkItem,
        created_by_user_id: UUID | None,
        captured: CapturedContent,
        object_content: ObjectContentService,
    ) -> bool:
        ledger = await self._leased_item(item)
        if not await self._lock_owner(item):
            self._cancel(ledger)
            return False

        existing = await self._existing_reference(item, lock=True)
        if existing is not None and existing.state is ContentState.AVAILABLE:
            ledger.state = "done"
            ledger.content_id = existing.content_id
            ledger.failure_revision = None
            self._clear_lease(ledger)
            await self._session.flush()
            return True

        owner_intent_key = (
            f"file:{item.owner_id}:{item.variant}:{item.ordinal}"
            if item.owner_kind == "file"
            else f"icon:{item.owner_id}:primary"
        )
        intent_key = (
            owner_intent_key
            if existing is None
            else f"{owner_intent_key}:replace:{existing.content_id}"
        )
        prepared = await object_content.prepare_in_transaction(
            self._session,
            intent=ContentIntent(
                tenant_id=item.tenant_id,
                created_by_user_id=created_by_user_id,
                access_class=(
                    ContentAccessClass.PRIVATE_RESOURCE
                    if item.owner_kind == "file"
                    else ContentAccessClass.PUBLIC_IMMUTABLE
                ),
                idempotency_key=intent_key,
                producer_receipt=intent_key,
            ),
            content=captured,
            storage_kind=StorageKind.POSTGRES_INLINE,
        )
        if prepared.state is not ContentState.AVAILABLE:
            raise ObjectContentStateError(
                "Legacy backfill replacement content is not available"
            )
        if existing is not None:
            await self._delete_reference(item, content_id=existing.content_id)
        if item.owner_kind == "file":
            reference = FileContentReferences()
            reference.file_id = item.owner_id
            reference.content_id = prepared.id
            reference.variant = item.variant
            reference.ordinal = item.ordinal
            if existing is not None:
                reference.page_number = existing.page_number
                reference.width = existing.width
                reference.height = existing.height
                reference.duration_ms = existing.duration_ms
            self._session.add(reference)
        else:
            reference = IconContentReferences()
            reference.icon_id = item.owner_id
            reference.content_id = prepared.id
            reference.variant = "primary"
            self._session.add(reference)

        ledger.state = "done"
        ledger.content_id = prepared.id
        ledger.failure_revision = None
        self._clear_lease(ledger)
        await self._session.flush()
        return True

    async def cancel(self, item: _WorkItem) -> None:
        ledger = await self._leased_item(item)
        self._cancel(ledger)
        await self._session.flush()

    async def fail(self, item: _WorkItem, *, code: str, detail: str) -> None:
        ledger = await self._leased_item(item)
        failure_revision = (
            await self._session.execute(
                sa.select(FileIconBackfillCampaign.resume_revision)
            )
        ).scalar_one()
        ledger.state = "failed"
        ledger.content_id = None
        ledger.last_error_code = code
        ledger.last_error_detail = detail[:512]
        ledger.failure_revision = failure_revision
        self._clear_lease(ledger)
        await self._session.flush()

    async def finish_campaign(self) -> _Campaign:
        campaign = (
            await self._session.scalars(
                sa.select(FileIconBackfillCampaign).with_for_update()
            )
        ).one()
        actionable = await self._has_actionable_items()
        if not actionable:
            if campaign.resume_cursor_id is not None:
                await self._session.flush()
                return _Campaign(
                    state=FileIconBackfillState(campaign.state),
                    target_kind=StorageKind(campaign.target_kind),
                    detail=campaign.halt_reason,
                )
            failed = bool(
                await self._session.scalar(
                    sa.select(
                        sa.exists().where(FileIconBackfillItems.state == "failed")
                    )
                )
            )
            if failed:
                campaign.state = FileIconBackfillState.HALTED.value
                campaign.halt_reason = (
                    "One or more File/Icon backfill items require operator action"
                )
            else:
                campaign.state = FileIconBackfillState.COMPLETE.value
                campaign.halt_reason = None
                await self._analyze_targets()
        await self._session.flush()
        return _Campaign(
            state=FileIconBackfillState(campaign.state),
            target_kind=StorageKind(campaign.target_kind),
            detail=campaign.halt_reason,
        )

    async def capacity_required_bytes(self) -> int:
        available_file_reference = sa.exists(
            sa.select(FileContentReferences.content_id)
            .join(ObjectContents, ObjectContents.id == FileContentReferences.content_id)
            .where(
                FileContentReferences.file_id == FileIconBackfillItems.owner_id,
                FileContentReferences.variant == FileIconBackfillItems.variant,
                FileContentReferences.ordinal == FileIconBackfillItems.ordinal,
                ObjectContents.state == ContentState.AVAILABLE.value,
            )
        )
        available_icon_reference = sa.exists(
            sa.select(IconContentReferences.content_id)
            .join(ObjectContents, ObjectContents.id == IconContentReferences.content_id)
            .where(
                IconContentReferences.icon_id == FileIconBackfillItems.owner_id,
                IconContentReferences.variant == FileIconBackfillItems.variant,
                ObjectContents.state == ContentState.AVAILABLE.value,
            )
        )
        required_bytes = await self._session.scalar(
            sa.select(
                sa.func.coalesce(
                    sa.func.sum(FileIconBackfillItems.payload_size_estimate).filter(
                        FileIconBackfillItems.state.not_in(("done", "cancelled"))
                    ),
                    0,
                )
            ).where(
                FileIconBackfillItems.state.not_in(("done", "cancelled")),
                sa.or_(
                    sa.and_(
                        FileIconBackfillItems.owner_kind == "file",
                        sa.exists().where(Files.id == FileIconBackfillItems.owner_id),
                        ~available_file_reference,
                    ),
                    sa.and_(
                        FileIconBackfillItems.owner_kind == "icon",
                        sa.exists().where(Icons.id == FileIconBackfillItems.owner_id),
                        ~available_icon_reference,
                    ),
                ),
            )
        )
        return int(required_bytes or 0)

    async def _has_actionable_items(self) -> bool:
        return bool(
            await self._session.scalar(
                sa.select(
                    sa.exists().where(
                        FileIconBackfillItems.state.in_(("pending", "leased"))
                    )
                )
            )
        )

    async def _leased_item(self, item: _WorkItem) -> FileIconBackfillItems:
        row = await self._session.scalar(
            sa.select(FileIconBackfillItems)
            .where(FileIconBackfillItems.id == item.id)
            .with_for_update()
        )
        if row is None or row.state != "leased" or row.lease_owner != item.lease_owner:
            raise _LeaseLost
        return row

    async def _lock_owner(self, item: _WorkItem) -> bool:
        owner = Files if item.owner_kind == "file" else Icons
        owner_id = await self._session.scalar(
            sa.select(owner.id).where(owner.id == item.owner_id).with_for_update()
        )
        return owner_id is not None

    async def _existing_reference(
        self,
        item: _WorkItem,
        *,
        lock: bool = False,
    ) -> _ExistingReference | None:
        if item.owner_kind == "file":
            statement = (
                sa.select(
                    FileContentReferences.content_id,
                    ObjectContents.state,
                    FileContentReferences.page_number,
                    FileContentReferences.width,
                    FileContentReferences.height,
                    FileContentReferences.duration_ms,
                )
                .join(
                    ObjectContents,
                    ObjectContents.id == FileContentReferences.content_id,
                )
                .where(
                    FileContentReferences.file_id == item.owner_id,
                    FileContentReferences.variant == item.variant,
                    FileContentReferences.ordinal == item.ordinal,
                )
            )
            if lock:
                statement = statement.with_for_update()
        else:
            statement = (
                sa.select(IconContentReferences.content_id, ObjectContents.state)
                .join(
                    ObjectContents,
                    ObjectContents.id == IconContentReferences.content_id,
                )
                .where(
                    IconContentReferences.icon_id == item.owner_id,
                    IconContentReferences.variant == "primary",
                )
            )
            if lock:
                statement = statement.with_for_update()
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None
        return _ExistingReference(
            content_id=row.content_id,
            state=ContentState(row.state),
            page_number=row.page_number if item.owner_kind == "file" else None,
            width=row.width if item.owner_kind == "file" else None,
            height=row.height if item.owner_kind == "file" else None,
            duration_ms=row.duration_ms if item.owner_kind == "file" else None,
        )

    async def _delete_reference(self, item: _WorkItem, *, content_id: UUID) -> None:
        if item.owner_kind == "file":
            statement = sa.delete(FileContentReferences).where(
                FileContentReferences.file_id == item.owner_id,
                FileContentReferences.variant == item.variant,
                FileContentReferences.ordinal == item.ordinal,
                FileContentReferences.content_id == content_id,
            )
        else:
            statement = sa.delete(IconContentReferences).where(
                IconContentReferences.icon_id == item.owner_id,
                IconContentReferences.variant == "primary",
                IconContentReferences.content_id == content_id,
            )
        deleted = await self._session.execute(statement)
        if affected_row_count(deleted) != 1:
            raise ObjectContentStateError(
                "Existing File/Icon content reference changed during legacy adoption"
            )

    @staticmethod
    def _clear_lease(item: FileIconBackfillItems) -> None:
        item.lease_owner = None
        item.lease_expires_at = None
        item.updated_at = datetime.now(UTC)

    @classmethod
    def _cancel(cls, item: FileIconBackfillItems) -> None:
        item.state = "cancelled"
        item.content_id = None
        item.last_error_code = None
        item.last_error_detail = None
        item.failure_revision = None
        cls._clear_lease(item)

    async def _database_now(self) -> datetime:
        return (
            await self._session.execute(sa.select(sa.func.clock_timestamp()))
        ).scalar_one()

    async def _analyze_targets(self) -> None:
        await self._session.execute(
            sa.text(
                "ANALYZE object_contents, inline_content_payloads, "
                "file_content_references, icon_content_references"
            )
        )


class FileIconBackfill:
    """Converge one bounded legacy File/Icon adoption batch."""

    def __init__(
        self,
        settings: FileIconBackfillSettings,
        object_content: ObjectContentService,
        database: DatabaseSessionManager = sessionmanager,
    ) -> None:
        self._settings = settings
        self._object_content = object_content
        self._database = database
        self._completed_result: FileIconBackfillResult | None = None
        self._waiting_capacity_result: FileIconBackfillResult | None = None

    async def run_once(self) -> FileIconBackfillResult:
        if self._completed_result is not None:
            return self._completed_result
        if self._waiting_capacity_result is not None:
            async with self._database.session() as session, session.begin():
                repository = _FileIconBackfillRepository(session)
                campaign_exists = await repository.has_campaign()
                policy_target = (
                    None if campaign_exists else await repository.policy_target()
                )
            if not campaign_exists and policy_target is StorageKind.POSTGRES_INLINE:
                return self._waiting_capacity_result
            self._waiting_capacity_result = None

        result: FileIconBackfillResult | None = None
        async with self._database.connect() as guard:
            acquired = await guard.scalar(
                sa.text(
                    "SELECT pg_try_advisory_xact_lock(:lock_class, :lock_id)"
                ).bindparams(
                    lock_class=_ADVISORY_LOCK_CLASS,
                    lock_id=_ADVISORY_LOCK_ID,
                )
            )
            if acquired:
                result = await self._run_once()

        if result is None:
            return await self._contended_result()

        if result.state is FileIconBackfillState.COMPLETE:
            self._completed_result = result
        elif result.state is FileIconBackfillState.WAITING_FOR_CAPACITY:
            self._waiting_capacity_result = result
        return result

    async def _run_once(self) -> FileIconBackfillResult:
        async with self._database.session() as session, session.begin():
            repository = _FileIconBackfillRepository(session)
            campaign = await repository.campaign_or_start(self._settings)
            if campaign.state is not FileIconBackfillState.ACTIVE:
                return self._result(campaign)
            if campaign.target_kind is not StorageKind.POSTGRES_INLINE:
                raise ObjectContentStateError(
                    "The inline File/Icon backfill cannot process another target"
                )
            work = await repository.claim(self._settings)

        completed_count = 0
        cancelled_count = 0
        failed_count = 0
        for item in work:
            try:
                async with self._database.session() as session, session.begin():
                    attempts = await _FileIconBackfillRepository(session).begin_attempt(
                        item
                    )
            except _LeaseLost:
                continue
            if attempts > self._settings.max_attempts:
                recorded = await self._record_failure(
                    item,
                    code="retry_exhausted",
                    detail=(
                        f"Exceeded {self._settings.max_attempts} processing "
                        "attempt(s) after repeated worker failures"
                    ),
                )
                failed_count += int(recorded)
                continue
            try:
                async with self._database.session() as session, session.begin():
                    source = await _FileIconBackfillRepository(
                        session
                    ).source_or_complete(item)
                if source is None:
                    completed_count += 1
                    continue
                if source.payload is None:
                    raise _LegacySourceMissing
                payload = source.payload
                media_type = source.media_type
                created_by_user_id = source.created_by_user_id
                source_stream = _one_chunk(payload)
                async with self._object_content.capture_for_target(
                    source_stream,
                    storage_kind=StorageKind.POSTGRES_INLINE,
                    declared_media_type=media_type,
                    verified_media_type=media_type,
                ) as captured:
                    async with self._database.session() as session, session.begin():
                        completed = await _FileIconBackfillRepository(
                            session
                        ).complete_inline(
                            item,
                            created_by_user_id,
                            captured,
                            self._object_content,
                        )
                    if completed:
                        completed_count += 1
                    else:
                        cancelled_count += 1
            except _OwnerDeleted:
                try:
                    async with self._database.session() as session, session.begin():
                        await _FileIconBackfillRepository(session).cancel(item)
                except _LeaseLost:
                    continue
                else:
                    cancelled_count += 1
            except _LeaseLost:
                continue
            except ContentTooLargeError as error:
                recorded = await self._record_failure(
                    item,
                    code="inline_payload_too_large",
                    detail=str(error),
                )
                failed_count += int(recorded)
            except (
                _LegacySourceMissing,
                ObjectContentIdempotencyConflictError,
                ObjectContentIntegrityError,
                ObjectContentStateError,
            ) as error:
                recorded = await self._record_failure(
                    item,
                    code="legacy_source_invalid",
                    detail=str(error) or "The frozen legacy payload is missing",
                )
                failed_count += int(recorded)

        async with self._database.session() as session, session.begin():
            repository = _FileIconBackfillRepository(session)
            campaign = await repository.finish_campaign()
        return self._result(
            campaign,
            claimed_count=len(work),
            completed_count=completed_count,
            cancelled_count=cancelled_count,
            failed_count=failed_count,
        )

    async def _contended_result(self) -> FileIconBackfillResult:
        async with self._database.session() as session, session.begin():
            campaign_row = (
                await session.execute(
                    sa.select(
                        FileIconBackfillCampaign.state,
                        FileIconBackfillCampaign.target_kind,
                        FileIconBackfillCampaign.halt_reason,
                    )
                )
            ).one_or_none()
        campaign = (
            _Campaign(
                state=FileIconBackfillState.ACTIVE,
                target_kind=None,
                detail="Another worker owns the current backfill run",
            )
            if campaign_row is None
            else _Campaign(
                state=FileIconBackfillState(campaign_row.state),
                target_kind=StorageKind(campaign_row.target_kind),
                detail=(
                    campaign_row.halt_reason
                    if campaign_row.state != FileIconBackfillState.ACTIVE.value
                    else "Another worker owns the current backfill run"
                ),
            )
        )
        return self._result(campaign)

    async def _record_failure(
        self,
        item: _WorkItem,
        *,
        code: str,
        detail: str,
    ) -> bool:
        try:
            async with self._database.session() as session, session.begin():
                await _FileIconBackfillRepository(session).fail(
                    item,
                    code=code,
                    detail=detail,
                )
        except _LeaseLost:
            return False
        return True

    @staticmethod
    def _result(
        campaign: _Campaign,
        *,
        claimed_count: int = 0,
        completed_count: int = 0,
        cancelled_count: int = 0,
        failed_count: int = 0,
    ) -> FileIconBackfillResult:
        return FileIconBackfillResult(
            state=campaign.state,
            target_kind=campaign.target_kind,
            claimed_count=claimed_count,
            completed_count=completed_count,
            cancelled_count=cancelled_count,
            failed_count=failed_count,
            detail=campaign.detail,
        )
