from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from secrets import token_hex
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Select
from sqlalchemy.dialects.postgresql import BYTEA, insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from eneo.database.affected_rows import affected_row_count
from eneo.database.database import DatabaseSessionManager, sessionmanager
from eneo.database.tables.file_icon_backfill_table import (
    FileIconBackfillAdmissionState,
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
    ContentAccessClass,
    ContentFacts,
    ContentIntent,
    ContentState,
    ContentTooLargeError,
    ObjectContentIdempotencyConflictError,
    ObjectContentStateError,
    StorageKind,
)
from eneo.object_content.content_service import ObjectContentService

_MEBIBYTE = 1024 * 1024
_GIBIBYTE = 1024 * _MEBIBYTE
_ADVISORY_LOCK_CLASS = 1_162_757_455  # ASCII "ENEO"
_ADVISORY_LOCK_ID = 1_179_206_214  # ASCII "FIBF"
_LOCK_NOT_AVAILABLE_SQLSTATE = "55P03"


def _is_lock_not_available(error: DBAPIError) -> bool:
    original = error.orig
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return sqlstate == _LOCK_NOT_AVAILABLE_SQLSTATE or (
        _LOCK_NOT_AVAILABLE_SQLSTATE in str(original)
    )


class FileIconBackfillSettings(BaseSettings):
    """Fixed worker bounds and the explicit one-time inline capacity grant."""

    model_config = SettingsConfigDict(
        env_prefix="FILE_ICON_BACKFILL_",
        env_file=None,
        extra="forbid",
    )

    auto_inline_max_bytes: int = Field(default=5 * _GIBIBYTE, ge=0)
    inline_capacity_ack: int = Field(default=0, ge=0)
    batch_rows: int = Field(default=200, ge=1, le=1000)
    batch_bytes: int = Field(default=128 * _MEBIBYTE, ge=1)
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
    admitted_count: int
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
    admission_generation: int | None = None


@dataclass(frozen=True, slots=True)
class _Admission:
    terminal: bool
    inspected_count: int
    completed_count: int
    cancelled_count: int


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
    content: ContentFacts
    created_by_user_id: UUID | None
    payload_select: Select[tuple[bytes]]


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


class _AdmissionContended(Exception):
    pass


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
                    additional_bytes = await self._unadmitted_resume_bytes(
                        campaign,
                        settings.resume_revision,
                    )
                    required_bytes = campaign.capacity_admitted_bytes + additional_bytes
                    if additional_bytes > 0 and not self._capacity_granted(
                        settings,
                        required_bytes,
                    ):
                        campaign.halt_reason = self._capacity_detail(required_bytes)
                    else:
                        campaign.state = FileIconBackfillState.ACTIVE.value
                        campaign.halt_reason = None
                        campaign.resume_revision = settings.resume_revision
                        campaign.resume_cursor_id = 0
                        campaign.capacity_admitted_bytes = required_bytes
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

        if not await self.has_source_items():
            return await self._insert_campaign(
                state=FileIconBackfillState.COMPLETE,
                resume_revision=settings.resume_revision,
                capacity_admitted_bytes=0,
            )

        policy_target = await self.policy_target()
        if policy_target is StorageKind.OBJECT_STORE:
            return _Campaign(
                state=FileIconBackfillState.WAITING_FOR_OBJECT_STORE,
                target_kind=StorageKind.OBJECT_STORE,
                detail="The object-store backfill adapter is not active in this release",
            )

        admission_generation = await self.admission_generation()
        required_bytes = await self.capacity_required_bytes()
        capacity_granted = self._capacity_granted(settings, required_bytes)
        if not capacity_granted:
            return _Campaign(
                state=FileIconBackfillState.WAITING_FOR_CAPACITY,
                target_kind=StorageKind.POSTGRES_INLINE,
                detail=self._capacity_detail(required_bytes),
                admission_generation=admission_generation,
            )
        return await self._insert_campaign(
            state=FileIconBackfillState.ACTIVE,
            resume_revision=settings.resume_revision,
            capacity_admitted_bytes=required_bytes,
        )

    async def _insert_campaign(
        self,
        *,
        state: FileIconBackfillState,
        resume_revision: int,
        capacity_admitted_bytes: int,
    ) -> _Campaign:
        statement = (
            insert(FileIconBackfillCampaign)
            .values(
                id=uuid4(),
                target_kind=StorageKind.POSTGRES_INLINE.value,
                destination_revision=None,
                state=state.value,
                resume_revision=resume_revision,
                capacity_admitted_bytes=capacity_admitted_bytes,
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

    @staticmethod
    def _capacity_granted(
        settings: FileIconBackfillSettings,
        required_bytes: int,
    ) -> bool:
        return (
            required_bytes <= settings.auto_inline_max_bytes
            or settings.inline_capacity_ack >= required_bytes
        )

    @staticmethod
    def _capacity_detail(required_bytes: int) -> str:
        return (
            "The upgrade is complete and existing File/Icon content remains "
            "readable, but legacy adoption is waiting for an inline capacity "
            f"decision. The backfill estimates {required_bytes} bytes; set "
            "FILE_ICON_BACKFILL_INLINE_CAPACITY_ACK to at least that value "
            "after reserving payload, WAL, and safety headroom"
        )

    async def _unadmitted_resume_bytes(
        self,
        campaign: FileIconBackfillCampaign,
        requested_resume_revision: int,
    ) -> int:
        additional_bytes = await self._session.scalar(
            sa.select(
                sa.func.coalesce(
                    sa.func.sum(FileIconBackfillItems.payload_size_estimate),
                    0,
                )
            ).where(
                FileIconBackfillItems.state == "failed",
                FileIconBackfillItems.capacity_admitted.is_(False),
                FileIconBackfillItems.failure_revision >= campaign.resume_revision,
                FileIconBackfillItems.failure_revision < requested_resume_revision,
            )
        )
        return int(additional_bytes or 0)

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

    async def has_source_items(self) -> bool:
        return bool(
            await self._session.scalar(
                sa.select(
                    sa.exists().where(
                        FileIconBackfillItems.state.in_(("pending", "ready", "leased"))
                    )
                )
            )
        )

    async def admit(self, settings: FileIconBackfillSettings) -> _Admission:
        candidates = (
            await self._session.scalars(
                sa.select(FileIconBackfillItems)
                .where(
                    FileIconBackfillItems.state == "pending",
                    FileIconBackfillItems.lease_expires_at.is_(None),
                )
                .order_by(
                    FileIconBackfillItems.lease_expires_at,
                    FileIconBackfillItems.id,
                )
                .limit(settings.batch_rows + 1)
            )
        ).all()
        candidate_batch = candidates[: settings.batch_rows]
        if not candidate_batch:
            return _Admission(
                terminal=True,
                inspected_count=0,
                completed_count=0,
                cancelled_count=0,
            )
        try:
            owners = await self._lock_admission_owners(candidate_batch)
            references = await self._lock_admission_references(candidate_batch)
        except DBAPIError as error:
            if not _is_lock_not_available(error):
                raise
            raise _AdmissionContended from error
        batch = (
            await self._session.scalars(
                sa.select(FileIconBackfillItems)
                .where(
                    FileIconBackfillItems.id.in_(
                        [candidate.id for candidate in candidate_batch]
                    ),
                    FileIconBackfillItems.state == "pending",
                )
                .order_by(FileIconBackfillItems.id)
                .with_for_update()
            )
        ).all()
        completed_count = 0
        cancelled_count = 0
        now = await self._database_now()
        for row in batch:
            item = self._work_item(row, lease_owner="")
            if (item.owner_kind, item.owner_id) not in owners:
                self._cancel(row)
                cancelled_count += 1
                continue
            existing = references.get(
                (item.owner_kind, item.owner_id, item.variant, item.ordinal)
            )
            if existing is not None and existing.state is ContentState.AVAILABLE:
                row.state = "done"
                row.content_id = existing.content_id
                row.failure_revision = None
                self._clear_lease(row)
                completed_count += 1
                continue
            row.state = "ready"
            row.updated_at = now
        await self._session.flush()
        return _Admission(
            terminal=len(candidates) <= settings.batch_rows,
            inspected_count=len(batch),
            completed_count=completed_count,
            cancelled_count=cancelled_count,
        )

    async def _lock_admission_owners(
        self,
        items: Sequence[FileIconBackfillItems],
    ) -> set[tuple[str, UUID]]:
        file_ids = {item.owner_id for item in items if item.owner_kind == "file"}
        icon_ids = {item.owner_id for item in items if item.owner_kind == "icon"}
        owners: set[tuple[str, UUID]] = set()
        if file_ids:
            locked_file_ids = await self._session.scalars(
                sa.select(Files.id)
                .where(Files.id.in_(file_ids))
                .order_by(Files.id)
                .with_for_update(nowait=True)
            )
            owners.update(("file", owner_id) for owner_id in locked_file_ids)
        if icon_ids:
            locked_icon_ids = await self._session.scalars(
                sa.select(Icons.id)
                .where(Icons.id.in_(icon_ids))
                .order_by(Icons.id)
                .with_for_update(nowait=True)
            )
            owners.update(("icon", owner_id) for owner_id in locked_icon_ids)
        return owners

    async def _lock_admission_references(
        self,
        items: Sequence[FileIconBackfillItems],
    ) -> dict[tuple[str, UUID, str, int], _ExistingReference]:
        references: dict[tuple[str, UUID, str, int], _ExistingReference] = {}
        file_keys = [
            (item.owner_id, item.variant, item.ordinal)
            for item in items
            if item.owner_kind == "file"
        ]
        if file_keys:
            rows = await self._session.execute(
                sa.select(
                    FileContentReferences.file_id,
                    FileContentReferences.variant,
                    FileContentReferences.ordinal,
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
                    sa.tuple_(
                        FileContentReferences.file_id,
                        FileContentReferences.variant,
                        FileContentReferences.ordinal,
                    ).in_(file_keys)
                )
                .order_by(
                    FileContentReferences.file_id,
                    FileContentReferences.variant,
                    FileContentReferences.ordinal,
                )
                .with_for_update(nowait=True)
            )
            for row in rows:
                references[("file", row.file_id, row.variant, row.ordinal)] = (
                    _ExistingReference(
                        content_id=row.content_id,
                        state=ContentState(row.state),
                        page_number=row.page_number,
                        width=row.width,
                        height=row.height,
                        duration_ms=row.duration_ms,
                    )
                )
        icon_ids = {item.owner_id for item in items if item.owner_kind == "icon"}
        if icon_ids:
            rows = await self._session.execute(
                sa.select(
                    IconContentReferences.icon_id,
                    IconContentReferences.content_id,
                    ObjectContents.state,
                )
                .join(
                    ObjectContents,
                    ObjectContents.id == IconContentReferences.content_id,
                )
                .where(
                    IconContentReferences.icon_id.in_(icon_ids),
                    IconContentReferences.variant == "primary",
                )
                .order_by(IconContentReferences.icon_id)
                .with_for_update(nowait=True)
            )
            for row in rows:
                references[("icon", row.icon_id, "primary", 0)] = _ExistingReference(
                    content_id=row.content_id,
                    state=ContentState(row.state),
                )
        return references

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
                        FileIconBackfillItems.state == "ready",
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
            item.capacity_admitted = True
            item.lease_owner = lease_owner
            item.lease_expires_at = lease_expires_at
            item.last_error_code = None
            item.last_error_detail = None
            item.updated_at = now
            work.append(self._work_item(item, lease_owner=lease_owner))
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
            item.state = "ready"
            item.capacity_admitted = True
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

    @staticmethod
    def _legacy_payload_expressions(
        item: _WorkItem,
    ) -> tuple[ColumnElement[bytes], ColumnElement[int], str | None, bool]:
        if item.owner_kind == "file":
            if item.variant == "transcription":
                size_expression = sa.func.octet_length(Files.legacy_transcription)
                payload_expression = sa.func.convert_to(
                    Files.legacy_transcription,
                    "UTF8",
                )
                media_type = "text/plain"
            elif item.variant == "original":
                payload_expression = Files.legacy_blob
                size_expression = sa.func.octet_length(payload_expression)
                media_type = None
            elif item.variant == "extracted_text":
                size_expression = sa.func.octet_length(Files.legacy_text)
                payload_expression = sa.func.convert_to(Files.legacy_text, "UTF8")
                media_type = "text/plain"
            elif item.variant in {"derived_page", "legacy_image"}:
                payload_expression = Files.legacy_blob
                size_expression = sa.func.octet_length(payload_expression)
                media_type = None
            else:
                raise _LegacySourceMissing
            return (
                sa.type_coerce(payload_expression, BYTEA),
                size_expression,
                media_type,
                item.variant in {"transcription", "extracted_text"},
            )
        if item.owner_kind == "icon" and item.variant == "primary":
            return (
                sa.type_coerce(Icons.legacy_blob, BYTEA),
                sa.func.octet_length(Icons.legacy_blob),
                None,
                False,
            )
        raise _LegacySourceMissing

    async def legacy_source_size(self, item: _WorkItem) -> int:
        _, size_expression, _, requires_utf8 = self._legacy_payload_expressions(item)
        if item.owner_kind == "file":
            row = (
                await self._session.execute(
                    sa.select(
                        Files.tenant_id,
                        size_expression.label("size_bytes"),
                        sa.func.getdatabaseencoding().label("database_encoding"),
                    ).where(Files.id == item.owner_id)
                )
            ).one_or_none()
            if row is None:
                raise _OwnerDeleted
        else:
            row = (
                await self._session.execute(
                    sa.select(
                        Icons.tenant_id,
                        size_expression.label("size_bytes"),
                        sa.func.getdatabaseencoding().label("database_encoding"),
                    ).where(Icons.id == item.owner_id)
                )
            ).one_or_none()
            if row is None:
                raise _OwnerDeleted
        if row.tenant_id != item.tenant_id or row.size_bytes is None:
            raise _LegacySourceMissing
        if requires_utf8 and row.database_encoding != "UTF8":
            raise ObjectContentStateError(
                "File/Icon text adoption requires UTF8 PostgreSQL encoding"
            )
        return int(row.size_bytes)

    async def legacy_source(self, item: _WorkItem) -> _LegacySource:
        payload_expression, _, fixed_media_type, _ = self._legacy_payload_expressions(
            item
        )
        if item.owner_kind == "file":
            row = (
                await self._session.execute(
                    sa.select(
                        Files.user_id,
                        Files.tenant_id,
                        Files.mimetype,
                        sa.func.sha256(payload_expression).label("sha256"),
                        sa.func.octet_length(payload_expression).label("size_bytes"),
                    ).where(Files.id == item.owner_id)
                )
            ).one_or_none()
            if row is None:
                raise _OwnerDeleted
            if (
                row.tenant_id != item.tenant_id
                or row.sha256 is None
                or row.size_bytes is None
            ):
                raise _LegacySourceMissing
            resolved_media_type = (
                fixed_media_type or row.mimetype or "application/octet-stream"
            )
            content = ContentFacts(
                sha256=bytes(row.sha256),
                size_bytes=int(row.size_bytes),
                declared_media_type=resolved_media_type,
                verified_media_type=resolved_media_type,
            )
            payload_select = sa.select(payload_expression.label("payload")).where(
                Files.id == item.owner_id,
                Files.tenant_id == item.tenant_id,
            )
            return _LegacySource(
                content=content,
                created_by_user_id=row.user_id,
                payload_select=payload_select,
            )

        if item.owner_kind == "icon":
            row = (
                await self._session.execute(
                    sa.select(
                        Icons.tenant_id,
                        Icons.legacy_mimetype,
                        sa.func.sha256(payload_expression).label("sha256"),
                        sa.func.octet_length(payload_expression).label("size_bytes"),
                    ).where(Icons.id == item.owner_id)
                )
            ).one_or_none()
            if row is None:
                raise _OwnerDeleted
            if (
                row.tenant_id != item.tenant_id
                or row.sha256 is None
                or row.size_bytes is None
            ):
                raise _LegacySourceMissing
            media_type = row.legacy_mimetype or "application/octet-stream"
            content = ContentFacts(
                sha256=bytes(row.sha256),
                size_bytes=int(row.size_bytes),
                declared_media_type=media_type,
                verified_media_type=media_type,
            )
            payload_select = sa.select(payload_expression.label("payload")).where(
                Icons.id == item.owner_id,
                Icons.tenant_id == item.tenant_id,
            )
            return _LegacySource(
                content=content,
                created_by_user_id=None,
                payload_select=payload_select,
            )
        raise _LegacySourceMissing

    async def complete_inline(
        self,
        item: _WorkItem,
        object_content: ObjectContentService,
    ) -> bool:
        if not await self._lock_owner(item):
            ledger = await self._leased_item(item)
            self._cancel(ledger)
            await self._session.flush()
            return False
        ledger = await self._leased_item(item)

        existing = await self._existing_reference(item, lock=True)
        if existing is not None and existing.state is ContentState.AVAILABLE:
            ledger.state = "done"
            ledger.content_id = existing.content_id
            ledger.failure_revision = None
            self._clear_lease(ledger)
            await self._session.flush()
            return True

        source_size = await self.legacy_source_size(item)
        object_content.ensure_inline_size(source_size)
        source = await self.legacy_source(item)
        ledger.payload_size_estimate = source.content.size_bytes
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
        prepared = await object_content.prepare_inline_from_select_in_transaction(
            self._session,
            intent=ContentIntent(
                tenant_id=item.tenant_id,
                created_by_user_id=source.created_by_user_id,
                access_class=(
                    ContentAccessClass.PRIVATE_RESOURCE
                    if item.owner_kind == "file"
                    else ContentAccessClass.PUBLIC_IMMUTABLE
                ),
                idempotency_key=intent_key,
                producer_receipt=intent_key,
            ),
            content=source.content,
            payload_select=source.payload_select,
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
        required_bytes = await self._session.scalar(
            sa.select(
                sa.func.coalesce(
                    sa.func.sum(FileIconBackfillItems.payload_size_estimate),
                    0,
                )
            ).where(FileIconBackfillItems.state == "ready")
        )
        return int(required_bytes or 0)

    async def admission_generation(self) -> int:
        generation = await self._session.scalar(
            sa.select(FileIconBackfillAdmissionState.generation).where(
                FileIconBackfillAdmissionState.singleton.is_(True)
            )
        )
        return int(generation or 0)

    async def campaign_state(self) -> FileIconBackfillState | None:
        state = await self._session.scalar(sa.select(FileIconBackfillCampaign.state))
        return None if state is None else FileIconBackfillState(state)

    async def _has_actionable_items(self) -> bool:
        return bool(
            await self._session.scalar(
                sa.select(
                    sa.exists().where(
                        FileIconBackfillItems.state.in_(("ready", "leased"))
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

    @staticmethod
    def _work_item(
        item: FileIconBackfillItems,
        *,
        lease_owner: str,
    ) -> _WorkItem:
        return _WorkItem(
            id=item.id,
            owner_kind=item.owner_kind,
            owner_id=item.owner_id,
            variant=item.variant,
            ordinal=item.ordinal,
            tenant_id=item.tenant_id,
            payload_size_estimate=item.payload_size_estimate,
            lease_owner=lease_owner,
        )

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
        self._waiting_capacity_result: tuple[FileIconBackfillResult, int] | None = None

    async def run_once(self) -> FileIconBackfillResult:
        if self._completed_result is not None:
            async with self._database.session() as session, session.begin():
                state = await _FileIconBackfillRepository(session).campaign_state()
            if state is FileIconBackfillState.COMPLETE:
                return self._completed_result
            self._completed_result = None
        if self._waiting_capacity_result is not None:
            waiting_result, waiting_generation = self._waiting_capacity_result
            async with self._database.session() as session, session.begin():
                repository = _FileIconBackfillRepository(session)
                campaign_exists = await repository.has_campaign()
                policy_target = (
                    None if campaign_exists else await repository.policy_target()
                )
                admission_generation = (
                    None if campaign_exists else await repository.admission_generation()
                )
            if (
                not campaign_exists
                and policy_target is StorageKind.POSTGRES_INLINE
                and admission_generation == waiting_generation
            ):
                return waiting_result
            self._waiting_capacity_result = None

        result: FileIconBackfillResult | None = None
        admission_generation: int | None = None
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
                result, admission_generation = await self._run_once()

        if result is None:
            return await self._contended_result()

        if result.state is FileIconBackfillState.COMPLETE:
            self._completed_result = result
        elif result.state is FileIconBackfillState.WAITING_FOR_CAPACITY:
            if admission_generation is None:
                raise RuntimeError("Capacity wait lost its admission generation")
            self._waiting_capacity_result = (result, admission_generation)
        return result

    async def _run_once(self) -> tuple[FileIconBackfillResult, int | None]:
        admission = _Admission(
            terminal=True,
            inspected_count=0,
            completed_count=0,
            cancelled_count=0,
        )
        try:
            async with self._database.session() as session, session.begin():
                repository = _FileIconBackfillRepository(session)
                if not await repository.has_campaign():
                    admission = await repository.admit(self._settings)
                    if not admission.terminal:
                        return (
                            self._result(
                                _Campaign(
                                    state=FileIconBackfillState.ACTIVE,
                                    target_kind=None,
                                    detail=(
                                        "Finalizing File/Icon backfill admission before "
                                        "the destination capacity decision"
                                    ),
                                ),
                                admitted_count=admission.inspected_count,
                                completed_count=admission.completed_count,
                                cancelled_count=admission.cancelled_count,
                            ),
                            None,
                        )
                campaign = await repository.campaign_or_start(self._settings)
                if campaign.state is not FileIconBackfillState.ACTIVE:
                    return (
                        self._result(
                            campaign,
                            admitted_count=admission.inspected_count,
                            completed_count=admission.completed_count,
                            cancelled_count=admission.cancelled_count,
                        ),
                        campaign.admission_generation,
                    )
                if campaign.target_kind is not StorageKind.POSTGRES_INLINE:
                    raise ObjectContentStateError(
                        "The inline File/Icon backfill cannot process another target"
                    )
                work = await repository.claim(self._settings)
        except _AdmissionContended:
            return (
                self._result(
                    _Campaign(
                        state=FileIconBackfillState.ACTIVE,
                        target_kind=None,
                        detail=(
                            "A File/Icon owner or reference is changing; admission "
                            "will retry on the next worker run"
                        ),
                    )
                ),
                None,
            )

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
                    completed = await _FileIconBackfillRepository(
                        session
                    ).complete_inline(
                        item,
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
        return (
            self._result(
                campaign,
                admitted_count=admission.inspected_count,
                claimed_count=len(work),
                completed_count=completed_count + admission.completed_count,
                cancelled_count=cancelled_count + admission.cancelled_count,
                failed_count=failed_count,
            ),
            None,
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
        admitted_count: int = 0,
        claimed_count: int = 0,
        completed_count: int = 0,
        cancelled_count: int = 0,
        failed_count: int = 0,
    ) -> FileIconBackfillResult:
        return FileIconBackfillResult(
            state=campaign.state,
            target_kind=campaign.target_kind,
            admitted_count=admitted_count,
            claimed_count=claimed_count,
            completed_count=completed_count,
            cancelled_count=cancelled_count,
            failed_count=failed_count,
            detail=campaign.detail,
        )
