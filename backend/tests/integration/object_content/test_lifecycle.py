import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContentHolds,
    ObjectContents,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.object_content.content import (
    CapturedContent,
    ContentFailureCode,
    ContentState,
    ObjectContentBusyError,
)
from eneo.object_content.content_repository import ObjectContentRepository
from eneo.object_content.reconciliation_repository import (
    ObjectContentReconciliationRepository,
)


@dataclass(frozen=True, slots=True)
class _OwnedContent:
    tenant_id: UUID
    user_id: UUID
    file_id: UUID
    content_id: UUID


async def _owner_ids(database: DatabaseSessionManager) -> tuple[UUID, UUID]:
    async with database.session() as session, session.begin():
        tenant_id = (await session.scalars(select(Tenants.id))).one()
        user_id = (await session.scalars(select(Users.id))).one()
    return tenant_id, user_id


def _file(*, tenant_id: UUID, user_id: UUID, name: str) -> Files:
    return Files(
        name=name,
        text=None,
        blob=None,
        checksum=sha256(name.encode()).hexdigest(),
        size=1,
        mimetype="text/plain",
        file_type="text",
        transcription=None,
        tenant_id=tenant_id,
        user_id=user_id,
        parent_file_id=None,
    )


async def _available_content(
    database: DatabaseSessionManager,
    *,
    minimum_retain_until: datetime | None = None,
) -> _OwnedContent:
    tenant_id, user_id = await _owner_ids(database)
    token = uuid4().hex
    digest = sha256(token.encode()).digest()
    async with database.session() as session, session.begin():
        owner = _file(
            tenant_id=tenant_id,
            user_id=user_id,
            name=f"{token}.txt",
        )
        content = ObjectContents(
            tenant_id=tenant_id,
            created_by_user_id=user_id,
            object_key=f"v1/a2d539affef042aaa7f814376947be2c/{token}",
            state=ContentState.PENDING.value,
            access_class="private_resource",
            sha256=digest,
            size_bytes=1,
            declared_media_type="text/plain",
            verified_media_type="text/plain",
            idempotency_key=token,
            request_fingerprint=digest,
            minimum_retain_until=minimum_retain_until,
        )
        session.add_all([owner, content])
        await session.flush()
        session.add(
            FileContentReferences(
                file_id=owner.id,
                content_id=content.id,
                variant="original",
                ordinal=0,
            )
        )
        await session.flush()
        content.state = ContentState.AVAILABLE.value
        content.available_at = await session.scalar(select(func.now()))
        await session.flush()
        result = _OwnedContent(
            tenant_id=tenant_id,
            user_id=user_id,
            file_id=owner.id,
            content_id=content.id,
        )
    return result


async def _pending_content(
    database: DatabaseSessionManager,
) -> tuple[_OwnedContent, CapturedContent]:
    tenant_id, user_id = await _owner_ids(database)
    token = uuid4().hex
    payload = token.encode()
    digest = sha256(payload).digest()
    async with database.session() as session, session.begin():
        owner = _file(
            tenant_id=tenant_id,
            user_id=user_id,
            name=f"{token}.txt",
        )
        content = ObjectContents(
            tenant_id=tenant_id,
            created_by_user_id=user_id,
            object_key=f"v1/a2d539affef042aaa7f814376947be2c/{token}",
            state=ContentState.PENDING.value,
            access_class="private_resource",
            sha256=digest,
            size_bytes=len(payload),
            declared_media_type="text/plain",
            verified_media_type="text/plain",
            idempotency_key=token,
            request_fingerprint=digest,
        )
        session.add_all([owner, content])
        await session.flush()
        session.add(
            FileContentReferences(
                file_id=owner.id,
                content_id=content.id,
                variant="original",
                ordinal=0,
            )
        )
        await session.flush()
        owned = _OwnedContent(
            tenant_id=tenant_id,
            user_id=user_id,
            file_id=owner.id,
            content_id=content.id,
        )
    return owned, CapturedContent(
        file=BytesIO(payload),
        sha256=digest,
        size_bytes=len(payload),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        part_sha256=(digest,),
    )


async def _fail_and_detach(
    database: DatabaseSessionManager,
    owned: _OwnedContent,
) -> None:
    async with database.session() as session, session.begin():
        content = await session.get(ObjectContents, owned.content_id)
        assert content is not None
        content.state = ContentState.FAILED.value
        content.failure_code = ContentFailureCode.REMOTE_CORRUPT.value
        content.failure_detail = "test integrity failure"
        await session.flush()
        await session.execute(
            delete(FileContentReferences).where(
                FileContentReferences.file_id == owned.file_id
            )
        )


@pytest.mark.asyncio
async def test_final_reference_creates_irreversible_delete_intent(
    object_content_database: DatabaseSessionManager,
) -> None:
    owned = await _available_content(object_content_database)

    async with object_content_database.session() as session, session.begin():
        await session.execute(
            delete(FileContentReferences).where(
                FileContentReferences.file_id == owned.file_id
            )
        )

    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, owned.content_id)
        assert content is not None
        assert content.state == ContentState.DELETE_PENDING.value
        assert content.reference_count == 0
        assert content.delete_requested_at is not None

    with pytest.raises(DBAPIError, match="delete intent is irreversible"):
        async with object_content_database.session() as session, session.begin():
            content = await session.get(ObjectContents, owned.content_id)
            assert content is not None
            content.delete_requested_at = None
            await session.flush()


@pytest.mark.asyncio
async def test_active_hold_retains_content_and_release_schedules_delete(
    object_content_database: DatabaseSessionManager,
) -> None:
    owned = await _available_content(object_content_database)
    async with object_content_database.session() as session, session.begin():
        hold_id = await ObjectContentRepository(session).apply_hold(
            tenant_id=owned.tenant_id,
            content_id=owned.content_id,
            kind="legal",
            reason="test retention fence",
            actor_user_id=owned.user_id,
            expires_at=None,
        )
        await session.execute(
            delete(FileContentReferences).where(
                FileContentReferences.file_id == owned.file_id
            )
        )

    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, owned.content_id)
        assert content is not None
        assert content.state == ContentState.RETAINED.value
        await ObjectContentRepository(session).release_hold(
            tenant_id=owned.tenant_id,
            hold_id=hold_id,
        )

    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, owned.content_id)
        hold = await session.get(ObjectContentHolds, hold_id)
        assert content is not None
        assert hold is not None
        assert hold.released_at is not None
        assert content.state == ContentState.DELETE_PENDING.value


@pytest.mark.asyncio
async def test_hold_policy_is_immutable_until_explicit_release(
    object_content_database: DatabaseSessionManager,
) -> None:
    owned = await _available_content(object_content_database)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    async with object_content_database.session() as session, session.begin():
        hold_id = await ObjectContentRepository(session).apply_hold(
            tenant_id=owned.tenant_id,
            content_id=owned.content_id,
            kind="legal",
            reason="preserve the original hold policy",
            actor_user_id=owned.user_id,
            expires_at=expires_at,
        )

    with pytest.raises(DBAPIError, match="hold identity is immutable"):
        async with object_content_database.session() as session, session.begin():
            hold = await session.get(ObjectContentHolds, hold_id)
            assert hold is not None
            hold.expires_at = expires_at - timedelta(days=1)
            await session.flush()


@pytest.mark.asyncio
async def test_hold_expiry_cannot_predate_its_creation(
    object_content_database: DatabaseSessionManager,
) -> None:
    owned = await _available_content(object_content_database)

    with pytest.raises(DBAPIError, match="expires_at"):
        async with object_content_database.session() as session, session.begin():
            await ObjectContentRepository(session).apply_hold(
                tenant_id=owned.tenant_id,
                content_id=owned.content_id,
                kind="recovery",
                reason="invalid historical recovery hold",
                actor_user_id=owned.user_id,
                expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            )


@pytest.mark.asyncio
async def test_minimum_retention_is_monotonic_and_blocks_final_delete(
    object_content_database: DatabaseSessionManager,
) -> None:
    retain_until = datetime.now(timezone.utc) + timedelta(days=7)
    owned = await _available_content(
        object_content_database,
        minimum_retain_until=retain_until,
    )
    async with object_content_database.session() as session, session.begin():
        await session.execute(
            delete(FileContentReferences).where(
                FileContentReferences.file_id == owned.file_id
            )
        )

    with pytest.raises(DBAPIError, match="minimum retention may only be extended"):
        async with object_content_database.session() as session, session.begin():
            content = await session.get(ObjectContents, owned.content_id)
            assert content is not None
            assert content.state == ContentState.RETAINED.value
            content.minimum_retain_until = retain_until - timedelta(days=1)
            await session.flush()


@pytest.mark.asyncio
async def test_failed_content_respects_active_hold_until_release(
    object_content_database: DatabaseSessionManager,
) -> None:
    owned = await _available_content(object_content_database)
    async with object_content_database.session() as session, session.begin():
        hold_id = await ObjectContentRepository(session).apply_hold(
            tenant_id=owned.tenant_id,
            content_id=owned.content_id,
            kind="legal",
            reason="preserve failed bytes for an active legal hold",
            actor_user_id=owned.user_id,
            expires_at=None,
        )
    await _fail_and_detach(object_content_database, owned)

    async with object_content_database.session() as session, session.begin():
        advanced = await ObjectContentReconciliationRepository(
            session
        ).advance_local_lifecycle(limit=10, pending_stale_seconds=1)
        content = await session.get(ObjectContents, owned.content_id)
        assert advanced == 0
        assert content is not None
        assert content.state == ContentState.FAILED.value

    async with object_content_database.session() as session, session.begin():
        await ObjectContentRepository(session).release_hold(
            tenant_id=owned.tenant_id,
            hold_id=hold_id,
        )
    async with object_content_database.session() as session, session.begin():
        advanced = await ObjectContentReconciliationRepository(
            session
        ).advance_local_lifecycle(limit=10, pending_stale_seconds=1)
        content = await session.get(ObjectContents, owned.content_id)
        assert advanced == 1
        assert content is not None
        assert content.state == ContentState.DELETE_PENDING.value


@pytest.mark.asyncio
async def test_failed_content_respects_future_minimum_retention(
    object_content_database: DatabaseSessionManager,
) -> None:
    owned = await _available_content(
        object_content_database,
        minimum_retain_until=datetime.now(timezone.utc) + timedelta(days=7),
    )
    await _fail_and_detach(object_content_database, owned)

    async with object_content_database.session() as session, session.begin():
        advanced = await ObjectContentReconciliationRepository(
            session
        ).advance_local_lifecycle(limit=10, pending_stale_seconds=1)
        content = await session.get(ObjectContents, owned.content_id)
        assert advanced == 0
        assert content is not None
        assert content.state == ContentState.FAILED.value


@pytest.mark.asyncio
async def test_reference_count_is_trigger_owned_and_parent_cascade_is_fenced(
    object_content_database: DatabaseSessionManager,
) -> None:
    owned = await _available_content(object_content_database)

    with pytest.raises(DBAPIError, match="reference count is trigger-owned"):
        async with object_content_database.session() as session, session.begin():
            content = await session.get(ObjectContents, owned.content_id)
            assert content is not None
            content.reference_count = 99
            await session.flush()

    async with object_content_database.session() as session, session.begin():
        owner = await session.get(Files, owned.file_id)
        assert owner is not None
        await session.delete(owner)

    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, owned.content_id)
        assert content is not None
        assert content.reference_count == 0
        assert content.state == ContentState.DELETE_PENDING.value


@pytest.mark.asyncio
async def test_content_identity_and_integrity_facts_are_immutable(
    object_content_database: DatabaseSessionManager,
) -> None:
    owned = await _available_content(object_content_database)

    with pytest.raises(DBAPIError, match="identity and integrity facts are immutable"):
        async with object_content_database.session() as session, session.begin():
            content = await session.get(ObjectContents, owned.content_id)
            assert content is not None
            content.sha256 = sha256(b"different canonical bytes").digest()
            await session.flush()


@pytest.mark.asyncio
async def test_only_the_current_pending_worker_can_renew_its_bounded_lease(
    object_content_database: DatabaseSessionManager,
) -> None:
    owned, captured = await _pending_content(object_content_database)
    lease_owner = uuid4().hex
    async with object_content_database.session() as session, session.begin():
        await ObjectContentRepository(session).claim_upload(
            content_id=owned.content_id,
            content=captured,
            lease_owner=lease_owner,
            lease_seconds=300,
        )
        content = await session.get(ObjectContents, owned.content_id)
        assert content is not None
        original_lease_until = content.lease_until
        assert original_lease_until is not None

    with pytest.raises(ObjectContentBusyError, match="lease changed"):
        async with object_content_database.session() as session, session.begin():
            await ObjectContentRepository(session).renew_pending_lease(
                content_id=owned.content_id,
                lease_owner=uuid4().hex,
                lease_seconds=300,
            )

    await asyncio.sleep(0.01)
    async with object_content_database.session() as session, session.begin():
        await ObjectContentRepository(session).renew_pending_lease(
            content_id=owned.content_id,
            lease_owner=lease_owner,
            lease_seconds=300,
        )
        content = await session.get(ObjectContents, owned.content_id)
        assert content is not None
        assert content.lease_until is not None
        assert content.lease_until > original_lease_until


@pytest.mark.asyncio
async def test_integrity_failure_keeps_live_owner_recovery_options_open(
    object_content_database: DatabaseSessionManager,
) -> None:
    owned, captured = await _pending_content(object_content_database)
    lease_owner = uuid4().hex
    async with object_content_database.session() as session, session.begin():
        await ObjectContentRepository(session).claim_upload(
            content_id=owned.content_id,
            content=captured,
            lease_owner=lease_owner,
            lease_seconds=300,
        )
    async with object_content_database.session() as session, session.begin():
        repository = ObjectContentRepository(session)
        await repository.record_integrity_failure(
            content_id=owned.content_id,
            lease_owner=lease_owner,
        )
        content = await session.get(ObjectContents, owned.content_id)
        assert content is not None
        assert content.state == ContentState.FAILED.value
        assert content.reference_count == 1
        assert content.delete_requested_at is None

        hold_id = await repository.apply_hold(
            tenant_id=owned.tenant_id,
            content_id=owned.content_id,
            kind="recovery",
            reason="retain failed bytes while the owner is investigated",
            actor_user_id=owned.user_id,
            expires_at=None,
        )
        assert hold_id is not None


@pytest.mark.asyncio
async def test_concurrent_attach_and_final_detach_preserve_reference_invariant(
    object_content_database: DatabaseSessionManager,
) -> None:
    owned = await _available_content(object_content_database)
    async with object_content_database.session() as session, session.begin():
        second_owner = _file(
            tenant_id=owned.tenant_id,
            user_id=owned.user_id,
            name=f"concurrent-{uuid4().hex}.txt",
        )
        session.add(second_owner)
        await session.flush()
        second_file_id = second_owner.id

    start = asyncio.Event()

    async def attach() -> Exception | None:
        try:
            async with object_content_database.session() as session, session.begin():
                await session.execute(text("SET LOCAL lock_timeout = '5s'"))
                await start.wait()
                session.add(
                    FileContentReferences(
                        file_id=second_file_id,
                        content_id=owned.content_id,
                        variant="original",
                        ordinal=0,
                    )
                )
                await session.flush()
        except Exception as error:
            return error
        return None

    async def detach() -> Exception | None:
        try:
            async with object_content_database.session() as session, session.begin():
                await session.execute(text("SET LOCAL lock_timeout = '5s'"))
                await start.wait()
                await session.execute(
                    delete(FileContentReferences).where(
                        FileContentReferences.file_id == owned.file_id
                    )
                )
        except Exception as error:
            return error
        return None

    attach_task = asyncio.create_task(attach())
    detach_task = asyncio.create_task(detach())
    start.set()
    attach_error, detach_error = await asyncio.gather(attach_task, detach_task)
    assert detach_error is None
    if attach_error is not None:
        assert isinstance(attach_error, DBAPIError)
        assert "cannot be attached" in str(attach_error)

    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, owned.content_id)
        actual_count = await session.scalar(
            select(func.count()).where(
                FileContentReferences.content_id == owned.content_id
            )
        )
        assert content is not None
        assert content.reference_count == actual_count
        if actual_count == 0:
            assert content.state == ContentState.DELETE_PENDING.value
        else:
            assert actual_count == 1
            assert content.state == ContentState.AVAILABLE.value


@pytest.mark.asyncio
async def test_concurrent_hold_and_final_detach_have_one_serialized_winner(
    object_content_database: DatabaseSessionManager,
) -> None:
    owned = await _available_content(object_content_database)
    start = asyncio.Event()

    async def apply_hold() -> Exception | None:
        try:
            async with object_content_database.session() as session, session.begin():
                await session.execute(text("SET LOCAL lock_timeout = '5s'"))
                await start.wait()
                await ObjectContentRepository(session).apply_hold(
                    tenant_id=owned.tenant_id,
                    content_id=owned.content_id,
                    kind="recovery",
                    reason="concurrent recovery fence",
                    actor_user_id=owned.user_id,
                    expires_at=None,
                )
        except Exception as error:
            return error
        return None

    async def detach() -> Exception | None:
        try:
            async with object_content_database.session() as session, session.begin():
                await session.execute(text("SET LOCAL lock_timeout = '5s'"))
                await start.wait()
                await session.execute(
                    delete(FileContentReferences).where(
                        FileContentReferences.file_id == owned.file_id
                    )
                )
        except Exception as error:
            return error
        return None

    hold_task = asyncio.create_task(apply_hold())
    detach_task = asyncio.create_task(detach())
    start.set()
    hold_error, detach_error = await asyncio.gather(hold_task, detach_task)
    assert detach_error is None
    if hold_error is not None:
        assert isinstance(hold_error, DBAPIError)
        assert "hold cannot cross committed delete intent" in str(hold_error)

    async with object_content_database.session() as session, session.begin():
        content = await session.get(ObjectContents, owned.content_id)
        active_holds = await session.scalar(
            select(func.count()).where(
                ObjectContentHolds.content_id == owned.content_id,
                ObjectContentHolds.released_at.is_(None),
            )
        )
        assert content is not None
        assert content.reference_count == 0
        if active_holds:
            assert content.state == ContentState.RETAINED.value
        else:
            assert content.state == ContentState.DELETE_PENDING.value


@pytest.mark.asyncio
async def test_opposite_detach_order_deadlock_rolls_back_and_retry_converges(
    object_content_database: DatabaseSessionManager,
) -> None:
    first = await _available_content(object_content_database)
    second = await _available_content(object_content_database)
    async with object_content_database.session() as session, session.begin():
        session.add_all(
            [
                FileContentReferences(
                    file_id=first.file_id,
                    content_id=second.content_id,
                    variant="preview",
                    ordinal=0,
                ),
                FileContentReferences(
                    file_id=second.file_id,
                    content_id=first.content_id,
                    variant="preview",
                    ordinal=0,
                ),
            ]
        )
        await session.flush()

    first_locked = asyncio.Event()
    second_locked = asyncio.Event()

    async def detach_in_order(
        first_file_id: UUID,
        first_variant: str,
        second_file_id: UUID,
        second_variant: str,
        own_lock: asyncio.Event,
        peer_lock: asyncio.Event,
    ) -> Exception | None:
        try:
            async with object_content_database.session() as session, session.begin():
                await session.execute(text("SET LOCAL deadlock_timeout = '100ms'"))
                await session.execute(text("SET LOCAL lock_timeout = '5s'"))
                await session.execute(
                    delete(FileContentReferences).where(
                        FileContentReferences.file_id == first_file_id,
                        FileContentReferences.variant == first_variant,
                    )
                )
                own_lock.set()
                await asyncio.wait_for(peer_lock.wait(), timeout=5)
                await session.execute(
                    delete(FileContentReferences).where(
                        FileContentReferences.file_id == second_file_id,
                        FileContentReferences.variant == second_variant,
                    )
                )
        except Exception as error:
            return error
        return None

    first_result, second_result = await asyncio.gather(
        detach_in_order(
            first.file_id,
            "original",
            first.file_id,
            "preview",
            first_locked,
            second_locked,
        ),
        detach_in_order(
            second.file_id,
            "original",
            second.file_id,
            "preview",
            second_locked,
            first_locked,
        ),
    )
    errors = tuple(
        error for error in (first_result, second_result) if error is not None
    )
    assert len(errors) == 1
    assert isinstance(errors[0], DBAPIError)
    assert getattr(errors[0].orig, "sqlstate", None) == "40P01"

    # The deadlock loser rolled its complete transaction back. A new
    # authorization-boundary attempt deletes remaining references in stable
    # content order and converges without partial counter changes.
    async with object_content_database.session() as session, session.begin():
        remaining = (
            await session.execute(
                select(
                    FileContentReferences.file_id,
                    FileContentReferences.variant,
                    FileContentReferences.content_id,
                ).order_by(FileContentReferences.content_id)
            )
        ).all()
        for file_id, variant, _content_id in remaining:
            await session.execute(
                delete(FileContentReferences).where(
                    FileContentReferences.file_id == file_id,
                    FileContentReferences.variant == variant,
                )
            )

    async with object_content_database.session() as session, session.begin():
        contents = (
            await session.scalars(
                select(ObjectContents).where(
                    ObjectContents.id.in_((first.content_id, second.content_id))
                )
            )
        ).all()
        reference_count = await session.scalar(
            select(func.count()).select_from(FileContentReferences)
        )
        assert reference_count == 0
        assert {content.reference_count for content in contents} == {0}
        assert {content.state for content in contents} == {
            ContentState.DELETE_PENDING.value
        }
