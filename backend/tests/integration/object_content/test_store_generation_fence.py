"""The connection revision fences every durable remote-intent transaction.

A credential rotation or destination cutover advances the active connection
row's revision under lock. A client leased before that advance must not be
able to make remote work durable afterwards: its reservation, adoption,
move completion, or inventory recording fails typed instead.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContentOrphanCandidates,
    ObjectContents,
    ObjectStoreObjects,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content import (
    ContentState,
    ObjectContentUnavailableError,
    StorageKind,
    capture_content,
)
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.object_store_provider import ObjectStoreProvider
from eneo.object_content.reconciliation import ObjectContentReconciler
from eneo.object_content.s3_object_store import new_object_key
from tests.integration.object_content.conftest import RealObjectStore

pytestmark = pytest.mark.asyncio


async def _advance_connection_revision(
    database: DatabaseSessionManager,
    *,
    revision: int,
) -> None:
    """Persist an active connection row the leased revision no longer matches."""
    async with database.session() as session, session.begin():
        await session.execute(
            text(
                """
                INSERT INTO object_store_connections
                    (id, revision, endpoint_url, region, bucket,
                     access_key_id_encrypted, secret_access_key_encrypted,
                     deployment_id, addressing_style, updated_by_actor)
                VALUES
                    (1, :revision, 'https://rotated.example.test', 'local',
                     'rotated-bucket', 'encrypted-access', 'encrypted-secret',
                     gen_random_uuid(), 'path', 'platform_admin')
                ON CONFLICT (id) DO UPDATE SET revision = :revision
                """
            ),
            {"revision": revision},
        )


async def test_publication_reservation_refused_after_revision_advance(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    """An upload leased before a rotation cannot reserve against the store."""
    service = ObjectContentService(
        ObjectContentCoreSettings(_env_file=None),
        object_content_database,
        object_store_provider=ObjectStoreProvider.fixed(
            real_object_store.settings,
            real_object_store.store,
        ),
    )
    payload = b"fence-me"

    async def chunks() -> AsyncGenerator[bytes]:
        yield payload

    async with service.capture_for_target(
        chunks(),
        storage_kind=StorageKind.OBJECT_STORE,
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
    ) as captured:
        # The lease was captured for the unstored (legacy) generation; a
        # rotation now persists revision 1 before the reservation commits.
        await _advance_connection_revision(object_content_database, revision=1)

        with pytest.raises(ObjectContentUnavailableError):
            async with service.upload_for_publication([captured]):
                raise AssertionError(
                    "publication must not proceed against a rotated store"
                )

    async with object_content_database.session() as session, session.begin():
        reservations = await session.scalar(
            select(func.count()).select_from(ObjectContentOrphanCandidates)
        )
    assert reservations == 0, "no durable reservation may survive the refusal"


async def test_stale_reconciler_run_records_nothing_after_revision_advance(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    """A reconciler leased before a rotation neither promotes nor inventories.

    The run degrades to its already-committed local work instead of raising,
    and the pending item converges under the next lease generation.
    """
    payload = b"stale-reconciler-fence"
    digest = sha256(payload).digest()
    async with object_content_database.session() as session, session.begin():
        tenant_id = (await session.scalars(select(Tenants.id))).one()
        user_id = (await session.scalars(select(Users.id))).one()
        token = uuid4().hex
        owner = Files(
            name=f"{token}.txt",
            mimetype="application/octet-stream",
            file_type="text",
            tenant_id=tenant_id,
            user_id=user_id,
            parent_file_id=None,
        )
        object_key = new_object_key(real_object_store.settings)
        content = ObjectContents(
            tenant_id=tenant_id,
            created_by_user_id=user_id,
            storage_kind=StorageKind.OBJECT_STORE.value,
            state=ContentState.PENDING.value,
            access_class="private_resource",
            sha256=digest,
            size_bytes=len(payload),
            declared_media_type="application/octet-stream",
            verified_media_type="application/octet-stream",
            idempotency_key=token,
            request_fingerprint=digest,
        )
        session.add_all([owner, content])
        await session.flush()
        descriptor = ObjectStoreObjects()
        descriptor.content_id = content.id
        descriptor.storage_kind = StorageKind.OBJECT_STORE.value
        descriptor.object_key = object_key
        descriptor.verification_chunk_size_bytes = len(payload)
        descriptor.verification_chunk_sha256 = digest
        session.add(descriptor)
        session.add(
            FileContentReferences(
                file_id=owner.id,
                content_id=content.id,
                variant="original",
                ordinal=0,
            )
        )
        await session.flush()
        content_id = content.id
    settings = real_object_store.settings
    async with capture_content(
        _chunks(payload),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        maximum_size_bytes=len(payload),
        spool_memory_bytes=settings.spool_memory_bytes,
        multipart_part_bytes=settings.multipart_part_bytes,
    ) as captured:
        await real_object_store.store.upload(object_key, captured)
    async with object_content_database.session() as session, session.begin():
        await session.execute(
            text(
                "UPDATE object_contents "
                "SET updated_at = now() - interval '10 seconds' "
                "WHERE id = :content_id"
            ),
            {"content_id": str(content_id)},
        )

    reconciler = ObjectContentReconciler(
        ObjectContentCoreSettings(_env_file=None),
        object_content_database,
        object_store_provider=ObjectStoreProvider.fixed(
            settings,
            real_object_store.store,
        ),
    )
    await _advance_connection_revision(object_content_database, revision=1)

    result = await reconciler.run_once()

    assert result.content_processed == 0
    assert not result.object_cycle_completed
    async with object_content_database.session() as session, session.begin():
        row = await session.get(ObjectContents, content_id)
        assert row is not None
        assert row.state == ContentState.PENDING.value, (
            "a stale lease must not promote remotely verified content"
        )


async def _chunks(payload: bytes) -> AsyncGenerator[bytes]:
    yield payload


async def test_generation_change_preserves_already_committed_inventory(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rotation mid-run must not erase transitions that already committed.

    Object inventory and missing-content marking commit before the multipart
    phase runs. If the store generation advances in between, the run has to
    report what it durably changed, or operators lose sight of an integrity
    transition that really happened.
    """
    payload = b"committed-inventory"
    digest = sha256(payload).digest()
    async with object_content_database.session() as session, session.begin():
        tenant_id = (await session.scalars(select(Tenants.id))).one()
        user_id = (await session.scalars(select(Users.id))).one()
        token = uuid4().hex
        owner = Files(
            name=f"{token}.txt",
            mimetype="application/octet-stream",
            file_type="text",
            tenant_id=tenant_id,
            user_id=user_id,
            parent_file_id=None,
        )
        content = ObjectContents(
            tenant_id=tenant_id,
            created_by_user_id=user_id,
            storage_kind=StorageKind.OBJECT_STORE.value,
            state=ContentState.AVAILABLE.value,
            access_class="private_resource",
            sha256=digest,
            size_bytes=len(payload),
            declared_media_type="application/octet-stream",
            verified_media_type="application/octet-stream",
            idempotency_key=token,
            request_fingerprint=digest,
            available_at=datetime.now(UTC),
        )
        session.add_all([owner, content])
        await session.flush()
        # A row whose object was never written: a complete inventory must mark
        # it missing.
        descriptor = ObjectStoreObjects()
        descriptor.content_id = content.id
        descriptor.storage_kind = StorageKind.OBJECT_STORE.value
        descriptor.object_key = new_object_key(real_object_store.settings)
        descriptor.verification_chunk_size_bytes = len(payload)
        descriptor.verification_chunk_sha256 = digest
        session.add(descriptor)
        session.add(
            FileContentReferences(
                file_id=owner.id,
                content_id=content.id,
                variant="original",
                ordinal=0,
            )
        )
        await session.flush()
        content.reference_count = 1
        content_id = content.id

    reconciler = ObjectContentReconciler(
        ObjectContentCoreSettings(_env_file=None),
        object_content_database,
        object_store_provider=ObjectStoreProvider.fixed(
            real_object_store.settings,
            real_object_store.store,
        ),
    )

    # One clean run first: missing-marking only considers rows that predate the
    # previous completed cycle.
    first = await reconciler.run_once()
    assert first.object_cycle_completed

    # Now advance the generation once object inventory and missing-marking have
    # committed, before the multipart phase records anything.
    original_multipart = ObjectContentReconciler._reconcile_multipart_page

    async def rotate_then_record(self, store_lease):  # type: ignore[no-untyped-def]
        await _advance_connection_revision(object_content_database, revision=1)
        return await original_multipart(self, store_lease)

    monkeypatch.setattr(
        ObjectContentReconciler, "_reconcile_multipart_page", rotate_then_record
    )

    result = await reconciler.run_once()

    assert result.object_cycle_completed, (
        "a completed inventory cycle must still be reported"
    )
    assert result.missing_objects == 1, (
        "a durable missing-content transition must not be hidden"
    )
    async with object_content_database.session() as session, session.begin():
        row = await session.get(ObjectContents, content_id)
        assert row is not None
        assert row.state == ContentState.FAILED.value
        assert row.failure_code == "backend_missing"
