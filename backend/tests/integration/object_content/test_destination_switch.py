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
    ObjectStoreConnectionInvalid,
    ObjectStoreConnectionService,
    ObjectStoreDestinationAlreadyBound,
    ObjectStoreDestinationCopyIncomplete,
    ObjectStoreDestinationSwitchBlocked,
    ObjectStoreMovesNotPaused,
    ObjectStoreNewWritesNotRedirected,
    ObjectStorePolicyChangedDuringSwitch,
    ObjectStorePreviousDestinationPresent,
    ObjectStoreProbeBindingMismatch,
    ObjectStoreSwitchBackDiverged,
)
from eneo.object_content.s3_object_store import (
    ObjectStoreBindingError,
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
    # A switch spends two generations: one retires the work running against
    # the source before it is counted, one commits the swap.
    assert switched.revision == 3
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
    restored = await service.switch_back(
        actor_user_id=actor,
        expected_previous_revision=switch.previous.revision,
    )
    assert restored.active.bucket == real_object_store.settings.bucket
    assert restored.active.revision == 5
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


async def test_self_rejected_switch_unclaims_the_target(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A switch that rejects itself removes its own marker and claim.

    Writing the pairing marker is durable. When the switch afterwards refuses
    for a reason it observed alone — here the copy proving incomplete — no
    other actor can own the marker, so it is verified and removed again and
    the temporary slot is cleared, leaving the bucket usable by anyone.
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

    # Content exists on the source and is never copied, so the switch admits
    # the target, writes the marker, and then rejects its own verification.
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


async def test_conflicted_switch_leaves_the_marker_for_the_competing_actor(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Losing a revision race must not remove a marker another actor may own.

    A revision conflict means a rotation or competing switch advanced the
    connection — and a same-target competitor may be about to activate the
    very bucket this attempt marked. The loser therefore keeps its hands off
    the marker; the recorded candidate keeps the bucket recoverable, and a
    later switch elsewhere hands it back.
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
        assert await target.verify_binding(binding_id)
    finally:
        await target.close()

    async with object_content_database.session() as session, session.begin():
        candidate = await session.get(
            ObjectStoreConnections, TEMPORARY_DESTINATION_SLOT
        )
        assert candidate is not None
        assert candidate.role == "candidate"
        assert candidate.bucket == real_unpaired_object_store.settings.bucket
    assert await service.get_previous() is None


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


@pytest.mark.parametrize(
    ("copied_payload", "copied_media_type"),
    [
        (b"truncated", "application/octet-stream"),
        (b"copy-me-exactly", "text/plain"),
    ],
    ids=["wrong-length", "wrong-media-type"],
)
async def test_switch_refuses_a_copy_with_mismatched_object_metadata(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    copied_payload: bytes,
    copied_media_type: str,
) -> None:
    """A key with the wrong length or media type is not a completed copy.

    Every read verifies these two header facts against the canonical row
    before touching bytes, so a truncated copy or one that lost its
    Content-Type would pass an existence check and then fail every read on
    the activated destination. Byte equality stays the operator's
    ``rclone check --download`` step, re-verified per read by SHA-256.
    """
    from eneo.object_content.content import capture_content

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

    source_settings = service.settings_for(created)
    source_store = S3ObjectStore(source_settings)
    try:
        object_key = await _seed_remote_content(
            object_content_database,
            source_settings,
            source_store,
            b"copy-me-exactly",
        )
    finally:
        await source_store.close()

    # The "copy" places an object at the right key whose length or media
    # type differs from what reads verify.
    write_settings = real_unpaired_object_store.settings.model_copy(
        update={"deployment_id": created.deployment_id}
    )
    write_store = S3ObjectStore(write_settings)
    try:
        async with capture_content(
            _chunks(copied_payload),
            declared_media_type=copied_media_type,
            verified_media_type=copied_media_type,
            maximum_size_bytes=len(copied_payload),
            spool_memory_bytes=write_settings.spool_memory_bytes,
            multipart_part_bytes=write_settings.multipart_part_bytes,
        ) as captured:
            await write_store.upload(object_key, captured)
    finally:
        await write_store.close()

    with pytest.raises(ObjectStoreDestinationCopyIncomplete):
        await service.replace_destination(
            _connection_input(real_unpaired_object_store),
            actor_user_id=actor,
        )


async def test_switch_refuses_content_that_became_servable_mid_verification(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Work promoted during the scan cannot ride into an unverified cutover.

    A crash-recovered pending upload can be promoted to available under the
    advanced generation without any policy change, after its key range was
    scanned. The commit therefore requires, under the lock that fences all
    remote intents, exactly the served set identity the scan verified.
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

    original_verify = ObjectStoreConnectionService._require_target_holds_every_object

    async def promote_after_verification(self, settings):  # type: ignore[no-untyped-def]
        total = await original_verify(self, settings)
        # A recovered pending upload becomes servable on the source after
        # its key range was scanned.
        source_settings = service.settings_for(created)
        source_store = S3ObjectStore(source_settings)
        try:
            await _seed_remote_content(
                object_content_database,
                source_settings,
                source_store,
                b"promoted-mid-verification",
            )
        finally:
            await source_store.close()
        return total

    monkeypatch.setattr(
        ObjectStoreConnectionService,
        "_require_target_holds_every_object",
        promote_after_verification,
    )
    with pytest.raises(ObjectStoreDestinationCopyIncomplete):
        await service.replace_destination(
            _connection_input(real_unpaired_object_store),
            actor_user_id=actor,
        )
    monkeypatch.undo()

    current = await service.get()
    assert current is not None
    assert current.bucket == real_object_store.settings.bucket


async def test_switch_refuses_an_equal_count_set_substitution(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A -1/+1 swap during the scan cannot hide behind an unchanged count.

    A deletion completed during verification plus a recovered publication
    promoted after its key range was scanned preserves the served count
    while changing the set. The commit compares the set's identity — count
    and order-stable digest — so the substituted object cannot ride into an
    unverified cutover.
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

    # One served object exists and is faithfully copied to the target.
    source_settings = service.settings_for(created)
    source_store = S3ObjectStore(source_settings)
    payload = b"verified-then-substituted"
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

    original_verify = ObjectStoreConnectionService._require_target_holds_every_object

    async def substitute_after_verification(self, settings):  # type: ignore[no-untyped-def]
        snapshot = await original_verify(self, settings)
        # The verified object leaves the served set while a different,
        # never-verified object enters it: the count is unchanged.
        async with object_content_database.session() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE object_contents SET state = 'failed', "
                    "failure_code = 'backend_missing' "
                    "WHERE id = (SELECT content_id FROM object_store_objects "
                    "WHERE object_key = :key)"
                ),
                {"key": object_key},
            )
        replacement_store = S3ObjectStore(service.settings_for(created))
        try:
            await _seed_remote_content(
                object_content_database,
                service.settings_for(created),
                replacement_store,
                b"promoted-in-its-place",
            )
        finally:
            await replacement_store.close()
        return snapshot

    monkeypatch.setattr(
        ObjectStoreConnectionService,
        "_require_target_holds_every_object",
        substitute_after_verification,
    )
    with pytest.raises(ObjectStoreDestinationCopyIncomplete):
        await service.replace_destination(
            _connection_input(real_unpaired_object_store),
            actor_user_id=actor,
        )
    monkeypatch.undo()

    current = await service.get()
    assert current is not None
    assert current.bucket == real_object_store.settings.bucket


async def test_mismatch_cleanup_yields_to_an_adopted_candidate(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup after a lost marker race must not strip a newer owner.

    If a concurrent attempt adopted the candidate row while this one was
    losing the conditional marker creation, the row and its binding claim
    belong to that owner now. The ownership-checked cleanup touches nothing
    it no longer owns.
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

    async def adopt_then_lose_the_marker(self, creation):  # type: ignore[no-untyped-def]
        # A concurrent same-target attempt adopts the candidate row just as
        # this attempt loses the marker race to a foreign installation.
        async with object_content_database.session() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE object_store_connections "
                    "SET revision = revision + 1 "
                    "WHERE id = 2 AND role = 'candidate'"
                )
            )
        raise ObjectStoreBindingError(
            "Object content storage is paired with another database"
        )

    monkeypatch.setattr(S3ObjectStore, "create_binding", adopt_then_lose_the_marker)
    with pytest.raises(ObjectStoreProbeBindingMismatch):
        await service.replace_destination(
            _connection_input(real_unpaired_object_store),
            actor_user_id=actor,
        )
    monkeypatch.undo()

    # The adopting owner's record and claim are intact.
    async with object_content_database.session() as session, session.begin():
        remaining = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM object_store_connections "
                    "WHERE id = 2 AND role = 'candidate') + "
                    "(SELECT count(*) FROM object_store_bindings "
                    "WHERE slot = 2)"
                )
            )
        ).scalar_one()
    assert remaining == 2


async def test_a_stale_release_retires_a_foreign_marked_candidate(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    real_spare_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A foreign-marked residue candidate cannot wedge later switches.

    When the interrupted attempt's own cleanup lost ownership — a concurrent
    adoption moved the candidate revision — the residue survives with a real
    foreign marker on its bucket. The next destination change's stale
    release proves the marker foreign, retires the local record (nothing of
    ours exists remotely), and completes without manual database repair.
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

    original_prepare = S3ObjectStore.prepare_binding_creation
    original_create = S3ObjectStore.create_binding
    foreign_binding_id = uuid4()

    async def foreign_wins_then_adoption_moves_on(self, creation):  # type: ignore[no-untyped-def]
        # A foreign installation's marker lands first (a REAL marker with a
        # different binding identity), and a concurrent adoption moves the
        # candidate revision so this attempt's own cleanup no longer owns
        # the row.
        foreign_writer = S3ObjectStore(
            real_unpaired_object_store.settings.model_copy(
                update={"deployment_id": created.deployment_id}
            )
        )
        try:
            foreign_creation = await original_prepare(
                foreign_writer, foreign_binding_id, require_empty_namespace=False
            )
            assert foreign_creation is not None
            await original_create(foreign_writer, foreign_creation)
        finally:
            await foreign_writer.close()
        async with object_content_database.session() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE object_store_connections "
                    "SET revision = revision + 1 "
                    "WHERE id = 2 AND role = 'candidate'"
                )
            )
        # This attempt's own conditional creation now loses to the foreign
        # marker through the real adapter path.
        return await original_create(self, creation)

    monkeypatch.setattr(
        S3ObjectStore, "create_binding", foreign_wins_then_adoption_moves_on
    )
    with pytest.raises(ObjectStoreProbeBindingMismatch):
        await service.replace_destination(
            _connection_input(real_unpaired_object_store),
            actor_user_id=actor,
        )
    monkeypatch.undo()

    # The residue survived this attempt's disowned cleanup: a candidate row
    # for a bucket whose real marker is foreign.
    async with object_content_database.session() as session, session.begin():
        residue = await session.get(ObjectStoreConnections, TEMPORARY_DESTINATION_SLOT)
        assert residue is not None
        assert residue.bucket == real_unpaired_object_store.settings.bucket

    # The next destination change proves the marker foreign, retires the
    # residue, and completes — no manual repair.
    switch = await service.replace_destination(
        _connection_input(real_spare_object_store),
        actor_user_id=actor,
    )
    assert switch.active.bucket == real_spare_object_store.settings.bucket

    # The foreign installation's marker was never ours to remove: it still
    # verifies with its own identity after the release.
    foreign_check = S3ObjectStore(
        real_unpaired_object_store.settings.model_copy(
            update={"deployment_id": created.deployment_id}
        )
    )
    try:
        assert await foreign_check.verify_binding(foreign_binding_id)
    finally:
        await foreign_check.close()


async def test_a_lost_foreign_marker_race_does_not_wedge_future_switches(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    real_spare_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Losing the marker race to another installation releases everything.

    When a foreign deployment wins the conditional marker creation, nothing
    of ours was written — but a lingering candidate row for that bucket
    could never be released later, since its marker is not ours to remove,
    and every subsequent destination change would fail against it.
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

    original_create = S3ObjectStore.create_binding

    async def foreign_wins_the_marker(self, creation):  # type: ignore[no-untyped-def]
        raise ObjectStoreBindingError(
            "Object content storage is paired with another database"
        )

    monkeypatch.setattr(S3ObjectStore, "create_binding", foreign_wins_the_marker)
    with pytest.raises(ObjectStoreProbeBindingMismatch):
        await service.replace_destination(
            _connection_input(real_unpaired_object_store),
            actor_user_id=actor,
        )
    monkeypatch.setattr(S3ObjectStore, "create_binding", original_create)

    # Nothing of ours lingers: no candidate row, no claim.
    async with object_content_database.session() as session, session.begin():
        residue = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM object_store_connections "
                    "WHERE id = 2) + (SELECT count(*) FROM "
                    "object_store_bindings WHERE slot = 2)"
                )
            )
        ).scalar_one()
    assert residue == 0

    # A switch to a different, clean destination succeeds without any
    # manual cleanup.
    switch = await service.replace_destination(
        _connection_input(real_spare_object_store),
        actor_user_id=actor,
    )
    assert switch.active.bucket == real_spare_object_store.settings.bucket


async def test_commit_yields_to_a_foreign_live_candidate(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    real_spare_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A switch never archives over another destination's live candidate.

    A concurrent change can release this attempt's claim and record its own
    candidate while this one is verifying. Committing anyway would overwrite
    that record with the retiring archive and leave the other bucket's
    marker untracked, so the commit yields with a typed conflict instead.
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
    original_verify = ObjectStoreConnectionService._require_target_holds_every_object

    async def hijack_candidate_mid_verification(self, settings):  # type: ignore[no-untyped-def]
        verified_snapshot = await original_verify(self, settings)
        # A concurrent change released this attempt's claim and recorded its
        # own candidate — with a real marker — for a different destination.
        spare_store = S3ObjectStore(
            real_spare_object_store.settings.model_copy(
                update={"deployment_id": created.deployment_id}
            )
        )
        try:
            creation = await spare_store.prepare_binding_creation(
                binding_id, require_empty_namespace=False
            )
            if creation is not None:
                await spare_store.create_binding(creation)
        finally:
            await spare_store.close()
        async with object_content_database.session() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE object_store_connections "
                    "SET endpoint_url = :endpoint_url, bucket = :bucket, "
                    "revision = revision + 1 "
                    "WHERE id = 2 AND role = 'candidate'"
                ),
                {
                    "endpoint_url": real_spare_object_store.settings.endpoint_url,
                    "bucket": real_spare_object_store.settings.bucket,
                },
            )
        return verified_snapshot

    monkeypatch.setattr(
        ObjectStoreConnectionService,
        "_require_target_holds_every_object",
        hijack_candidate_mid_verification,
    )
    with pytest.raises(ObjectStoreConnectionConflict):
        await service.replace_destination(
            _connection_input(real_unpaired_object_store),
            actor_user_id=actor,
        )
    monkeypatch.undo()

    # The foreign candidate record and its marker survive, and nothing was
    # activated.
    async with object_content_database.session() as session, session.begin():
        candidate = await session.get(
            ObjectStoreConnections, TEMPORARY_DESTINATION_SLOT
        )
        assert candidate is not None
        assert candidate.role == "candidate"
        assert candidate.bucket == real_spare_object_store.settings.bucket
    current = await service.get()
    assert current is not None
    assert current.bucket == real_object_store.settings.bucket
    spare_check = S3ObjectStore(
        real_spare_object_store.settings.model_copy(
            update={"deployment_id": created.deployment_id}
        )
    )
    try:
        assert await spare_check.verify_binding(binding_id)
    finally:
        await spare_check.close()

    # The surviving candidate's own switch completes: the recovery contract
    # the guard preserved is a working destination change, not just a row.
    switch = await service.replace_destination(
        _connection_input(real_spare_object_store),
        actor_user_id=actor,
    )
    assert switch.active.bucket == real_spare_object_store.settings.bucket
    active_check = S3ObjectStore(
        real_spare_object_store.settings.model_copy(
            update={"deployment_id": created.deployment_id}
        )
    )
    try:
        assert await active_check.verify_binding(binding_id)
    finally:
        await active_check.close()


async def test_verification_cost_follows_stored_objects_not_the_target(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hostile or huge candidate cannot make Eneo hold its inventory.

    The candidate is an endpoint an administrator names, so what it returns
    is not this deployment's business: completeness is driven from the keys
    Eneo stores, and asking about them is all the candidate can cost.
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

    source_settings = service.settings_for(created)
    source_store = S3ObjectStore(source_settings)
    payload = b"one-copied-object"
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

    listings = 0
    original_list = S3ObjectStore.list_object_page

    async def count_listings(self, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal listings
        listings += 1
        return await original_list(self, **kwargs)

    monkeypatch.setattr(S3ObjectStore, "list_object_page", count_listings)
    switch = await service.replace_destination(
        _connection_input(real_unpaired_object_store),
        actor_user_id=actor,
    )
    monkeypatch.undo()

    assert switch.active.bucket == real_unpaired_object_store.settings.bucket
    assert listings == 0, "verification must not enumerate the candidate bucket"


async def test_a_second_switch_cannot_overwrite_a_live_candidate(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    real_spare_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two changes at once must not leave one bucket's marker unrecoverable.

    The candidate record is the only trace of a bucket whose marker is about
    to be written, so the second attempt is refused instead of replacing it.
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

    # A second attempt whose own release could not reach the claimed bucket
    # must not silently take the slot from it.
    async def unreachable(self, binding_id):  # type: ignore[no-untyped-def]
        raise ObjectStoreUnavailableError("injected release failure")

    monkeypatch.setattr(S3ObjectStore, "remove_binding", unreachable)
    with pytest.raises(ObjectStoreDestinationAlreadyBound):
        await service.replace_destination(
            _connection_input(real_spare_object_store),
            actor_user_id=actor,
        )
    monkeypatch.undo()

    async with object_content_database.session() as session, session.begin():
        candidate = await session.get(
            ObjectStoreConnections, TEMPORARY_DESTINATION_SLOT
        )
        assert candidate is not None
        assert candidate.bucket == real_unpaired_object_store.settings.bucket


async def test_zombie_cleanup_cannot_unbind_an_adopted_destination(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup owns the marker only while it owns the candidate revision.

    An interrupted attempt's cleanup can wake up after a same-target retry
    has adopted the destination and switched to it. The retry's adoption
    advanced the candidate revision, so the zombie's ownership handshake
    fails before it issues any remote delete, and the active destination
    stays bound.
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

    async with object_content_database.session() as session, session.begin():
        interrupted = await session.get(
            ObjectStoreConnections, TEMPORARY_DESTINATION_SLOT
        )
        assert interrupted is not None
        interrupted_revision = interrupted.revision

    # The same-target retry adopts the marked destination and switches.
    switch = await service.replace_destination(
        _connection_input(real_unpaired_object_store),
        actor_user_id=actor,
    )
    assert switch.active.bucket == real_unpaired_object_store.settings.bucket

    # The interrupted attempt's cleanup finally runs with its stale
    # ownership. The revision handshake must stop it before any remote
    # delete, leaving the active destination bound.
    candidate_settings = service.settings_for(created).model_copy(
        update={
            "endpoint_url": real_unpaired_object_store.settings.endpoint_url,
            "bucket": real_unpaired_object_store.settings.bucket,
        }
    )
    await service._abandon_switch_claim(  # noqa: SLF001
        candidate_settings,
        binding_id=binding_id,
        candidate_revision=interrupted_revision,
    )

    active_store = S3ObjectStore(
        real_unpaired_object_store.settings.model_copy(
            update={"deployment_id": created.deployment_id}
        )
    )
    try:
        assert await active_store.verify_binding(binding_id)
    finally:
        await active_store.close()


async def test_the_current_destination_is_refused_in_any_equivalent_form(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A trailing slash does not make the active bucket a new destination.

    The settings model strips it, so `https://host/` and `https://host` are
    one destination. Comparing the raw input would let the active bucket
    through as new: Eneo would probe it, spend generations, and archive the
    destination as its own predecessor.
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

    probes = 0
    original_probe = ObjectStoreConnectionService._probe

    async def count_probes(self, settings, *, binding):  # type: ignore[no-untyped-def]
        nonlocal probes
        probes += 1
        return await original_probe(self, settings, binding=binding)

    monkeypatch.setattr(ObjectStoreConnectionService, "_probe", count_probes)

    endpoint = real_object_store.settings.endpoint_url
    scheme, _, authority = endpoint.partition("://")
    host, _, port = authority.partition(":")
    equivalents = (
        f"{endpoint}/",
        f"{scheme}://{host.upper()}:{port}" if port else f"{scheme}://{host.upper()}",
    )
    for equivalent in equivalents:
        same_destination = _connection_input(real_object_store).model_copy(
            update={"endpoint_url": equivalent}
        )
        with pytest.raises(ObjectStoreConnectionInvalid):
            await service.replace_destination(same_destination, actor_user_id=actor)
    monkeypatch.undo()

    assert probes == 0, "a self-switch must be refused before any remote work"
    current = await service.get()
    assert current is not None
    assert current.revision == created.revision, "no generation may be spent"
    assert await service.get_previous() is None, "no destination may be archived"


async def test_adoption_is_refused_while_a_release_lease_is_live(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry must not adopt a marker whose deletion is in flight.

    A releasing cleanup holds a durable lease before it touches the store,
    so a same-target retry arriving in that window is refused with a
    retryable reason instead of racing the pending delete. The lease expires
    on its own, so a release that dies only delays the next attempt.
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

    # The interrupted attempt's cleanup takes its release lease.
    async with object_content_database.session() as session, session.begin():
        await session.execute(
            text(
                "UPDATE object_store_bindings "
                "SET claim_id = gen_random_uuid(), "
                "claim_until = now() + interval '60 seconds' "
                "WHERE slot = 2"
            )
        )

    with pytest.raises(ObjectStoreDestinationSwitchBlocked):
        await service.replace_destination(
            _connection_input(real_unpaired_object_store),
            actor_user_id=actor,
        )


async def test_an_ownerless_marker_is_reclaimed_not_trusted(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A marker whose candidate record is gone is rebuilt, not relied on.

    A finished release that failed its remote deletion leaves a marker with
    no record. A retry cannot know whether that marker will persist, so it
    reclaims the bucket and goes through the full claimed admission,
    finishing with a marker it owns.
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

    # A finished release consumed the candidate record and the claim but its
    # remote marker deletion failed, leaving the marker ownerless.
    async with object_content_database.session() as session, session.begin():
        await session.execute(text("DELETE FROM object_store_bindings WHERE slot = 2"))
        await session.execute(text("DELETE FROM object_store_connections WHERE id = 2"))

    switch = await service.replace_destination(
        _connection_input(real_unpaired_object_store),
        actor_user_id=actor,
    )
    assert switch.active.bucket == real_unpaired_object_store.settings.bucket
    active_store = S3ObjectStore(
        real_unpaired_object_store.settings.model_copy(
            update={"deployment_id": created.deployment_id}
        )
    )
    try:
        assert await active_store.verify_binding(binding_id)
    finally:
        await active_store.close()


async def test_committed_switch_reasserts_a_marker_lost_to_concurrent_cleanup(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The active destination ends up marked, whatever raced the switch.

    A concurrent attempt's cleanup can remove the marker between this
    switch's admission check and its commit; no ordering of lock-free remote
    deletes prevents every interleaving. The committed switch therefore
    re-asserts its own marker, so the race's worst outcome is a marker that
    briefly disappeared, never an active destination without one.
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

    # A competing attempt's cleanup deletes the target's marker after this
    # switch admitted it, just before the swap commits.
    original_commit = ObjectStoreConnectionService._commit_switch

    async def steal_marker_then_commit(self, candidate, **kwargs):  # type: ignore[no-untyped-def]
        thief = S3ObjectStore(
            real_unpaired_object_store.settings.model_copy(
                update={"deployment_id": created.deployment_id}
            )
        )
        try:
            await thief.remove_binding(binding_id)
            assert not await thief.verify_binding(binding_id)
        finally:
            await thief.close()
        return await original_commit(self, candidate, **kwargs)

    monkeypatch.setattr(
        ObjectStoreConnectionService, "_commit_switch", steal_marker_then_commit
    )
    switch = await service.replace_destination(
        _connection_input(real_unpaired_object_store),
        actor_user_id=actor,
    )
    monkeypatch.undo()

    assert switch.active.bucket == real_unpaired_object_store.settings.bucket
    active_store = S3ObjectStore(
        real_unpaired_object_store.settings.model_copy(
            update={"deployment_id": created.deployment_id}
        )
    )
    try:
        assert await active_store.verify_binding(binding_id)
    finally:
        await active_store.close()


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
    switch = await service.replace_destination(
        _connection_input(real_unpaired_object_store),
        actor_user_id=actor,
    )

    with pytest.raises(ObjectStorePreviousDestinationPresent):
        await service.replace_destination(
            _connection_input(real_object_store),
            actor_user_id=actor,
        )

    # Forgetting the archive releases the slot and the switch proceeds.
    await service.forget_previous_destination(
        actor_user_id=actor, expected_revision=switch.previous.revision
    )
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


async def test_switch_refuses_when_the_policy_moved_during_verification(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A policy round trip during verification invalidates the frozen state.

    Creating a remote object requires selecting object storage or resuming
    moves, and either change advances the policy revision. An administrator
    who re-enables writes mid-verification and restores the quiet state
    before the swap would otherwise activate a target that was never checked
    for what they wrote.
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

    original_verify = ObjectStoreConnectionService._require_target_holds_every_object

    async def flip_policy_mid_verification(self, settings):  # type: ignore[no-untyped-def]
        verified_snapshot = await original_verify(self, settings)
        # Another administrator briefly re-enables object storage and puts
        # the quiet state back, all while this switch is verifying.
        await _select_object_store_writes(object_content_database)
        await _select_inline_writes(object_content_database)
        return verified_snapshot

    monkeypatch.setattr(
        ObjectStoreConnectionService,
        "_require_target_holds_every_object",
        flip_policy_mid_verification,
    )

    with pytest.raises(ObjectStorePolicyChangedDuringSwitch):
        await service.replace_destination(
            _connection_input(real_unpaired_object_store),
            actor_user_id=actor,
        )
    monkeypatch.undo()

    # The active destination is unchanged; a retry from the restored quiet
    # state succeeds.
    switch = await service.replace_destination(
        _connection_input(real_unpaired_object_store),
        actor_user_id=actor,
    )
    assert switch.active.bucket == real_unpaired_object_store.settings.bucket


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


async def test_a_stale_revision_cannot_mutate_a_replacement_archive(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
) -> None:
    """Switch-back and forget act only on the archive the administrator saw.

    A stale page can hold the revision of an archive that a concurrent
    administrator has since forgotten and replaced. Its request must be
    refused with the typed revision conflict instead of restoring or
    deleting the replacement.
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

    first = await service.replace_destination(
        _connection_input(real_unpaired_object_store),
        actor_user_id=actor,
    )
    stale_revision = first.previous.revision

    # A rival administrator forgets that archive and completes another
    # switch, archiving a different destination in its place.
    await service.forget_previous_destination(
        actor_user_id=actor, expected_revision=stale_revision
    )
    second = await service.replace_destination(
        _connection_input(real_object_store),
        actor_user_id=actor,
    )
    # Archives adopt the strictly growing active generation, so a
    # replacement always carries a LARGER revision than any earlier archive.
    assert second.previous.revision > stale_revision

    with pytest.raises(ObjectStoreConnectionConflict):
        await service.forget_previous_destination(
            actor_user_id=actor, expected_revision=stale_revision
        )
    with pytest.raises(ObjectStoreConnectionConflict):
        await service.switch_back(
            actor_user_id=actor,
            expected_previous_revision=stale_revision,
        )

    # The replacement archive and the active destination are untouched.
    remaining = await service.get_previous()
    assert remaining is not None
    assert remaining.revision == second.previous.revision
    current = await service.get()
    assert current is not None
    assert current.bucket == real_object_store.settings.bucket


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
        await service.switch_back(
            actor_user_id=actor,
            expected_previous_revision=switch.previous.revision,
        )


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
        await service.forget_previous_destination(
            actor_user_id=actor, expected_revision=switch.previous.revision
        )
        return await original_probe(self, settings, binding=binding)

    monkeypatch.setattr(ObjectStoreConnectionService, "_probe", forget_during_probe)

    with pytest.raises(ObjectStoreConnectionConflict):
        await service.switch_back(
            actor_user_id=actor,
            expected_previous_revision=switch.previous.revision,
        )
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
