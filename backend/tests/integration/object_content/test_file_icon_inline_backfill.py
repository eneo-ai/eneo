from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    IconContentReferences,
    InlineContentPayloads,
    ObjectContents,
)
from eneo.database.tables.users_table import Users
from eneo.object_content import file_icon_backfill as file_icon_backfill_module
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content import (
    ContentAccessClass,
    ContentFacts,
    ContentFailureCode,
    ContentIntent,
    ContentReadGrant,
    ContentState,
    ObjectContentIntegrityError,
    ObjectContentStateError,
    StorageKind,
)
from eneo.object_content.content_repository import (
    ObjectContentRepository,
    PreparedContent,
)
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.file_icon_backfill import (
    FileIconBackfill,
    FileIconBackfillSettings,
    FileIconBackfillState,
)


async def _tenant_and_user(
    database: DatabaseSessionManager,
) -> tuple[UUID, UUID]:
    async with database.session() as session, session.begin():
        return (
            await session.execute(
                sa.select(Users.tenant_id, Users.id).where(
                    Users.email == "object-content@example.test"
                )
            )
        ).one()


async def _seed_legacy_text(
    database: DatabaseSessionManager,
    *,
    payload: bytes,
    estimate: int | None = None,
    file_id: UUID | None = None,
    parent_file_id: UUID | None = None,
) -> UUID:
    tenant_id, user_id = await _tenant_and_user(database)
    file_id = file_id or uuid4()
    async with database.session() as session, session.begin():
        await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
        await session.execute(
            sa.text(
                """
                INSERT INTO files (
                    id, name, text, blob, checksum, size, mimetype, file_type,
                    transcription, user_id, tenant_id, parent_file_id
                ) VALUES (
                    :file_id, 'legacy.txt', :text, NULL, :checksum, :size,
                    'text/plain', 'text', NULL, :user_id, :tenant_id,
                    :parent_file_id
                )
                """
            ),
            {
                "file_id": file_id,
                "text": payload.decode(),
                "checksum": sha256(payload).hexdigest(),
                "size": len(payload),
                "user_id": user_id,
                "tenant_id": tenant_id,
                "parent_file_id": parent_file_id,
            },
        )
        await session.execute(
            sa.text(
                """
                INSERT INTO file_icon_backfill_items (
                    owner_kind, owner_id, variant, ordinal, tenant_id,
                    payload_size_estimate
                ) VALUES (
                    'file', :file_id, 'extracted_text', 0, :tenant_id, :estimate
                )
                """
            ),
            {
                "file_id": file_id,
                "tenant_id": tenant_id,
                "estimate": len(payload) if estimate is None else estimate,
            },
        )
    return file_id


async def _attach_existing_inline_reference(
    database: DatabaseSessionManager,
    *,
    file_id: UUID,
    payload: bytes = b"already adopted",
    variant: str = "extracted_text",
    page_number: int | None = None,
    width: int | None = None,
    height: int | None = None,
    duration_ms: int | None = None,
) -> UUID:
    tenant_id, user_id = await _tenant_and_user(database)
    service = ObjectContentService(
        ObjectContentCoreSettings(
            inline_maximum_bytes=1024,
            inline_io_chunk_bytes=256,
        ),
        database,
    )

    async def source() -> AsyncIterator[bytes]:
        yield payload

    async with service.capture_for_target(
        source(),
        storage_kind=StorageKind.POSTGRES_INLINE,
        declared_media_type="text/plain",
        verified_media_type="text/plain",
    ) as captured:
        async with database.session() as session, session.begin():
            prepared = await service.prepare_in_transaction(
                session,
                intent=ContentIntent(
                    tenant_id=tenant_id,
                    created_by_user_id=user_id,
                    access_class=ContentAccessClass.PRIVATE_RESOURCE,
                    idempotency_key=f"existing:{file_id}:{variant}:0",
                    producer_receipt=f"existing:{file_id}:{variant}:0",
                ),
                content=captured,
                storage_kind=StorageKind.POSTGRES_INLINE,
            )
            session.add(
                FileContentReferences(
                    file_id=file_id,
                    content_id=prepared.id,
                    variant=variant,
                    ordinal=0,
                    page_number=page_number,
                    width=width,
                    height=height,
                    duration_ms=duration_ms,
                )
            )
        return prepared.id


async def _seed_legacy_icon(
    database: DatabaseSessionManager,
    *,
    payload: bytes,
) -> UUID:
    tenant_id, _ = await _tenant_and_user(database)
    icon_id = uuid4()
    async with database.session() as session, session.begin():
        await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
        await session.execute(
            sa.text(
                """
                INSERT INTO icons (id, blob, mimetype, size, tenant_id)
                VALUES (:icon_id, :payload, 'image/svg+xml', :size, :tenant_id)
                """
            ),
            {
                "icon_id": icon_id,
                "payload": payload,
                "size": len(payload),
                "tenant_id": tenant_id,
            },
        )
        await session.execute(
            sa.text(
                """
                INSERT INTO file_icon_backfill_items (
                    owner_kind, owner_id, variant, ordinal, tenant_id,
                    payload_size_estimate
                ) VALUES (
                    'icon', :icon_id, 'primary', 0, :tenant_id, :size
                )
                """
            ),
            {
                "icon_id": icon_id,
                "tenant_id": tenant_id,
                "size": len(payload),
            },
        )
    return icon_id


async def _attach_existing_inline_icon_reference(
    database: DatabaseSessionManager,
    *,
    icon_id: UUID,
    payload: bytes,
) -> UUID:
    tenant_id, _ = await _tenant_and_user(database)
    service = ObjectContentService(
        ObjectContentCoreSettings(
            inline_maximum_bytes=1024,
            inline_io_chunk_bytes=256,
        ),
        database,
    )

    async def source() -> AsyncIterator[bytes]:
        yield payload

    async with service.capture_for_target(
        source(),
        storage_kind=StorageKind.POSTGRES_INLINE,
        declared_media_type="image/svg+xml",
        verified_media_type="image/svg+xml",
    ) as captured:
        async with database.session() as session, session.begin():
            prepared = await service.prepare_in_transaction(
                session,
                intent=ContentIntent(
                    tenant_id=tenant_id,
                    created_by_user_id=None,
                    access_class=ContentAccessClass.PUBLIC_IMMUTABLE,
                    idempotency_key=f"existing:{icon_id}:primary",
                    producer_receipt=f"existing:{icon_id}:primary",
                ),
                content=captured,
                storage_kind=StorageKind.POSTGRES_INLINE,
            )
            session.add(
                IconContentReferences(
                    icon_id=icon_id,
                    content_id=prepared.id,
                    variant="primary",
                )
            )
        return prepared.id


async def _seed_legacy_variants(
    database: DatabaseSessionManager,
) -> tuple[UUID, UUID, UUID]:
    tenant_id, user_id = await _tenant_and_user(database)
    text_id, image_id, icon_id = uuid4(), uuid4(), uuid4()
    async with database.session() as session, session.begin():
        await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
        await session.execute(
            sa.text(
                """
                INSERT INTO files (
                    id, name, text, blob, checksum, size, mimetype, file_type,
                    transcription, user_id, tenant_id, parent_file_id
                ) VALUES (
                    :text_id, 'legacy.pdf', 'extract', :original, 'frozen', 7,
                    'application/pdf', 'text', 'spoken', :user_id, :tenant_id,
                    NULL
                ), (
                    :image_id, 'legacy.png', NULL, :image, 'frozen', 5,
                    'image/png', 'image', NULL, :user_id, :tenant_id, NULL
                )
                """
            ),
            {
                "text_id": text_id,
                "original": b"original",
                "image_id": image_id,
                "image": b"image",
                "user_id": user_id,
                "tenant_id": tenant_id,
            },
        )
        await session.execute(
            sa.text(
                """
                INSERT INTO icons (id, blob, mimetype, size, tenant_id)
                VALUES (:icon_id, :icon, 'image/svg+xml', 4, :tenant_id)
                """
            ),
            {"icon_id": icon_id, "icon": b"icon", "tenant_id": tenant_id},
        )
        await session.execute(
            sa.text(
                """
                INSERT INTO file_icon_backfill_items (
                    owner_kind, owner_id, variant, ordinal, tenant_id,
                    payload_size_estimate
                ) VALUES
                    ('file', :text_id, 'extracted_text', 0, :tenant_id, 7),
                    ('file', :text_id, 'original', 0, :tenant_id, 8),
                    ('file', :text_id, 'transcription', 0, :tenant_id, 6),
                    ('file', :image_id, 'legacy_image', 0, :tenant_id, 5),
                    ('icon', :icon_id, 'primary', 0, :tenant_id, 4)
                """
            ),
            {
                "text_id": text_id,
                "image_id": image_id,
                "icon_id": icon_id,
                "tenant_id": tenant_id,
            },
        )
    return text_id, image_id, icon_id


async def _set_policy_target(
    database: DatabaseSessionManager,
    target: str,
) -> None:
    async with database.session() as session, session.begin():
        await session.execute(
            sa.text(
                """
                UPDATE object_content_deployment_policy
                SET new_write_storage_target = :target,
                    revision = revision + 1,
                    updated_by_actor = 'migration',
                    updated_by_user_id = NULL
                WHERE id = 1
                """
            ),
            {"target": target},
        )


def _backfill(
    database: DatabaseSessionManager,
    *,
    auto_inline_max_bytes: int = 1024,
    inline_capacity_ack: int = 0,
    batch_rows: int = 10,
    batch_bytes: int = 1024,
    inline_maximum_bytes: int = 1024,
    resume_revision: int = 0,
    max_attempts: int = 3,
) -> FileIconBackfill:
    return FileIconBackfill(
        FileIconBackfillSettings(
            auto_inline_max_bytes=auto_inline_max_bytes,
            inline_capacity_ack=inline_capacity_ack,
            batch_rows=batch_rows,
            batch_bytes=batch_bytes,
            resume_revision=resume_revision,
            max_attempts=max_attempts,
        ),
        ObjectContentService(
            ObjectContentCoreSettings(
                inline_maximum_bytes=inline_maximum_bytes,
                inline_io_chunk_bytes=min(256, inline_maximum_bytes),
            ),
            database,
        ),
        database,
    )


@pytest.mark.asyncio
async def test_inline_backfill_adopts_one_legacy_variant_atomically(
    object_content_database: DatabaseSessionManager,
) -> None:
    payload = b"legacy policy text"
    file_id = await _seed_legacy_text(object_content_database, payload=payload)
    backfill = _backfill(object_content_database)

    result = await backfill.run_once()

    assert result.state is FileIconBackfillState.COMPLETE
    assert result.claimed_count == 1
    assert result.completed_count == 1

    async with object_content_database.session() as session, session.begin():
        row = (
            await session.execute(
                sa.text(
                    """
                    SELECT
                        item.state AS item_state,
                        item.attempts,
                        item.lease_owner,
                        item.lease_expires_at,
                        item.content_id,
                        content.storage_kind,
                        content.state AS content_state,
                        content.sha256,
                        content.size_bytes,
                        content.verified_media_type,
                        content.reference_count,
                        inline.payload,
                        reference.variant,
                        file.text
                    FROM file_icon_backfill_items AS item
                    JOIN object_contents AS content ON content.id = item.content_id
                    JOIN inline_content_payloads AS inline
                      ON inline.content_id = content.id
                    JOIN file_content_references AS reference
                      ON reference.content_id = content.id
                    JOIN files AS file ON file.id = item.owner_id
                    WHERE item.owner_kind = 'file'
                      AND item.owner_id = :file_id
                      AND item.variant = 'extracted_text'
                    """
                ),
                {"file_id": file_id},
            )
        ).one()
        campaign = (
            await session.execute(
                sa.text(
                    """
                    SELECT target_kind, destination_revision, state, halt_reason
                    FROM file_icon_backfill_campaign
                    """
                )
            )
        ).one()

    assert row.item_state == "done"
    assert row.attempts == 1
    assert row.lease_owner is None
    assert row.lease_expires_at is None
    assert row.storage_kind == "postgres_inline"
    assert row.content_state == "available"
    assert row.sha256 == sha256(payload).digest()
    assert row.size_bytes == len(payload)
    assert row.verified_media_type == "text/plain"
    assert row.reference_count == 1
    assert row.payload == payload
    assert row.variant == "extracted_text"
    assert row.text == payload.decode()
    assert campaign == ("postgres_inline", None, "complete", None)


@pytest.mark.asyncio
async def test_inline_backfill_copies_unicode_text_without_python_capture(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = "åäö😀 kommuntext".encode()
    file_id = await _seed_legacy_text(object_content_database, payload=payload)
    backfill = _backfill(object_content_database)

    def unexpected_capture(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("PostgreSQL-inline adoption must not capture bytes")

    monkeypatch.setattr(
        ObjectContentService,
        "capture_for_target",
        unexpected_capture,
    )

    result = await backfill.run_once()

    assert result.state is FileIconBackfillState.COMPLETE
    async with object_content_database.session() as session, session.begin():
        row = (
            await session.execute(
                sa.text(
                    """
                    SELECT content.sha256, content.size_bytes, inline.payload
                    FROM file_icon_backfill_items AS item
                    JOIN object_contents AS content ON content.id = item.content_id
                    JOIN inline_content_payloads AS inline
                      ON inline.content_id = content.id
                    WHERE item.owner_id = :file_id
                    """
                ),
                {"file_id": file_id},
            )
        ).one()

    assert row.sha256 == sha256(payload).digest()
    assert row.size_bytes == len(payload)
    assert row.payload == payload


@pytest.mark.parametrize("payload", (b"", b"four"))
@pytest.mark.asyncio
async def test_inline_backfill_accepts_empty_and_exact_limit_text(
    object_content_database: DatabaseSessionManager,
    payload: bytes,
) -> None:
    file_id = await _seed_legacy_text(object_content_database, payload=payload)

    result = await _backfill(
        object_content_database,
        inline_maximum_bytes=4,
    ).run_once()

    assert result.state is FileIconBackfillState.COMPLETE
    async with object_content_database.session() as session, session.begin():
        row = (
            await session.execute(
                sa.text(
                    """
                    SELECT content.sha256, content.size_bytes, inline.payload
                    FROM file_icon_backfill_items AS item
                    JOIN object_contents AS content ON content.id = item.content_id
                    JOIN inline_content_payloads AS inline
                      ON inline.content_id = content.id
                    WHERE item.owner_id = :file_id
                    """
                ),
                {"file_id": file_id},
            )
        ).one()

    assert row.sha256 == sha256(payload).digest()
    assert row.size_bytes == len(payload)
    assert row.payload == payload


@pytest.mark.asyncio
async def test_inline_select_writer_rejects_payload_that_does_not_match_facts(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _tenant_and_user(object_content_database)
    expected = b"expected"
    service = ObjectContentService(
        ObjectContentCoreSettings(
            inline_maximum_bytes=1024,
            inline_io_chunk_bytes=256,
        ),
        object_content_database,
    )

    async with object_content_database.session() as session:
        transaction = await session.begin()
        try:
            with pytest.raises(
                ObjectContentStateError,
                match="Selected inline payload does not match content facts",
            ):
                await service.prepare_inline_from_select_in_transaction(
                    session,
                    intent=ContentIntent(
                        tenant_id=tenant_id,
                        created_by_user_id=user_id,
                        access_class=ContentAccessClass.PRIVATE_RESOURCE,
                        idempotency_key="test:mismatched-inline-select",
                        producer_receipt="test:mismatched-inline-select",
                    ),
                    content=ContentFacts(
                        sha256=sha256(expected).digest(),
                        size_bytes=len(expected),
                        declared_media_type="application/octet-stream",
                        verified_media_type="application/octet-stream",
                    ),
                    payload_select=sa.select(sa.literal(b"tampered").label("payload")),
                )
        finally:
            await transaction.rollback()

    async with object_content_database.session() as session, session.begin():
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(sa.table("object_contents"))
            )
            == 0
        )
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(
                    sa.table("inline_content_payloads")
                )
            )
            == 0
        )


@pytest.mark.asyncio
async def test_inline_backfill_rolls_back_if_frozen_bytes_change_before_copy(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"frozen source"
    file_id = await _seed_legacy_text(object_content_database, payload=payload)
    original_prepare = ObjectContentService.prepare_inline_from_select_in_transaction

    async def mutate_before_copy(
        service: ObjectContentService,
        session: AsyncSession,
        *,
        intent: ContentIntent,
        content: ContentFacts,
        payload_select: Select[tuple[bytes]],
    ) -> PreparedContent:
        await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
        await session.execute(
            sa.text("UPDATE files SET text = :text WHERE id = :file_id"),
            {"file_id": file_id, "text": "changed source"},
        )
        return await original_prepare(
            service,
            session,
            intent=intent,
            content=content,
            payload_select=payload_select,
        )

    monkeypatch.setattr(
        ObjectContentService,
        "prepare_inline_from_select_in_transaction",
        mutate_before_copy,
    )

    result = await _backfill(object_content_database).run_once()

    assert result.state is FileIconBackfillState.HALTED
    assert result.failed_count == 1
    async with object_content_database.session() as session, session.begin():
        row = (
            await session.execute(
                sa.text(
                    """
                    SELECT item.state, item.last_error_code,
                           item.last_error_detail, file.text
                    FROM file_icon_backfill_items AS item
                    JOIN files AS file ON file.id = item.owner_id
                    WHERE item.owner_id = :file_id
                    """
                ),
                {"file_id": file_id},
            )
        ).one()
        content_count = await session.scalar(
            sa.select(sa.func.count()).select_from(sa.table("object_contents"))
        )
        reference_count = await session.scalar(
            sa.select(sa.func.count()).select_from(sa.table("file_content_references"))
        )

    assert row.state == "failed"
    assert row.last_error_code == "legacy_source_invalid"
    assert "does not match content facts" in row.last_error_detail
    assert row.text == payload.decode()
    assert content_count == 0
    assert reference_count == 0


@pytest.mark.asyncio
async def test_large_inline_campaign_waits_for_capacity_acknowledgement(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_id = await _seed_legacy_text(
        object_content_database,
        payload=b"small physical payload",
        estimate=2048,
    )

    backfill = _backfill(
        object_content_database,
        auto_inline_max_bytes=1024,
    )
    waiting = await backfill.run_once()

    assert waiting.state is FileIconBackfillState.WAITING_FOR_CAPACITY
    assert waiting.claimed_count == 0
    assert waiting.detail is not None
    assert "upgrade is complete" in waiting.detail
    assert "content remains readable" in waiting.detail
    assert "FILE_ICON_BACKFILL_INLINE_CAPACITY_ACK" in waiting.detail

    async def reject_repeated_capacity_scan(*_args: object) -> object:
        raise AssertionError("waiting ticks must not rescan the complete ledger")

    with monkeypatch.context() as patch:
        patch.setattr(
            file_icon_backfill_module._FileIconBackfillRepository,
            "capacity_required_bytes",
            reject_repeated_capacity_scan,
        )
        repeated = await backfill.run_once()

    assert repeated == waiting
    async with object_content_database.session() as session, session.begin():
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(
                    sa.table("file_icon_backfill_campaign")
                )
            )
            == 0
        )

    completed = await _backfill(
        object_content_database,
        auto_inline_max_bytes=1024,
        inline_capacity_ack=2048,
    ).run_once()

    assert completed.state is FileIconBackfillState.COMPLETE
    assert completed.completed_count == 1

    async def reject_capacity_scan_after_campaign_start(*_args: object) -> object:
        raise AssertionError("persisted campaigns must bypass the capacity scan")

    with monkeypatch.context() as patch:
        patch.setattr(
            file_icon_backfill_module._FileIconBackfillRepository,
            "capacity_required_bytes",
            reject_capacity_scan_after_campaign_start,
        )
        observed_by_original_waiter = await backfill.run_once()

    assert observed_by_original_waiter.state is FileIconBackfillState.COMPLETE
    async with object_content_database.session() as session, session.begin():
        assert (
            await session.scalar(
                sa.text(
                    """
                SELECT count(*)
                FROM file_content_references
                WHERE file_id = :file_id AND variant = 'extracted_text'
                """
                ),
                {"file_id": file_id},
            )
            == 1
        )


@pytest.mark.asyncio
async def test_partial_owner_delete_rechecks_waiting_capacity_in_same_worker(
    object_content_database: DatabaseSessionManager,
) -> None:
    deleted_file_id = await _seed_legacy_text(
        object_content_database,
        payload=b"delete this source",
        estimate=800,
    )
    retained_file_id = await _seed_legacy_text(
        object_content_database,
        payload=b"retain this source",
        estimate=800,
    )
    backfill = _backfill(
        object_content_database,
        auto_inline_max_bytes=1024,
    )

    waiting = await backfill.run_once()

    assert waiting.state is FileIconBackfillState.WAITING_FOR_CAPACITY
    async with object_content_database.session() as session, session.begin():
        await session.execute(
            sa.text("DELETE FROM files WHERE id = :file_id"),
            {"file_id": deleted_file_id},
        )

    completed = await backfill.run_once()

    assert completed.state is FileIconBackfillState.COMPLETE
    assert completed.completed_count == 1
    async with object_content_database.session() as session, session.begin():
        states = dict(
            (
                await session.execute(
                    sa.text(
                        """
                    SELECT owner_id, state
                    FROM file_icon_backfill_items
                    WHERE owner_id IN (:deleted_file_id, :retained_file_id)
                    """
                    ),
                    {
                        "deleted_file_id": deleted_file_id,
                        "retained_file_id": retained_file_id,
                    },
                )
            ).all()
        )
    assert states == {
        deleted_file_id: "cancelled",
        retained_file_id: "done",
    }


@pytest.mark.asyncio
async def test_reference_failure_before_admission_requires_inline_capacity(
    object_content_database: DatabaseSessionManager,
) -> None:
    await _seed_legacy_text(
        object_content_database,
        payload=b"x",
        estimate=1,
    )
    referenced_file_id = await _seed_legacy_text(
        object_content_database,
        payload=b"legacy source that still needs capacity",
        estimate=2048,
    )
    referenced_content_id = await _attach_existing_inline_reference(
        object_content_database,
        file_id=referenced_file_id,
    )
    backfill = _backfill(
        object_content_database,
        auto_inline_max_bytes=1024,
        batch_rows=1,
    )

    preparing = await backfill.run_once()

    assert preparing.state is FileIconBackfillState.ACTIVE
    assert preparing.completed_count == 0
    async with object_content_database.session() as session, session.begin():
        await ObjectContentRepository(session).mark_backend_failure(
            content_id=referenced_content_id,
            failure_code=ContentFailureCode.BACKEND_CORRUPT,
        )

    waiting = await backfill.run_once()

    assert waiting.state is FileIconBackfillState.WAITING_FOR_CAPACITY
    assert waiting.completed_count == 0
    async with object_content_database.session() as session, session.begin():
        states = (
            (
                await session.execute(
                    sa.text(
                        """
                    SELECT state
                    FROM file_icon_backfill_items
                    ORDER BY id
                    """
                    )
                )
            )
            .scalars()
            .all()
        )
        content_count = await session.scalar(
            sa.select(sa.func.count()).select_from(sa.table("object_contents"))
        )
    assert states == ["ready", "ready"]
    assert content_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "waiting_state"),
    [
        (StorageKind.POSTGRES_INLINE, FileIconBackfillState.WAITING_FOR_CAPACITY),
        (StorageKind.OBJECT_STORE, FileIconBackfillState.WAITING_FOR_OBJECT_STORE),
    ],
)
async def test_waiting_campaign_completes_when_last_owner_is_deleted(
    object_content_database: DatabaseSessionManager,
    target: StorageKind,
    waiting_state: FileIconBackfillState,
) -> None:
    file_id = await _seed_legacy_text(
        object_content_database,
        payload=b"delete while waiting",
        estimate=2048,
    )
    backfill = _backfill(
        object_content_database,
        auto_inline_max_bytes=1024,
    )
    try:
        await _set_policy_target(object_content_database, target.value)

        waiting = await backfill.run_once()

        assert waiting.state is waiting_state
        async with object_content_database.session() as session, session.begin():
            await session.execute(
                sa.text("DELETE FROM files WHERE id = :file_id"),
                {"file_id": file_id},
            )

        completed = await backfill.run_once()

        assert completed.state is FileIconBackfillState.COMPLETE
        async with object_content_database.session() as session, session.begin():
            item_state = await session.scalar(
                sa.text(
                    """
                    SELECT state
                    FROM file_icon_backfill_items
                    WHERE owner_id = :file_id
                    """
                ),
                {"file_id": file_id},
            )
        assert item_state == "cancelled"
    finally:
        await _set_policy_target(
            object_content_database,
            StorageKind.POSTGRES_INLINE.value,
        )


@pytest.mark.asyncio
async def test_expired_lease_resumes_without_duplicate_content(
    object_content_database: DatabaseSessionManager,
) -> None:
    file_id = await _seed_legacy_text(
        object_content_database,
        payload=b"resume me",
    )
    async with object_content_database.session() as session, session.begin():
        await session.execute(
            sa.text(
                """
                UPDATE file_icon_backfill_items
                SET state = 'leased', attempts = 1, lease_owner = 'dead-worker',
                    lease_expires_at = :expired
                WHERE owner_id = :file_id
                """
            ),
            {
                "file_id": file_id,
                "expired": datetime.now(UTC) - timedelta(seconds=1),
            },
        )

    result = await _backfill(object_content_database).run_once()
    repeated = await _backfill(object_content_database).run_once()

    assert result.state is FileIconBackfillState.COMPLETE
    assert result.completed_count == 1
    assert repeated.state is FileIconBackfillState.COMPLETE
    assert repeated.claimed_count == 0
    async with object_content_database.session() as session, session.begin():
        row = (
            await session.execute(
                sa.text(
                    """
                    SELECT attempts, state, content_id
                    FROM file_icon_backfill_items
                    WHERE owner_id = :file_id
                    """
                ),
                {"file_id": file_id},
            )
        ).one()
        content_count = await session.scalar(
            sa.select(sa.func.count()).select_from(sa.table("object_contents"))
        )
    assert row.attempts == 2
    assert row.state == "done"
    assert row.content_id is not None
    assert content_count == 1


@pytest.mark.asyncio
async def test_deleted_owner_is_cancelled_without_creating_content(
    object_content_database: DatabaseSessionManager,
) -> None:
    file_id = await _seed_legacy_text(
        object_content_database,
        payload=b"delete raced",
        estimate=2048,
    )
    async with object_content_database.session() as session, session.begin():
        await session.execute(
            sa.text("DELETE FROM files WHERE id = :file_id"),
            {"file_id": file_id},
        )

    result = await _backfill(
        object_content_database,
        auto_inline_max_bytes=1024,
    ).run_once()

    assert result.state is FileIconBackfillState.COMPLETE
    assert result.cancelled_count == 0
    async with object_content_database.session() as session, session.begin():
        item = (
            await session.execute(
                sa.text(
                    """
                    SELECT state, content_id
                    FROM file_icon_backfill_items
                    WHERE owner_id = :file_id
                    """
                ),
                {"file_id": file_id},
            )
        ).one()
        content_count = await session.scalar(
            sa.select(sa.func.count()).select_from(sa.table("object_contents"))
        )
    assert item == ("cancelled", None)
    assert content_count == 0


@pytest.mark.asyncio
async def test_deleted_icon_is_cancelled_by_the_database_fence(
    object_content_database: DatabaseSessionManager,
) -> None:
    icon_id = await _seed_legacy_icon(
        object_content_database,
        payload=b"<svg>deleted</svg>",
    )
    async with object_content_database.session() as session, session.begin():
        await session.execute(
            sa.text("DELETE FROM icons WHERE id = :icon_id"),
            {"icon_id": icon_id},
        )

    result = await _backfill(object_content_database).run_once()

    assert result.state is FileIconBackfillState.COMPLETE
    async with object_content_database.session() as session, session.begin():
        item = (
            await session.execute(
                sa.text(
                    """
                    SELECT state, content_id
                    FROM file_icon_backfill_items
                    WHERE owner_id = :icon_id
                    """
                ),
                {"icon_id": icon_id},
            )
        ).one()
    assert item == ("cancelled", None)


@pytest.mark.asyncio
async def test_existing_reference_does_not_require_phantom_inline_capacity(
    object_content_database: DatabaseSessionManager,
) -> None:
    file_id = await _seed_legacy_text(
        object_content_database,
        payload=b"legacy source",
        estimate=2048,
    )
    content_id = await _attach_existing_inline_reference(
        object_content_database,
        file_id=file_id,
    )

    result = await _backfill(
        object_content_database,
        auto_inline_max_bytes=1024,
    ).run_once()

    assert result.state is FileIconBackfillState.COMPLETE
    assert result.completed_count == 1
    async with object_content_database.session() as session, session.begin():
        item = (
            await session.execute(
                sa.text(
                    """
                    SELECT state, content_id
                    FROM file_icon_backfill_items
                    WHERE owner_id = :file_id
                    """
                ),
                {"file_id": file_id},
            )
        ).one()
    assert item == ("done", content_id)


@pytest.mark.asyncio
async def test_failed_adopted_reference_reopens_completed_campaign_for_recovery(
    object_content_database: DatabaseSessionManager,
) -> None:
    payload = b"authoritative legacy source"
    file_id = await _seed_legacy_text(
        object_content_database,
        payload=payload,
    )
    completed_backfill = _backfill(object_content_database)

    completed = await completed_backfill.run_once()

    assert completed.state is FileIconBackfillState.COMPLETE
    tenant_id, _ = await _tenant_and_user(object_content_database)
    async with object_content_database.session() as session, session.begin():
        content_id = await session.scalar(
            sa.select(FileContentReferences.content_id).where(
                FileContentReferences.file_id == file_id,
                FileContentReferences.variant == "extracted_text",
                FileContentReferences.ordinal == 0,
            )
        )
        assert content_id is not None
        await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
        await session.execute(
            sa.update(InlineContentPayloads)
            .where(InlineContentPayloads.content_id == content_id)
            .values(payload=b"x" * len(payload))
        )

    service = ObjectContentService(
        ObjectContentCoreSettings(
            inline_maximum_bytes=1024,
            inline_io_chunk_bytes=256,
        ),
        object_content_database,
    )
    grant = ContentReadGrant(
        content_id=content_id,
        tenant_id=tenant_id,
        access_class=ContentAccessClass.PRIVATE_RESOURCE,
    )
    with pytest.raises(ObjectContentIntegrityError):
        async with service.open_content(grant) as opened:
            _ = b"".join([chunk async for chunk in opened.chunks])

    halted = await completed_backfill.run_once()

    assert halted.state is FileIconBackfillState.HALTED
    async with object_content_database.session() as session, session.begin():
        failed_state = (
            await session.execute(
                sa.text(
                    """
                SELECT item.state, item.content_id, campaign.state,
                       item.failure_revision
                FROM file_icon_backfill_items AS item
                CROSS JOIN file_icon_backfill_campaign AS campaign
                WHERE item.owner_id = :file_id
                """
                ),
                {"file_id": file_id},
            )
        ).one()
    assert failed_state == ("failed", None, "halted", 0)

    recovered = await _backfill(
        object_content_database,
        resume_revision=1,
    ).run_once()

    assert recovered.state is FileIconBackfillState.COMPLETE
    assert recovered.completed_count == 1
    async with object_content_database.session() as session, session.begin():
        replacement_id = await session.scalar(
            sa.select(FileContentReferences.content_id).where(
                FileContentReferences.file_id == file_id,
                FileContentReferences.variant == "extracted_text",
                FileContentReferences.ordinal == 0,
            )
        )
        replacement = await session.get(ObjectContents, replacement_id)
        replacement_state = None if replacement is None else replacement.state
        replacement_sha256 = None if replacement is None else replacement.sha256
        item_state = await session.scalar(
            sa.text(
                """
                SELECT state
                FROM file_icon_backfill_items
                WHERE owner_id = :file_id
                """
            ),
            {"file_id": file_id},
        )
    assert replacement_id != content_id
    assert replacement is not None
    assert replacement_state == ContentState.AVAILABLE.value
    assert replacement_sha256 == sha256(payload).digest()
    assert item_state == "done"


@pytest.mark.asyncio
async def test_failed_existing_reference_is_replaced_by_available_legacy_content(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"authoritative legacy source"
    file_id = await _seed_legacy_text(object_content_database, payload=payload)
    failed_content_id = await _attach_existing_inline_reference(
        object_content_database,
        file_id=file_id,
        payload=b"untrusted durable content",
        page_number=2,
        width=640,
        height=480,
        duration_ms=1200,
    )
    async with object_content_database.session() as session, session.begin():
        await ObjectContentRepository(session).mark_backend_failure(
            content_id=failed_content_id,
            failure_code=ContentFailureCode.BACKEND_CORRUPT,
        )

    original_delete_reference = (
        file_icon_backfill_module._FileIconBackfillRepository.__dict__[
            "_delete_reference"
        ]
    )

    async def fail_after_delete(
        repository: file_icon_backfill_module._FileIconBackfillRepository,
        item: file_icon_backfill_module._WorkItem,
        *,
        content_id: UUID,
    ) -> None:
        await original_delete_reference(
            repository,
            item,
            content_id=content_id,
        )
        raise OSError("injected failure after reference delete")

    monkeypatch.setattr(
        file_icon_backfill_module._FileIconBackfillRepository,
        "_delete_reference",
        fail_after_delete,
    )
    with pytest.raises(OSError, match="injected failure"):
        await _backfill(object_content_database).run_once()

    async with object_content_database.session() as session, session.begin():
        rolled_back_reference_id = await session.scalar(
            sa.select(FileContentReferences.content_id).where(
                FileContentReferences.file_id == file_id,
                FileContentReferences.variant == "extracted_text",
                FileContentReferences.ordinal == 0,
            )
        )
        rolled_back_item = (
            await session.execute(
                sa.text(
                    """
                    SELECT state, content_id, lease_owner
                    FROM file_icon_backfill_items
                    WHERE owner_id = :file_id
                    """
                ),
                {"file_id": file_id},
            )
        ).one()
        content_count = await session.scalar(
            sa.select(sa.func.count()).select_from(ObjectContents)
        )
        assert rolled_back_reference_id == failed_content_id
        assert rolled_back_item[0] == "leased"
        assert rolled_back_item[1] is None
        assert rolled_back_item[2] is not None
        assert content_count == 1
        await session.execute(
            sa.text(
                """
                UPDATE file_icon_backfill_items
                SET lease_expires_at = :expired
                WHERE owner_id = :file_id
                """
            ),
            {
                "file_id": file_id,
                "expired": datetime.now(UTC) - timedelta(seconds=1),
            },
        )

    monkeypatch.setattr(
        file_icon_backfill_module._FileIconBackfillRepository,
        "_delete_reference",
        original_delete_reference,
    )
    result = await _backfill(object_content_database).run_once()

    assert result.state is FileIconBackfillState.COMPLETE
    assert result.completed_count == 1
    assert result.failed_count == 0
    async with object_content_database.session() as session, session.begin():
        reference = (
            await session.execute(
                sa.select(
                    FileContentReferences.content_id,
                    FileContentReferences.page_number,
                    FileContentReferences.width,
                    FileContentReferences.height,
                    FileContentReferences.duration_ms,
                ).where(
                    FileContentReferences.file_id == file_id,
                    FileContentReferences.variant == "extracted_text",
                    FileContentReferences.ordinal == 0,
                )
            )
        ).one()
        reference_content_id = reference.content_id
        assert reference_content_id is not None
        replacement = await session.get(ObjectContents, reference_content_id)
        failed = await session.get(ObjectContents, failed_content_id)
        item = (
            await session.execute(
                sa.text(
                    """
                    SELECT state, content_id
                    FROM file_icon_backfill_items
                    WHERE owner_id = :file_id
                    """
                ),
                {"file_id": file_id},
            )
        ).one()
        assert reference_content_id != failed_content_id
        assert reference.page_number == 2
        assert reference.width == 640
        assert reference.height == 480
        assert reference.duration_ms == 1200
        assert replacement is not None
        assert replacement.state == ContentState.AVAILABLE.value
        assert replacement.sha256 == sha256(payload).digest()
        assert replacement.reference_count == 1
        assert failed is not None
        assert failed.state == ContentState.FAILED.value
        assert failed.failure_code == ContentFailureCode.BACKEND_CORRUPT.value
        assert failed.reference_count == 0
        assert failed.delete_requested_at is not None
        assert failed.next_attempt_at is not None
        assert item == ("done", reference_content_id)


@pytest.mark.asyncio
async def test_failed_icon_reference_is_replaced_by_available_legacy_content(
    object_content_database: DatabaseSessionManager,
) -> None:
    payload = b"<svg>authoritative legacy icon</svg>"
    icon_id = await _seed_legacy_icon(object_content_database, payload=payload)
    failed_content_id = await _attach_existing_inline_icon_reference(
        object_content_database,
        icon_id=icon_id,
        payload=b"<svg>untrusted durable icon</svg>",
    )
    async with object_content_database.session() as session, session.begin():
        await ObjectContentRepository(session).mark_backend_failure(
            content_id=failed_content_id,
            failure_code=ContentFailureCode.BACKEND_CORRUPT,
        )

    result = await _backfill(object_content_database).run_once()

    assert result.state is FileIconBackfillState.COMPLETE
    assert result.completed_count == 1
    assert result.failed_count == 0
    async with object_content_database.session() as session, session.begin():
        replacement_id = await session.scalar(
            sa.select(IconContentReferences.content_id).where(
                IconContentReferences.icon_id == icon_id,
                IconContentReferences.variant == "primary",
            )
        )
        assert replacement_id is not None
        replacement = await session.get(ObjectContents, replacement_id)
        failed = await session.get(ObjectContents, failed_content_id)
        item = (
            await session.execute(
                sa.text(
                    """
                    SELECT state, content_id
                    FROM file_icon_backfill_items
                    WHERE owner_id = :icon_id
                    """
                ),
                {"icon_id": icon_id},
            )
        ).one()
        assert replacement_id != failed_content_id
        assert replacement is not None
        assert replacement.state == ContentState.AVAILABLE.value
        assert replacement.sha256 == sha256(payload).digest()
        assert replacement.reference_count == 1
        assert failed is not None
        assert failed.state == ContentState.FAILED.value
        assert failed.reference_count == 0
        assert failed.delete_requested_at is not None
        assert failed.next_attempt_at is not None
        assert item == ("done", replacement_id)


@pytest.mark.asyncio
async def test_owner_delete_waits_for_existing_reference_admission_fence(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_id = await _seed_legacy_text(
        object_content_database,
        payload=b"legacy source",
    )
    await _attach_existing_inline_reference(
        object_content_database,
        file_id=file_id,
    )
    reference_seen = asyncio.Event()
    continue_processing = asyncio.Event()
    original_lock_references = (
        file_icon_backfill_module._FileIconBackfillRepository.__dict__[
            "_lock_admission_references"
        ]
    )

    async def pause_after_reference_discovery(
        repository: file_icon_backfill_module._FileIconBackfillRepository,
        items: Sequence[file_icon_backfill_module.FileIconBackfillItems],
    ) -> dict[
        tuple[str, UUID, str, int],
        file_icon_backfill_module._ExistingReference,
    ]:
        references = await original_lock_references(repository, items)
        reference_seen.set()
        await continue_processing.wait()
        return references

    monkeypatch.setattr(
        file_icon_backfill_module._FileIconBackfillRepository,
        "_lock_admission_references",
        pause_after_reference_discovery,
    )
    running = asyncio.create_task(_backfill(object_content_database).run_once())
    deleting: asyncio.Task[None] | None = None

    async def delete_owner() -> None:
        async with object_content_database.session() as session, session.begin():
            await session.execute(
                sa.text("DELETE FROM files WHERE id = :file_id"),
                {"file_id": file_id},
            )

    try:
        await asyncio.wait_for(reference_seen.wait(), timeout=5)
        deleting = asyncio.create_task(delete_owner())
        await asyncio.sleep(0.1)
        assert not deleting.done()
    finally:
        continue_processing.set()
    result = await running
    assert deleting is not None
    await deleting

    assert result.state is FileIconBackfillState.COMPLETE
    assert result.completed_count == 1
    async with object_content_database.session() as session, session.begin():
        item = (
            await session.execute(
                sa.text(
                    """
                    SELECT state, content_id
                    FROM file_icon_backfill_items
                    WHERE owner_id = :file_id
                    """
                ),
                {"file_id": file_id},
            )
        ).one()
        reference_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FileContentReferences)
            .where(FileContentReferences.file_id == file_id)
        )
    assert item == ("cancelled", None)
    assert reference_count == 0


@pytest.mark.asyncio
async def test_admission_retries_instead_of_deadlocking_with_parent_delete(
    object_content_database: DatabaseSessionManager,
) -> None:
    parent_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    child_id = UUID("00000000-0000-0000-0000-000000000001")
    assert child_id < parent_id
    await _seed_legacy_text(
        object_content_database,
        payload=b"parent",
        file_id=parent_id,
    )
    await _seed_legacy_text(
        object_content_database,
        payload=b"child",
        file_id=child_id,
        parent_file_id=parent_id,
    )
    parent_locked = asyncio.Event()
    allow_delete = asyncio.Event()

    async def delete_family() -> None:
        async with object_content_database.session() as session, session.begin():
            await session.execute(
                sa.text("SELECT id FROM files WHERE id = :file_id FOR UPDATE"),
                {"file_id": parent_id},
            )
            parent_locked.set()
            await allow_delete.wait()
            await session.execute(
                sa.text("DELETE FROM files WHERE id = :file_id"),
                {"file_id": parent_id},
            )

    deleting = asyncio.create_task(delete_family())
    try:
        await asyncio.wait_for(parent_locked.wait(), timeout=5)
        contended = await asyncio.wait_for(
            _backfill(object_content_database).run_once(), timeout=5
        )
    finally:
        allow_delete.set()
    await asyncio.wait_for(deleting, timeout=5)

    assert contended.state is FileIconBackfillState.ACTIVE
    assert contended.admitted_count == 0
    assert contended.claimed_count == 0
    assert contended.detail is not None
    assert "will retry" in contended.detail

    completed = await _backfill(object_content_database).run_once()

    assert completed.state is FileIconBackfillState.COMPLETE
    async with object_content_database.session() as session, session.begin():
        states = (
            (
                await session.execute(
                    sa.text(
                        """
                    SELECT state
                    FROM file_icon_backfill_items
                    WHERE owner_id IN (:parent_id, :child_id)
                    ORDER BY owner_id
                    """
                    ),
                    {"parent_id": parent_id, "child_id": child_id},
                )
            )
            .scalars()
            .all()
        )
    assert states == ["cancelled", "cancelled"]


@pytest.mark.asyncio
async def test_owner_deleted_before_the_atomic_flip_is_cancelled(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_id = await _seed_legacy_text(
        object_content_database,
        payload=b"delete before flip",
    )
    original_complete_inline = (
        file_icon_backfill_module._FileIconBackfillRepository.complete_inline
    )

    async def delete_owner_before_flip(
        repository: file_icon_backfill_module._FileIconBackfillRepository,
        item: file_icon_backfill_module._WorkItem,
        object_content: ObjectContentService,
    ) -> bool:
        async with object_content_database.session() as session, session.begin():
            await session.execute(
                sa.text("DELETE FROM files WHERE id = :file_id"),
                {"file_id": file_id},
            )
        return await original_complete_inline(repository, item, object_content)

    monkeypatch.setattr(
        file_icon_backfill_module._FileIconBackfillRepository,
        "complete_inline",
        delete_owner_before_flip,
    )

    result = await _backfill(object_content_database).run_once()

    assert result.state is FileIconBackfillState.COMPLETE
    assert result.cancelled_count == 1
    async with object_content_database.session() as session, session.begin():
        item = (
            await session.execute(
                sa.text(
                    """
                    SELECT state, content_id
                    FROM file_icon_backfill_items
                    WHERE owner_id = :file_id
                    """
                ),
                {"file_id": file_id},
            )
        ).one()
    assert item == ("cancelled", None)


@pytest.mark.asyncio
async def test_worker_that_loses_its_lease_leaves_the_new_owner_untouched(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_id = await _seed_legacy_text(
        object_content_database,
        payload=b"lease changed before flip",
    )
    original_complete_inline = (
        file_icon_backfill_module._FileIconBackfillRepository.complete_inline
    )

    async def replace_lease_before_flip(
        repository: file_icon_backfill_module._FileIconBackfillRepository,
        item: file_icon_backfill_module._WorkItem,
        object_content: ObjectContentService,
    ) -> bool:
        async with object_content_database.session() as session, session.begin():
            await session.execute(
                sa.text(
                    """
                    UPDATE file_icon_backfill_items
                    SET lease_owner = 'replacement-worker',
                        lease_expires_at = :lease_expires_at
                    WHERE owner_id = :file_id
                    """
                ),
                {
                    "file_id": file_id,
                    "lease_expires_at": datetime.now(UTC) + timedelta(minutes=5),
                },
            )
        return await original_complete_inline(repository, item, object_content)

    monkeypatch.setattr(
        file_icon_backfill_module._FileIconBackfillRepository,
        "complete_inline",
        replace_lease_before_flip,
    )

    result = await _backfill(object_content_database).run_once()

    assert result.state is FileIconBackfillState.ACTIVE
    assert result.claimed_count == 1
    assert result.completed_count == 0
    assert result.failed_count == 0
    async with object_content_database.session() as session, session.begin():
        item = (
            await session.execute(
                sa.text(
                    """
                    SELECT state, lease_owner, last_error_code, content_id
                    FROM file_icon_backfill_items
                    WHERE owner_id = :file_id
                    """
                ),
                {"file_id": file_id},
            )
        ).one()
        content_count = await session.scalar(
            sa.select(sa.func.count()).select_from(sa.table("object_contents"))
        )
    assert item == ("leased", "replacement-worker", None, None)
    assert content_count == 0


@pytest.mark.asyncio
async def test_repeated_unclassified_error_becomes_a_visible_terminal_failure(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_id = await _seed_legacy_text(
        object_content_database,
        payload=b"processed first",
    )
    poison_id = await _seed_legacy_text(
        object_content_database,
        payload=b"cannot spool",
    )
    last_id = await _seed_legacy_text(
        object_content_database,
        payload=b"processed last",
    )

    original_complete_inline = (
        file_icon_backfill_module._FileIconBackfillRepository.__dict__[
            "complete_inline"
        ]
    )

    async def fail_during_poison_flip(
        repository: file_icon_backfill_module._FileIconBackfillRepository,
        item: file_icon_backfill_module._WorkItem,
        object_content: ObjectContentService,
    ) -> bool:
        if item.owner_id == poison_id:
            raise OSError("database connection reset during inline adoption")
        return await original_complete_inline(
            repository,
            item,
            object_content,
        )

    monkeypatch.setattr(
        file_icon_backfill_module._FileIconBackfillRepository,
        "complete_inline",
        fail_during_poison_flip,
    )
    backfill = _backfill(
        object_content_database,
        max_attempts=1,
    )

    with pytest.raises(OSError, match="database connection reset"):
        await backfill.run_once()

    async with object_content_database.session() as session, session.begin():
        await session.execute(
            sa.text(
                """
                UPDATE file_icon_backfill_items
                SET lease_expires_at = :expired
                WHERE state = 'leased'
                """
            ),
            {
                "expired": datetime.now(UTC) - timedelta(seconds=1),
            },
        )

    result = await backfill.run_once()

    assert result.state is FileIconBackfillState.HALTED
    assert result.failed_count == 1
    async with object_content_database.session() as session, session.begin():
        rows = {
            row.owner_id: row
            for row in (
                await session.execute(
                    sa.text(
                        """
                        SELECT owner_id, state, attempts, last_error_code,
                               last_error_detail
                        FROM file_icon_backfill_items
                        ORDER BY id
                        """
                    )
                )
            ).all()
        }
    assert rows[first_id].state == "done"
    assert rows[first_id].attempts == 1
    assert rows[last_id].state == "done"
    assert rows[last_id].attempts == 1
    assert rows[poison_id].state == "failed"
    assert rows[poison_id].attempts == 2
    assert rows[poison_id].last_error_code == "retry_exhausted"
    assert "1 processing attempt" in rows[poison_id].last_error_detail

    monkeypatch.setattr(
        file_icon_backfill_module._FileIconBackfillRepository,
        "complete_inline",
        original_complete_inline,
    )
    resumed = await _backfill(
        object_content_database,
        max_attempts=1,
        resume_revision=1,
    ).run_once()

    assert resumed.state is FileIconBackfillState.COMPLETE
    async with object_content_database.session() as session, session.begin():
        resumed_item = (
            await session.execute(
                sa.text(
                    """
                    SELECT state, attempts
                    FROM file_icon_backfill_items
                    WHERE owner_id = :poison_id
                    """
                ),
                {"poison_id": poison_id},
            )
        ).one()
    assert resumed_item == ("done", 1)


@pytest.mark.asyncio
async def test_concurrent_runs_share_one_cluster_wide_batch_bound(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_legacy_text(
        object_content_database,
        payload=b"hold the first run",
    )
    entered_flip = asyncio.Event()
    release_flip = asyncio.Event()
    original_complete_inline = (
        file_icon_backfill_module._FileIconBackfillRepository.complete_inline
    )

    async def pause_during_flip(
        repository: file_icon_backfill_module._FileIconBackfillRepository,
        item: file_icon_backfill_module._WorkItem,
        object_content: ObjectContentService,
    ) -> bool:
        entered_flip.set()
        await release_flip.wait()
        return await original_complete_inline(repository, item, object_content)

    monkeypatch.setattr(
        file_icon_backfill_module._FileIconBackfillRepository,
        "complete_inline",
        pause_during_flip,
    )
    backfill = _backfill(object_content_database)
    first = asyncio.create_task(backfill.run_once())
    try:
        await asyncio.wait_for(entered_flip.wait(), timeout=5)
        overlapping = await asyncio.wait_for(backfill.run_once(), timeout=5)
    finally:
        release_flip.set()
    completed = await first

    assert overlapping.state is FileIconBackfillState.ACTIVE
    assert overlapping.claimed_count == 0
    assert overlapping.detail == "Another worker owns the current backfill run"
    assert completed.state is FileIconBackfillState.COMPLETE
    assert completed.claimed_count == 1
    assert completed.completed_count == 1


@pytest.mark.asyncio
async def test_oversized_item_halts_after_other_items_finish(
    object_content_database: DatabaseSessionManager,
) -> None:
    oversized_id = await _seed_legacy_text(
        object_content_database,
        payload=b"too-large",
    )
    small_id = await _seed_legacy_text(
        object_content_database,
        payload=b"ok",
    )

    result = await _backfill(
        object_content_database,
        batch_bytes=1024,
        inline_maximum_bytes=4,
    ).run_once()

    assert result.state is FileIconBackfillState.HALTED
    assert result.claimed_count == 2
    assert result.completed_count == 1
    assert result.failed_count == 1
    assert result.detail is not None
    async with object_content_database.session() as session, session.begin():
        rows = dict(
            (
                await session.execute(
                    sa.text(
                        """
                        SELECT owner_id, state
                        FROM file_icon_backfill_items
                        WHERE owner_id IN (:oversized_id, :small_id)
                        """
                    ),
                    {"oversized_id": oversized_id, "small_id": small_id},
                )
            ).all()
        )
    assert rows[oversized_id] == "failed"
    assert rows[small_id] == "done"

    unchanged = await _backfill(
        object_content_database,
        inline_maximum_bytes=1024,
    ).run_once()
    resumed = await _backfill(
        object_content_database,
        inline_maximum_bytes=1024,
        resume_revision=1,
    ).run_once()

    assert unchanged.state is FileIconBackfillState.HALTED
    assert unchanged.claimed_count == 0
    assert resumed.state is FileIconBackfillState.COMPLETE
    assert resumed.completed_count == 1
    async with object_content_database.session() as session, session.begin():
        retry = (
            await session.execute(
                sa.text(
                    """
                    SELECT item.state, item.attempts, campaign.resume_revision
                    FROM file_icon_backfill_items AS item
                    CROSS JOIN file_icon_backfill_campaign AS campaign
                    WHERE item.owner_id = :owner_id
                    """
                ),
                {"owner_id": oversized_id},
            )
        ).one()
        assert retry == ("done", 1, 1)


@pytest.mark.asyncio
async def test_oversized_item_is_rejected_before_postgres_produces_payload(
    object_content_database: DatabaseSessionManager,
) -> None:
    await _seed_legacy_text(
        object_content_database,
        payload=b"too-large",
    )
    async with object_content_database.session() as session:
        assert session.bind is not None
        engine = session.bind.sync_engine
    payload_statements: list[str] = []

    def capture_payload_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        normalized = statement.lower()
        if "sha256(" in normalized or "convert_to(" in normalized:
            payload_statements.append(statement)

    sa.event.listen(engine, "before_cursor_execute", capture_payload_statement)
    try:
        result = await _backfill(
            object_content_database,
            inline_maximum_bytes=4,
        ).run_once()
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture_payload_statement)

    assert result.state is FileIconBackfillState.HALTED
    assert result.failed_count == 1
    assert payload_statements == []


@pytest.mark.asyncio
async def test_resume_requeues_failed_items_in_durable_bounded_batches(
    object_content_database: DatabaseSessionManager,
) -> None:
    owner_ids = [
        await _seed_legacy_text(
            object_content_database,
            payload=payload,
        )
        for payload in (b"poison", b"ok", b"ok", b"ok", b"ok")
    ]
    initial = _backfill(
        object_content_database,
        batch_rows=2,
        inline_maximum_bytes=1,
    )

    initial_states = [(await initial.run_once()).state for _ in range(5)]

    assert initial_states == [
        FileIconBackfillState.ACTIVE,
        FileIconBackfillState.ACTIVE,
        FileIconBackfillState.ACTIVE,
        FileIconBackfillState.ACTIVE,
        FileIconBackfillState.HALTED,
    ]

    first_resume = await _backfill(
        object_content_database,
        batch_rows=2,
        inline_maximum_bytes=2,
        resume_revision=1,
    ).run_once()

    assert first_resume.state is FileIconBackfillState.ACTIVE
    assert first_resume.claimed_count == 2
    assert first_resume.completed_count == 1
    assert first_resume.failed_count == 1
    async with object_content_database.session() as session, session.begin():
        rows = (
            await session.execute(
                sa.text(
                    """
                    SELECT id, owner_id, state, failure_revision
                    FROM file_icon_backfill_items
                    ORDER BY id
                    """
                )
            )
        ).all()
        campaign = (
            await session.execute(
                sa.text(
                    """
                    SELECT state, resume_revision, resume_cursor_id
                    FROM file_icon_backfill_campaign
                    """
                )
            )
        ).one()
    assert [(row.owner_id, row.state, row.failure_revision) for row in rows] == [
        (owner_ids[0], "failed", 1),
        (owner_ids[1], "done", None),
        (owner_ids[2], "failed", 0),
        (owner_ids[3], "failed", 0),
        (owner_ids[4], "failed", 0),
    ]
    assert campaign == ("active", 1, rows[1].id)

    second_resume = await _backfill(
        object_content_database,
        batch_rows=2,
        inline_maximum_bytes=2,
        resume_revision=1,
    ).run_once()

    assert second_resume.state is FileIconBackfillState.ACTIVE
    assert second_resume.claimed_count == 2
    assert second_resume.completed_count == 2
    async with object_content_database.session() as session, session.begin():
        rows = (
            await session.execute(
                sa.text(
                    """
                    SELECT id, owner_id, state, failure_revision
                    FROM file_icon_backfill_items
                    ORDER BY id
                    """
                )
            )
        ).all()
        cursor = await session.scalar(
            sa.text("SELECT resume_cursor_id FROM file_icon_backfill_campaign")
        )
    assert [(row.owner_id, row.state, row.failure_revision) for row in rows] == [
        (owner_ids[0], "failed", 1),
        (owner_ids[1], "done", None),
        (owner_ids[2], "done", None),
        (owner_ids[3], "done", None),
        (owner_ids[4], "failed", 0),
    ]
    assert cursor == rows[3].id

    final_resume = await _backfill(
        object_content_database,
        batch_rows=2,
        inline_maximum_bytes=2,
        resume_revision=1,
    ).run_once()
    unchanged = await _backfill(
        object_content_database,
        batch_rows=2,
        inline_maximum_bytes=1024,
        resume_revision=1,
    ).run_once()

    assert final_resume.state is FileIconBackfillState.HALTED
    assert final_resume.claimed_count == 1
    assert final_resume.completed_count == 1
    assert unchanged.state is FileIconBackfillState.HALTED
    assert unchanged.claimed_count == 0
    async with object_content_database.session() as session, session.begin():
        final_rows = (
            await session.execute(
                sa.text(
                    """
                    SELECT owner_id, state, failure_revision
                    FROM file_icon_backfill_items
                    ORDER BY id
                    """
                )
            )
        ).all()
        final_campaign = (
            await session.execute(
                sa.text(
                    """
                    SELECT state, resume_revision, resume_cursor_id
                    FROM file_icon_backfill_campaign
                    """
                )
            )
        ).one()
    assert final_rows == [
        (owner_ids[0], "failed", 1),
        (owner_ids[1], "done", None),
        (owner_ids[2], "done", None),
        (owner_ids[3], "done", None),
        (owner_ids[4], "done", None),
    ]
    assert final_campaign == ("halted", 1, None)


@pytest.mark.asyncio
async def test_empty_campaign_completes_without_claiming_work(
    object_content_database: DatabaseSessionManager,
) -> None:
    result = await _backfill(object_content_database).run_once()

    assert result.state is FileIconBackfillState.COMPLETE
    assert result.claimed_count == 0


@pytest.mark.asyncio
async def test_batch_estimate_limits_each_run_without_stranding_large_items(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_id = await _seed_legacy_text(
        object_content_database,
        payload=b"first",
        estimate=6,
    )
    second_id = await _seed_legacy_text(
        object_content_database,
        payload=b"second",
        estimate=6,
    )
    backfill = _backfill(
        object_content_database,
        batch_rows=10,
        batch_bytes=10,
    )

    first = await backfill.run_once()

    async def reject_hot_path_progress_scan(*_args: object) -> object:
        raise AssertionError("active batches must not rescan the complete ledger")

    with monkeypatch.context() as patch:
        patch.setattr(
            file_icon_backfill_module._FileIconBackfillRepository,
            "capacity_required_bytes",
            reject_hot_path_progress_scan,
        )
        second = await backfill.run_once()

    assert first.state is FileIconBackfillState.ACTIVE
    assert first.claimed_count == 1
    assert second.state is FileIconBackfillState.COMPLETE
    assert second.claimed_count == 1
    async with object_content_database.session() as session, session.begin():
        states = dict(
            (
                await session.execute(
                    sa.text(
                        """
                        SELECT owner_id, state
                        FROM file_icon_backfill_items
                        WHERE owner_id IN (:first_id, :second_id)
                        """
                    ),
                    {"first_id": first_id, "second_id": second_id},
                )
            ).all()
        )
    assert states == {first_id: "done", second_id: "done"}


@pytest.mark.asyncio
async def test_inline_backfill_preserves_exact_file_and_icon_variant_contracts(
    object_content_database: DatabaseSessionManager,
) -> None:
    text_id, image_id, icon_id = await _seed_legacy_variants(object_content_database)

    result = await _backfill(object_content_database).run_once()

    assert result.state is FileIconBackfillState.COMPLETE
    assert result.completed_count == 5
    async with object_content_database.session() as session, session.begin():
        rows = (
            await session.execute(
                sa.text(
                    """
                    SELECT
                        'file' AS owner_kind,
                        reference.file_id AS owner_id,
                        reference.variant,
                        content.verified_media_type,
                        content.access_class,
                        inline.payload
                    FROM file_content_references AS reference
                    JOIN object_contents AS content
                      ON content.id = reference.content_id
                    JOIN inline_content_payloads AS inline
                      ON inline.content_id = content.id
                    WHERE reference.file_id IN (:text_id, :image_id)
                    UNION ALL
                    SELECT
                        'icon', reference.icon_id, reference.variant,
                        content.verified_media_type, content.access_class,
                        inline.payload
                    FROM icon_content_references AS reference
                    JOIN object_contents AS content
                      ON content.id = reference.content_id
                    JOIN inline_content_payloads AS inline
                      ON inline.content_id = content.id
                    WHERE reference.icon_id = :icon_id
                    """
                ),
                {"text_id": text_id, "image_id": image_id, "icon_id": icon_id},
            )
        ).all()
        legacy = (
            await session.execute(
                sa.text(
                    """
                    SELECT file.text, file.blob, file.transcription, icon.blob
                    FROM files AS file
                    CROSS JOIN icons AS icon
                    WHERE file.id = :text_id AND icon.id = :icon_id
                    """
                ),
                {"text_id": text_id, "icon_id": icon_id},
            )
        ).one()

    actual = {
        (row.owner_kind, row.owner_id, row.variant): (
            row.verified_media_type,
            row.access_class,
            row.payload,
        )
        for row in rows
    }
    assert actual == {
        ("file", text_id, "extracted_text"): (
            "text/plain",
            "private_resource",
            b"extract",
        ),
        ("file", text_id, "original"): (
            "application/pdf",
            "private_resource",
            b"original",
        ),
        ("file", text_id, "transcription"): (
            "text/plain",
            "private_resource",
            b"spoken",
        ),
        ("file", image_id, "legacy_image"): (
            "image/png",
            "private_resource",
            b"image",
        ),
        ("icon", icon_id, "primary"): (
            "image/svg+xml",
            "public_immutable",
            b"icon",
        ),
    }
    assert legacy == ("extract", b"original", "spoken", b"icon")


@pytest.mark.asyncio
async def test_campaign_never_silently_changes_its_frozen_destination(
    object_content_database: DatabaseSessionManager,
) -> None:
    await _seed_legacy_text(object_content_database, payload=b"first")
    await _seed_legacy_text(object_content_database, payload=b"second")
    backfill = _backfill(
        object_content_database,
        batch_rows=1,
    )
    try:
        await _set_policy_target(object_content_database, "object_store")
        preparing = await backfill.run_once()
        waiting = await backfill.run_once()
        assert preparing.state is FileIconBackfillState.ACTIVE
        assert preparing.target_kind is None
        assert waiting.state is FileIconBackfillState.WAITING_FOR_OBJECT_STORE
        assert waiting.claimed_count == 0

        await _set_policy_target(object_content_database, "postgres_inline")
        active = await backfill.run_once()
        assert active.state is FileIconBackfillState.ACTIVE
        assert active.completed_count == 1

        await _set_policy_target(object_content_database, "object_store")
        halted = await backfill.run_once()
        assert halted.state is FileIconBackfillState.HALTED
        assert halted.claimed_count == 0
        assert halted.detail is not None
        assert "storage target changed" in halted.detail
    finally:
        await _set_policy_target(object_content_database, "postgres_inline")
