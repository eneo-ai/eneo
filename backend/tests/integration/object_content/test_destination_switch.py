"""The guarded destination switch: probed, fenced, reversible.

The operator copies the content namespace (`v1/<deployment-id>/`) to the new
bucket with an external tool; Eneo owns everything safety-critical around it:
preconditions that no write can be in flight, a probe of the new destination,
marker admission that refuses a bucket paired with another installation, one
fenced transaction that archives the previous destination for switch-back,
and the existing read/inventory verification afterwards.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select, text

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.object_store_connection_table import (
    TEMPORARY_DESTINATION_SLOT,
    ObjectStoreConnections,
)
from eneo.object_content.configuration import (
    ObjectContentCoreSettings,
    ObjectStoreOperatorSettings,
)
from eneo.object_content.content import StorageKind
from eneo.object_content.object_store_connection import (
    ObjectStoreConnectionConflict,
    ObjectStoreConnectionError,
    ObjectStoreConnectionInput,
    ObjectStoreConnectionService,
    ObjectStoreDestinationCopyIncomplete,
    ObjectStoreMovesNotPaused,
    ObjectStoreNewWritesNotRedirected,
    ObjectStorePreviousDestinationPresent,
    ObjectStoreSwitchBackDiverged,
)
from eneo.object_content.s3_object_store import (
    ObjectStoreUnavailableError,
    S3ObjectStore,
)
from eneo.object_content.store_binding import ensure_store_binding_ready
from eneo.settings.encryption_service import EncryptionService
from tests.integration.object_content.conftest import RealObjectStore

pytestmark = pytest.mark.asyncio


def _service(
    database: DatabaseSessionManager,
    source: RealObjectStore,
) -> ObjectStoreConnectionService:
    settings = source.settings
    core = ObjectContentCoreSettings.model_validate(
        {
            name: getattr(settings, name)
            for name in ObjectContentCoreSettings.model_fields
        }
    )
    operator = ObjectStoreOperatorSettings.model_validate(
        {
            name: getattr(settings, name)
            for name in ObjectStoreOperatorSettings.model_fields
        }
    )
    return ObjectStoreConnectionService(
        database=database,
        core_settings=core,
        operator_settings=operator,
        encryption=EncryptionService(Fernet.generate_key().decode()),
    )


def _connection_input(store: RealObjectStore) -> ObjectStoreConnectionInput:
    return ObjectStoreConnectionInput(
        endpoint_url=store.settings.endpoint_url,
        region=store.settings.region,
        bucket=store.settings.bucket,
        access_key_id=SecretStr(store.settings.access_key_id.get_secret_value()),
        secret_access_key=SecretStr(
            store.settings.secret_access_key.get_secret_value()
        ),
        addressing_style=store.settings.addressing_style,
    )


@pytest.fixture(autouse=True)
async def _restore_write_target(
    object_content_database: DatabaseSessionManager,
) -> AsyncGenerator[None]:
    """Keep the shared deployment policy out of these tests' blast radius.

    The object-content fixture truncates the control plane but deliberately
    keeps the singleton policy row, so a switch test that redirects new
    writes must put the target back for the rest of the suite.
    """
    async with object_content_database.session() as session, session.begin():
        original = (
            await session.execute(
                text(
                    "SELECT new_write_storage_target, moves_paused, revision "
                    "FROM object_content_deployment_policy WHERE id = 1"
                )
            )
        ).one()
    yield
    # Restore the row exactly as found, revision included: a bumped revision
    # would make another test's expected_revision stale.
    async with object_content_database.session() as session, session.begin():
        await session.execute(
            text(
                "UPDATE object_content_deployment_policy "
                "SET new_write_storage_target = :target, "
                "moves_paused = :paused, revision = :revision "
                "WHERE id = 1"
            ),
            {"target": original[0], "paused": original[1], "revision": original[2]},
        )


async def _select_inline_writes(database: DatabaseSessionManager) -> None:
    """Apply the documented switch preparation: redirect writes, pause moves."""
    async with database.session() as session, session.begin():
        await session.execute(
            text(
                "UPDATE object_content_deployment_policy "
                "SET new_write_storage_target = 'postgres_inline', "
                "moves_paused = true, "
                "revision = revision + 1 WHERE id = 1"
            )
        )


async def _select_object_store_writes(database: DatabaseSessionManager) -> None:
    async with database.session() as session, session.begin():
        await session.execute(
            text(
                "UPDATE object_content_deployment_policy "
                "SET new_write_storage_target = 'object_store', "
                "revision = revision + 1 WHERE id = 1"
            )
        )


async def test_switch_requires_inline_new_writes(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
) -> None:
    """New writes on object storage refuse the switch with an actionable code.

    This is the administrator's most likely first attempt, and it is a
    configuration they must change rather than transient work to wait out,
    so it carries its own typed reason.
    """
    service = _service(object_content_database, real_object_store)
    stored = await service.create(
        _connection_input(real_object_store),
        actor_user_id=await _any_user_id(object_content_database),
    )
    assert stored.revision == 1
    await ensure_store_binding_ready(
        object_content_database,
        service.settings_for(stored),
        real_object_store.store,
    )
    await _select_object_store_writes(object_content_database)

    with pytest.raises(ObjectStoreNewWritesNotRedirected):
        await service.replace_destination(
            _connection_input(real_unpaired_object_store),
            actor_user_id=await _any_user_id(object_content_database),
        )


async def test_switch_serves_copied_content_and_switches_back(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
) -> None:
    """A copied bucket becomes active atomically and remains reversible."""
    service = _service(object_content_database, real_object_store)
    actor = await _any_user_id(object_content_database)
    created = await service.create(
        _connection_input(real_object_store), actor_user_id=actor
    )
    await ensure_store_binding_ready(
        object_content_database,
        service.settings_for(created),
        real_object_store.store,
    )
    await _select_inline_writes(object_content_database)

    # Seed one remote object inside the connection's own deployment
    # namespace, then "operator-copy" that content prefix to the new bucket
    # byte for byte, exactly as the documented rclone recipe does.
    source_settings = service.settings_for(created)
    source_store = S3ObjectStore(source_settings)
    payload = b"switch-me-safely"
    try:
        object_key = await _seed_remote_content(
            object_content_database, source_settings, source_store, payload
        )
    finally:
        await source_store.close()
    await _copy_object(
        real_unpaired_object_store,
        object_key,
        payload,
        deployment_id=created.deployment_id,
    )

    # Give the reconciler a completed-inventory fact from the old bucket, so
    # the switch can prove it does not carry over to the new destination.
    async with object_content_database.session() as session, session.begin():
        await session.execute(
            text(
                "UPDATE object_content_reconciliation_state "
                "SET last_completed_object_cycle_started_at = now(), "
                "last_object_cycle_completed_at = now() WHERE id = 1"
            )
        )

    switch = await service.replace_destination(
        _connection_input(real_unpaired_object_store),
        actor_user_id=actor,
    )
    switched = switch.active

    # The old bucket's completed-inventory facts do not describe the new
    # destination: missing-marking and health wait for its own first cycle.
    async with object_content_database.session() as session, session.begin():
        cycle_facts = (
            await session.execute(
                text(
                    "SELECT last_completed_object_cycle_started_at, "
                    "last_object_cycle_completed_at "
                    "FROM object_content_reconciliation_state WHERE id = 1"
                )
            )
        ).one()
    assert cycle_facts == (None, None)
    assert switched.bucket == real_unpaired_object_store.settings.bucket
    assert switched.revision == 2
    # The mutation carries both projections, so a caller never has to read the
    # archived row again after the switch has already committed.
    assert switch.previous.bucket == real_object_store.settings.bucket
    # The deployment identity carries over, so every stored object key stays
    # valid and no content row is touched by the switch.
    assert switched.deployment_id == created.deployment_id

    async with object_content_database.session() as session, session.begin():
        previous = await session.get(ObjectStoreConnections, TEMPORARY_DESTINATION_SLOT)
        assert previous is not None
        assert previous.role == "retiring"
        assert previous.bucket == real_object_store.settings.bucket

    # The admin surface reads the archived destination through the service,
    # so that path must work as soon as a switch has happened.
    archived = await service.get_previous()
    assert archived is not None
    assert archived.bucket == real_object_store.settings.bucket

    # The copied object is readable and digest-verified through the new
    # destination's own client.
    new_store = S3ObjectStore(service.settings_for(switched))
    try:
        digest = await new_store.recompute_sha256(
            object_key,
            expected_size_bytes=len(payload),
            expected_media_type="application/octet-stream",
        )
        from hashlib import sha256

        assert digest == sha256(payload).digest()
    finally:
        await new_store.close()

    # Switch back to the archived destination, reusing its stored credentials.
    restored = await service.switch_back(actor_user_id=actor)
    assert restored.active.bucket == real_object_store.settings.bucket
    assert restored.active.revision == 3
    assert restored.previous.bucket == real_unpaired_object_store.settings.bucket


async def _any_user_id(database: DatabaseSessionManager):
    from eneo.database.tables.users_table import Users

    async with database.session() as session, session.begin():
        return (await session.scalars(select(Users.id))).one()


async def _seed_remote_content(
    database: DatabaseSessionManager,
    settings,
    store: S3ObjectStore,
    payload: bytes,
) -> str:
    from hashlib import sha256

    from eneo.database.tables.files_table import Files
    from eneo.database.tables.object_content_table import (
        FileContentReferences,
        ObjectContents,
        ObjectStoreObjects,
    )
    from eneo.database.tables.tenant_table import Tenants
    from eneo.database.tables.users_table import Users
    from eneo.object_content.content import ContentState, capture_content
    from eneo.object_content.s3_object_store import new_object_key

    digest = sha256(payload).digest()
    async with database.session() as session, session.begin():
        tenant_id = (await session.scalars(select(Tenants.id))).one()
        user_id = (await session.scalars(select(Users.id))).one()
        token = uuid4().hex
        owner = Files(
            name=f"{token}.bin",
            mimetype="application/octet-stream",
            file_type="text",
            tenant_id=tenant_id,
            user_id=user_id,
            parent_file_id=None,
        )
        object_key = new_object_key(settings)
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
        session.add(content)
        content.reference_count = 1

    async with capture_content(
        _chunks(payload),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        maximum_size_bytes=len(payload),
        spool_memory_bytes=settings.spool_memory_bytes,
        multipart_part_bytes=settings.multipart_part_bytes,
    ) as captured:
        await store.upload(object_key, captured)
    return object_key


async def _copy_object(
    target: RealObjectStore,
    object_key: str,
    payload: bytes,
    *,
    deployment_id,
) -> None:
    """Byte-for-byte operator copy of one content-namespace object."""
    from eneo.object_content.content import capture_content

    write_settings = target.settings.model_copy(update={"deployment_id": deployment_id})
    write_store = S3ObjectStore(write_settings)
    try:
        async with capture_content(
            _chunks(payload),
            declared_media_type="application/octet-stream",
            verified_media_type="application/octet-stream",
            maximum_size_bytes=len(payload),
            spool_memory_bytes=write_settings.spool_memory_bytes,
            multipart_part_bytes=write_settings.multipart_part_bytes,
        ) as captured:
            await write_store.upload(object_key, captured)
    finally:
        await write_store.close()


async def _chunks(payload: bytes) -> AsyncGenerator[bytes]:
    yield payload


async def test_rejected_switch_leaves_no_binding_marker_on_the_target(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A target that fails the data probe must not stay paired to us.

    Credentials can be able to write the small marker and list the prefix
    while still failing a content upload. Claiming the bucket before that is
    proven would leave another Eneo installation unable to adopt it.
    """
    service = _service(object_content_database, real_object_store)
    actor = await _any_user_id(object_content_database)
    created = await service.create(
        _connection_input(real_object_store), actor_user_id=actor
    )
    await ensure_store_binding_ready(
        object_content_database,
        service.settings_for(created),
        real_object_store.store,
    )
    await _select_inline_writes(object_content_database)

    original_upload = S3ObjectStore.upload

    async def refuse_content_upload(self, key, content, **kwargs):  # type: ignore[no-untyped-def]
        if self._settings.bucket == real_unpaired_object_store.settings.bucket:
            raise ObjectStoreUnavailableError("injected content upload refusal")
        return await original_upload(self, key, content, **kwargs)

    monkeypatch.setattr(S3ObjectStore, "upload", refuse_content_upload)

    with pytest.raises(ObjectStoreConnectionError):
        await service.replace_destination(
            _connection_input(real_unpaired_object_store),
            actor_user_id=actor,
        )

    monkeypatch.undo()

    # No durable claim on the rejected target, and no database change.
    target = S3ObjectStore(
        real_unpaired_object_store.settings.model_copy(
            update={"deployment_id": created.deployment_id}
        )
    )
    try:
        assert not await target.verify_binding(
            (await _binding_id(object_content_database))
        )
    finally:
        await target.close()

    async with object_content_database.session() as session, session.begin():
        rows = (
            await session.execute(
                select(ObjectStoreConnections.id, ObjectStoreConnections.bucket)
            )
        ).all()
    assert [(row[0], row[1]) for row in rows] == [
        (1, real_object_store.settings.bucket)
    ]


async def _binding_id(database: DatabaseSessionManager):
    from eneo.object_content.store_binding import StoreBindingRepository

    async with database.session() as session, session.begin():
        snapshot = await StoreBindingRepository(session).snapshot()
    assert snapshot.binding_id is not None
    return snapshot.binding_id


async def test_rejected_switch_unclaims_the_target(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A definitively rejected switch removes its own marker and claim.

    Writing the pairing marker is durable. If the swap afterwards loses a
    revision race, the target bucket must not stay paired to this
    installation: the marker is verified and removed again, and the temporary
    binding slot is cleared, so a different bucket can be attempted next
    without leaving this one unusable by anyone.
    """
    service = _service(object_content_database, real_object_store)
    actor = await _any_user_id(object_content_database)
    created = await service.create(
        _connection_input(real_object_store), actor_user_id=actor
    )
    await ensure_store_binding_ready(
        object_content_database,
        service.settings_for(created),
        real_object_store.store,
    )
    await _select_inline_writes(object_content_database)
    binding_id = await _binding_id(object_content_database)

    original_create = S3ObjectStore.create_binding

    async def rotate_after_marker(self, creation):  # type: ignore[no-untyped-def]
        await original_create(self, creation)
        # A credential rotation lands between the marker and the swap.
        async with object_content_database.session() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE object_store_connections SET revision = revision + 1 "
                    "WHERE id = 1"
                )
            )

    monkeypatch.setattr(S3ObjectStore, "create_binding", rotate_after_marker)

    with pytest.raises(ObjectStoreConnectionConflict):
        await service.replace_destination(
            _connection_input(real_unpaired_object_store),
            actor_user_id=actor,
        )
    monkeypatch.undo()

    target = S3ObjectStore(
        real_unpaired_object_store.settings.model_copy(
            update={"deployment_id": created.deployment_id}
        )
    )
    try:
        assert not await target.verify_binding(binding_id)
    finally:
        await target.close()

    async with object_content_database.session() as session, session.begin():
        claim = (
            await session.execute(
                text("SELECT slot FROM object_store_bindings WHERE slot = 2")
            )
        ).one_or_none()
    assert claim is None, "an unclaimed target must leave no switch claim behind"


async def test_switch_refuses_a_target_missing_stored_objects(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
) -> None:
    """The candidate must already hold every object the deployment serves.

    Eneo never sees the operator's copy, so it proves the result instead of
    trusting timing. This is also the check that catches the copy that ran
    against the wrong prefix and quietly moved nothing.
    """
    service = _service(object_content_database, real_object_store)
    actor = await _any_user_id(object_content_database)
    created = await service.create(
        _connection_input(real_object_store), actor_user_id=actor
    )
    await ensure_store_binding_ready(
        object_content_database,
        service.settings_for(created),
        real_object_store.store,
    )
    await _select_inline_writes(object_content_database)

    # Content exists on the source and was never copied across.
    source_settings = service.settings_for(created)
    source_store = S3ObjectStore(source_settings)
    try:
        await _seed_remote_content(
            object_content_database, source_settings, source_store, b"never-copied"
        )
    finally:
        await source_store.close()

    with pytest.raises(ObjectStoreDestinationCopyIncomplete):
        await service.replace_destination(
            _connection_input(real_unpaired_object_store),
            actor_user_id=actor,
        )


async def test_switch_refuses_while_a_previous_destination_is_archived(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
) -> None:
    """Giving up the way back is a deliberate act, not a side effect.

    The temporary slot records the destination being claimed, and a second
    switch would overwrite the archived record that Switch back depends on.
    """
    service = _service(object_content_database, real_object_store)
    actor = await _any_user_id(object_content_database)
    created = await service.create(
        _connection_input(real_object_store), actor_user_id=actor
    )
    await ensure_store_binding_ready(
        object_content_database,
        service.settings_for(created),
        real_object_store.store,
    )
    await _select_inline_writes(object_content_database)
    await service.replace_destination(
        _connection_input(real_unpaired_object_store),
        actor_user_id=actor,
    )

    with pytest.raises(ObjectStorePreviousDestinationPresent):
        await service.replace_destination(
            _connection_input(real_object_store),
            actor_user_id=actor,
        )

    # Forgetting the archive releases the slot and the switch proceeds.
    await service.forget_previous_destination(actor_user_id=actor)
    restored = await service.replace_destination(
        _connection_input(real_object_store),
        actor_user_id=actor,
    )
    assert restored.active.bucket == real_object_store.settings.bucket


async def test_interrupted_switch_keeps_the_claimed_destination_recoverable(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    real_spare_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A process loss after the marker leaves the touched bucket identified.

    Without the candidate record, the only trace of the claimed bucket is a
    marker no one can find, and the next switch to another destination would
    strand it. The record lets that switch hand the bucket back first.
    """
    service = _service(object_content_database, real_object_store)
    actor = await _any_user_id(object_content_database)
    created = await service.create(
        _connection_input(real_object_store), actor_user_id=actor
    )
    await ensure_store_binding_ready(
        object_content_database,
        service.settings_for(created),
        real_object_store.store,
    )
    await _select_inline_writes(object_content_database)
    binding_id = await _binding_id(object_content_database)

    class SimulatedProcessLoss(BaseException):
        pass

    original_create = S3ObjectStore.create_binding

    async def lose_process_after_marker(self, creation):  # type: ignore[no-untyped-def]
        await original_create(self, creation)
        raise SimulatedProcessLoss("the worker died before the swap committed")

    monkeypatch.setattr(S3ObjectStore, "create_binding", lose_process_after_marker)
    with pytest.raises(SimulatedProcessLoss):
        await service.replace_destination(
            _connection_input(real_unpaired_object_store),
            actor_user_id=actor,
        )
    monkeypatch.undo()

    # The claimed bucket is identified, and is not offered as a way back.
    async with object_content_database.session() as session, session.begin():
        candidate = await session.get(
            ObjectStoreConnections, TEMPORARY_DESTINATION_SLOT
        )
        assert candidate is not None
        assert candidate.role == "candidate"
        assert candidate.bucket == real_unpaired_object_store.settings.bucket
    assert await service.get_previous() is None

    target = S3ObjectStore(
        real_unpaired_object_store.settings.model_copy(
            update={"deployment_id": created.deployment_id}
        )
    )
    try:
        assert await target.verify_binding(binding_id)
    finally:
        await target.close()

    # Switching somewhere else hands the stranded bucket back first, so it
    # does not stay paired to an installation that never adopted it.
    switched = await service.replace_destination(
        _connection_input(real_spare_object_store),
        actor_user_id=actor,
    )
    assert switched.active.bucket == real_spare_object_store.settings.bucket

    released = S3ObjectStore(
        real_unpaired_object_store.settings.model_copy(
            update={"deployment_id": created.deployment_id}
        )
    )
    try:
        assert not await released.verify_binding(binding_id)
    finally:
        await released.close()


async def test_switch_requires_paused_moves(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
) -> None:
    """Running moves could write to the old bucket mid-copy, so pause first.

    Redirecting new writes fences publications, but a queued inline-to-object
    move would still create a new object on the active destination after the
    operator's copy. The pause is what makes the preconditions hold for the
    whole copy window rather than at one instant.
    """
    service = _service(object_content_database, real_object_store)
    actor = await _any_user_id(object_content_database)
    created = await service.create(
        _connection_input(real_object_store), actor_user_id=actor
    )
    await ensure_store_binding_ready(
        object_content_database,
        service.settings_for(created),
        real_object_store.store,
    )
    async with object_content_database.session() as session, session.begin():
        await session.execute(
            text(
                "UPDATE object_content_deployment_policy "
                "SET new_write_storage_target = 'postgres_inline', "
                "moves_paused = false, revision = revision + 1 WHERE id = 1"
            )
        )

    with pytest.raises(ObjectStoreMovesNotPaused):
        await service.replace_destination(
            _connection_input(real_unpaired_object_store),
            actor_user_id=actor,
        )


async def test_switch_back_is_refused_after_remote_content_diverged(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
) -> None:
    """Objects stored after the switch make blind switch-back unsafe.

    Every remote key created after the destinations were swapped exists only
    on the current destination, so restoring the archived bucket would make
    that content unreadable. The way back is a fresh reverse copy through the
    normal change-destination flow.
    """
    service = _service(object_content_database, real_object_store)
    actor = await _any_user_id(object_content_database)
    created = await service.create(
        _connection_input(real_object_store), actor_user_id=actor
    )
    await ensure_store_binding_ready(
        object_content_database,
        service.settings_for(created),
        real_object_store.store,
    )
    await _select_inline_writes(object_content_database)

    switch = await service.replace_destination(
        _connection_input(real_unpaired_object_store),
        actor_user_id=actor,
    )

    # Content becomes remote on the new destination after the cutover — the
    # exact state a one-click switch-back can no longer serve.
    new_settings = service.settings_for(switch.active)
    new_store = S3ObjectStore(new_settings)
    try:
        await _seed_remote_content(
            object_content_database, new_settings, new_store, b"post-switch-object"
        )
    finally:
        await new_store.close()

    with pytest.raises(ObjectStoreSwitchBackDiverged):
        await service.switch_back(actor_user_id=actor)


async def test_switch_back_loses_to_a_concurrent_remove(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remove and switch-back cannot both report success.

    An operator who saw Remove succeed may decommission the endpoint, so a
    switch-back that was in flight during the removal must fail with a typed
    conflict instead of silently reactivating the removed destination.
    """
    service = _service(object_content_database, real_object_store)
    actor = await _any_user_id(object_content_database)
    created = await service.create(
        _connection_input(real_object_store), actor_user_id=actor
    )
    await ensure_store_binding_ready(
        object_content_database,
        service.settings_for(created),
        real_object_store.store,
    )
    await _select_inline_writes(object_content_database)

    switch = await service.replace_destination(
        _connection_input(real_unpaired_object_store),
        actor_user_id=actor,
    )

    # The archived destination is removed while switch-back is still probing
    # the old bucket, after it has already read the archived row.
    original_probe = ObjectStoreConnectionService._probe

    async def forget_during_probe(self, settings, *, binding):  # type: ignore[no-untyped-def]
        await service.forget_previous_destination(actor_user_id=actor)
        return await original_probe(self, settings, binding=binding)

    monkeypatch.setattr(ObjectStoreConnectionService, "_probe", forget_during_probe)

    with pytest.raises(ObjectStoreConnectionConflict):
        await service.switch_back(actor_user_id=actor)
    monkeypatch.undo()

    # Only the removal succeeded: the active destination is unchanged and the
    # archived slot stays gone.
    async with object_content_database.session() as session, session.begin():
        rows = (
            await session.execute(
                select(ObjectStoreConnections.id, ObjectStoreConnections.bucket)
            )
        ).all()
    assert [(row[0], row[1]) for row in rows] == [(1, switch.active.bucket)]
