from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.icons_table import Icons
from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    IconContentReferences,
    InfoBlobContentReferences,
    ObjectContents,
    ObjectStoreObjects,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.object_content.content import (
    CapturedContent,
    ContentAccessClass,
    ContentIntent,
    ObjectContentIdempotencyConflictError,
    StorageKind,
    content_request_fingerprint,
)
from eneo.object_content.content_repository import ObjectContentRepository


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


def _pending_content(
    *,
    tenant_id: UUID,
    user_id: UUID,
    idempotency_key: str,
    access_class: str = "private_resource",
) -> ObjectContents:
    digest = sha256(idempotency_key.encode()).digest()
    return ObjectContents(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        storage_kind=StorageKind.OBJECT_STORE.value,
        state="pending",
        access_class=access_class,
        sha256=digest,
        size_bytes=1,
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        idempotency_key=idempotency_key,
        request_fingerprint=digest,
    )


def _descriptor(content_id: UUID, key_suffix: str) -> ObjectStoreObjects:
    descriptor = ObjectStoreObjects()
    descriptor.content_id = content_id
    descriptor.storage_kind = StorageKind.OBJECT_STORE.value
    descriptor.object_key = f"v1/a2d539affef042aaa7f814376947be2c/{key_suffix}"
    descriptor.verification_chunk_size_bytes = 1
    descriptor.verification_chunk_sha256 = sha256(key_suffix.encode()).digest()
    return descriptor


def _captured_content(payload: bytes = b"x") -> CapturedContent:
    digest = sha256(payload).digest()
    return CapturedContent(
        file=BytesIO(payload),
        sha256=digest,
        size_bytes=len(payload),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        part_sha256=(digest,),
        part_size_bytes=max(1, len(payload)),
    )


@pytest.mark.asyncio
async def test_pending_content_accepts_its_first_reference_in_creation_transaction(
    object_content_database: DatabaseSessionManager,
) -> None:
    async with object_content_database.session() as session, session.begin():
        server_version = (
            await session.execute(text("SHOW server_version_num"))
        ).scalar_one()
    assert int(server_version) // 10_000 == 13

    tenant_id, user_id = await _owner_ids(object_content_database)

    async with object_content_database.session() as session, session.begin():
        first_file = _file(tenant_id=tenant_id, user_id=user_id, name="first.txt")
        initial_content = _pending_content(
            tenant_id=tenant_id,
            user_id=user_id,
            idempotency_key="initial-content",
        )
        session.add_all([first_file, initial_content])
        await session.flush()
        session.add(_descriptor(initial_content.id, "initial-content"))
        session.add(
            FileContentReferences(
                file_id=first_file.id,
                content_id=initial_content.id,
                variant="original",
                ordinal=0,
            )
        )
        await session.flush()
        await session.refresh(initial_content)
        assert initial_content.reference_count == 1


@pytest.mark.asyncio
async def test_verified_object_content_accepts_first_reference_at_publication(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    content = _captured_content(b"verified-before-publication")
    intent = ContentIntent(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        access_class=ContentAccessClass.PRIVATE_RESOURCE,
        idempotency_key="verified-before-publication",
        producer_receipt="file:verified-before-publication:original:0",
    )

    async with object_content_database.session() as session, session.begin():
        owner = _file(
            tenant_id=tenant_id,
            user_id=user_id,
            name="verified-before-publication.txt",
        )
        session.add(owner)
        await session.flush()
        prepared = await ObjectContentRepository(session).prepare_verified_object_store(
            intent=intent,
            content=content,
            object_key=f"v1/a2d539affef042aaa7f814376947be2c/{uuid4().hex}",
            request_fingerprint=content_request_fingerprint(
                intent,
                content,
                StorageKind.OBJECT_STORE,
            ),
        )
        session.add(
            FileContentReferences(
                file_id=owner.id,
                content_id=prepared.id,
                variant="original",
                ordinal=0,
            )
        )
        await session.flush()
        row = await session.get(ObjectContents, prepared.id)
        assert row is not None
        assert row.state == "available"
        assert row.reference_count == 1


@pytest.mark.asyncio
async def test_verified_object_content_without_product_owner_cannot_commit(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    content = _captured_content(b"ownerless-verified-object")
    intent = ContentIntent(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        access_class=ContentAccessClass.PRIVATE_RESOURCE,
        idempotency_key="ownerless-verified-object",
        producer_receipt="file:ownerless-verified-object:original:0",
    )

    with pytest.raises(DBAPIError, match="requires an initial owner"):
        async with object_content_database.session() as session, session.begin():
            await ObjectContentRepository(session).prepare_verified_object_store(
                intent=intent,
                content=content,
                object_key=f"v1/a2d539affef042aaa7f814376947be2c/{uuid4().hex}",
                request_fingerprint=content_request_fingerprint(
                    intent,
                    content,
                    StorageKind.OBJECT_STORE,
                ),
            )


@pytest.mark.asyncio
async def test_info_blob_pending_content_accepts_its_first_reference_at_creation(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)

    async with object_content_database.session() as session, session.begin():
        owner = InfoBlobs(
            text="",
            title="owned extracted text",
            url=None,
            size=0,
            content_hash=sha256(b"").digest(),
            source_id=uuid4(),
            version_state=InfoBlobVersionState.ACTIVE.value,
            user_id=user_id,
            tenant_id=tenant_id,
            group_id=None,
            website_id=None,
            embedding_model_id=None,
            integration_knowledge_id=None,
            sharepoint_item_id=None,
        )
        content = _pending_content(
            tenant_id=tenant_id,
            user_id=user_id,
            idempotency_key="info-blob-owned-content",
        )
        session.add_all([owner, content])
        await session.flush()
        session.add(_descriptor(content.id, "info-blob-owned-content"))
        session.add(
            InfoBlobContentReferences(
                info_blob_id=owner.id,
                content_id=content.id,
                original_filename="owned-original.txt",
            )
        )


@pytest.mark.asyncio
async def test_icon_pending_content_accepts_its_first_reference_at_creation(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)

    async with object_content_database.session() as session, session.begin():
        owner = Icons(
            tenant_id=tenant_id,
        )
        content = _pending_content(
            tenant_id=tenant_id,
            user_id=user_id,
            idempotency_key="icon-owned-content",
            access_class="public_immutable",
        )
        session.add_all([owner, content])
        await session.flush()
        session.add(_descriptor(content.id, "icon-owned-content"))
        session.add(
            IconContentReferences(
                icon_id=owner.id,
                content_id=content.id,
                variant="primary",
            )
        )


@pytest.mark.asyncio
async def test_ownerless_pending_content_cannot_commit(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)

    with pytest.raises(DBAPIError, match="requires an initial owner"):
        async with object_content_database.session() as session, session.begin():
            content = _pending_content(
                tenant_id=tenant_id,
                user_id=user_id,
                idempotency_key="ownerless-content",
            )
            session.add(content)
            await session.flush()
            session.add(_descriptor(content.id, "ownerless-content"))


@pytest.mark.asyncio
async def test_prepare_is_idempotent_and_rejects_fingerprint_substitution(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    content = _captured_content(b"same content")
    intent = ContentIntent(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        access_class=ContentAccessClass.PRIVATE_RESOURCE,
        idempotency_key="repository-idempotency",
        producer_receipt="file:repository-idempotency:original:0",
    )
    fingerprint = content_request_fingerprint(
        intent,
        content,
        StorageKind.OBJECT_STORE,
    )

    async with object_content_database.session() as session, session.begin():
        owner = _file(
            tenant_id=tenant_id,
            user_id=user_id,
            name="repository-idempotency.txt",
        )
        session.add(owner)
        await session.flush()
        prepared = await ObjectContentRepository(session).prepare_object_store(
            intent=intent,
            content=content,
            object_key=f"v1/a2d539affef042aaa7f814376947be2c/{uuid4().hex}",
            request_fingerprint=fingerprint,
        )
        session.add(
            FileContentReferences(
                file_id=owner.id,
                content_id=prepared.id,
                variant="original",
                ordinal=0,
            )
        )
        await session.flush()
        assert prepared.created is True

    async with object_content_database.session() as session, session.begin():
        replay = await ObjectContentRepository(session).prepare_object_store(
            intent=intent,
            content=content,
            object_key=f"v1/a2d539affef042aaa7f814376947be2c/{uuid4().hex}",
            request_fingerprint=fingerprint,
        )
        assert replay.created is False
        assert replay.id == prepared.id
        assert replay.storage_kind is StorageKind.OBJECT_STORE

    changed_intent = replace(intent, producer_receipt="file:other:original:0")
    with pytest.raises(ObjectContentIdempotencyConflictError):
        async with object_content_database.session() as session, session.begin():
            await ObjectContentRepository(session).prepare_object_store(
                intent=changed_intent,
                content=content,
                object_key=f"v1/a2d539affef042aaa7f814376947be2c/{uuid4().hex}",
                request_fingerprint=content_request_fingerprint(
                    changed_intent,
                    content,
                    StorageKind.OBJECT_STORE,
                ),
            )
