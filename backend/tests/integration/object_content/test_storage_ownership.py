from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
    ObjectContentAuditEvents,
    ObjectContents,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.object_content.content import StorageKind


async def _owner_ids(database: DatabaseSessionManager) -> tuple[UUID, UUID]:
    async with database.session() as session, session.begin():
        tenant_id = (await session.scalars(select(Tenants.id))).one()
        user_id = (await session.scalars(select(Users.id))).one()
    return tenant_id, user_id


def _file(*, tenant_id: UUID, user_id: UUID, name: str) -> Files:
    return Files(
        name=name,
        mimetype="text/plain",
        file_type="text",
        tenant_id=tenant_id,
        user_id=user_id,
        parent_file_id=None,
    )


def _inline_content(
    *,
    tenant_id: UUID,
    user_id: UUID,
    idempotency_key: str,
    payload: bytes,
) -> ObjectContents:
    digest = sha256(payload).digest()
    return ObjectContents(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        storage_kind=StorageKind.POSTGRES_INLINE.value,
        state="available",
        access_class="private_resource",
        sha256=digest,
        size_bytes=len(payload),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        idempotency_key=idempotency_key,
        request_fingerprint=digest,
        available_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_inline_payload_and_first_reference_commit_atomically(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    payload = b"inline durable content"

    async with object_content_database.session() as session, session.begin():
        owner = _file(
            tenant_id=tenant_id,
            user_id=user_id,
            name="inline-content.txt",
        )
        content = _inline_content(
            tenant_id=tenant_id,
            user_id=user_id,
            idempotency_key="inline-content",
            payload=payload,
        )
        session.add_all([owner, content])
        await session.flush()
        session.add_all(
            [
                InlineContentPayloads(
                    content_id=content.id,
                    storage_kind=StorageKind.POSTGRES_INLINE.value,
                    payload=payload,
                ),
                FileContentReferences(
                    file_id=owner.id,
                    content_id=content.id,
                    variant="original",
                    ordinal=0,
                ),
            ]
        )
        content_id = content.id

    async with object_content_database.session() as session, session.begin():
        stored_content = await session.get(ObjectContents, content_id)
        stored_payload = await session.get(InlineContentPayloads, content_id)
        audit_events = (
            await session.scalars(
                select(ObjectContentAuditEvents.event_type)
                .where(ObjectContentAuditEvents.content_id == content_id)
                .order_by(ObjectContentAuditEvents.created_at)
            )
        ).all()

        assert stored_content is not None
        assert stored_content.reference_count == 1
        assert stored_content.storage_kind == StorageKind.POSTGRES_INLINE.value
        assert stored_payload is not None
        assert stored_payload.payload == payload
        assert sorted(audit_events) == ["available", "prepared", "reference_changed"]


@pytest.mark.asyncio
async def test_non_tombstoned_content_requires_exact_backend_row_at_commit(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)

    with pytest.raises(DBAPIError, match="requires exactly one matching byte backend"):
        async with object_content_database.session() as session, session.begin():
            owner = _file(
                tenant_id=tenant_id,
                user_id=user_id,
                name="missing-inline-payload.txt",
            )
            content = _inline_content(
                tenant_id=tenant_id,
                user_id=user_id,
                idempotency_key="missing-inline-payload",
                payload=b"missing payload row",
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


@pytest.mark.asyncio
async def test_new_inline_content_requires_first_reference_in_same_transaction(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    payload = b"unowned inline payload"

    with pytest.raises(DBAPIError, match="requires an initial owner"):
        async with object_content_database.session() as session, session.begin():
            content = _inline_content(
                tenant_id=tenant_id,
                user_id=user_id,
                idempotency_key="unowned-inline-payload",
                payload=payload,
            )
            session.add(content)
            await session.flush()
            session.add(
                InlineContentPayloads(
                    content_id=content.id,
                    storage_kind=StorageKind.POSTGRES_INLINE.value,
                    payload=payload,
                )
            )


@pytest.mark.asyncio
async def test_new_inline_content_rejects_multiple_initial_references(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    payload = b"one initial owner only"

    with pytest.raises(DBAPIError, match="one first reference"):
        async with object_content_database.session() as session, session.begin():
            owners = [
                _file(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    name=f"inline-owner-{index}.txt",
                )
                for index in range(2)
            ]
            content = _inline_content(
                tenant_id=tenant_id,
                user_id=user_id,
                idempotency_key="multiple-inline-owners",
                payload=payload,
            )
            session.add_all([*owners, content])
            await session.flush()
            session.add(
                InlineContentPayloads(
                    content_id=content.id,
                    storage_kind=StorageKind.POSTGRES_INLINE.value,
                    payload=payload,
                )
            )
            session.add_all(
                [
                    FileContentReferences(
                        file_id=owner.id,
                        content_id=content.id,
                        variant="original",
                        ordinal=index,
                    )
                    for index, owner in enumerate(owners)
                ]
            )
