import asyncio
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.object_content_table import (
    ObjectContentReconciliationState,
)
from eneo.database.tables.object_store_connection_table import ObjectStoreConnections
from eneo.database.tables.users_table import Users
from eneo.object_content.configuration import (
    ObjectContentCoreSettings,
    ObjectContentSettings,
    ObjectStoreOperatorSettings,
)
from eneo.object_content.content import ObjectContentUnavailableError
from eneo.object_content.object_store_connection import (
    ObjectStoreConnectionInput,
    ObjectStoreConnectionService,
    ObjectStoreCredentialRotation,
    ObjectStoreDestinationAlreadyBound,
    ObjectStoreProbeUnavailable,
)
from eneo.object_content.runtime import ObjectContentRuntime
from eneo.object_content.s3_object_store import S3ObjectStore, StoreBindingCreation
from eneo.object_content.store_binding import ensure_store_binding_ready
from eneo.settings.encryption_service import EncryptionService
from tests.integration.object_content.conftest import RealObjectStore


def _service(
    database: DatabaseSessionManager,
    settings: ObjectContentSettings,
    *,
    store_factory=S3ObjectStore,
) -> ObjectStoreConnectionService:
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
        | {"admin_allowed_endpoint_origins": (settings.endpoint_url,)}
    )
    return ObjectStoreConnectionService(
        database=database,
        core_settings=core,
        operator_settings=operator,
        encryption=EncryptionService(Fernet.generate_key().decode()),
        store_factory=store_factory,
    )


def _candidate(settings: ObjectContentSettings) -> ObjectStoreConnectionInput:
    return ObjectStoreConnectionInput(
        endpoint_url=settings.endpoint_url,
        region=settings.region,
        bucket=settings.bucket,
        access_key_id=settings.access_key_id,
        secret_access_key=settings.secret_access_key,
        addressing_style=settings.addressing_style,
    )


async def test_first_admin_connection_is_verified_encrypted_and_leaves_no_probe_object(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    service = _service(object_content_database, real_object_store.settings)
    async with object_content_database.session() as session, session.begin():
        actor_user_id = (await session.scalars(select(Users.id))).one()

    stored = await service.create(
        _candidate(real_object_store.settings),
        actor_user_id=actor_user_id,
    )

    assert stored.revision == 1
    assert stored.access_key_id_encrypted.startswith(EncryptionService.VERSION_PREFIX)
    assert stored.secret_access_key_encrypted.startswith(
        EncryptionService.VERSION_PREFIX
    )
    assert real_object_store.settings.access_key_id.get_secret_value() not in (
        stored.access_key_id_encrypted,
        stored.secret_access_key_encrypted,
    )

    rotated = await service.rotate_credentials(
        ObjectStoreCredentialRotation(
            expected_revision=stored.revision,
            access_key_id=real_object_store.settings.access_key_id,
            secret_access_key=real_object_store.settings.secret_access_key,
        ),
        actor_user_id=actor_user_id,
    )
    assert rotated.revision == 2

    resolved = service.settings_for(rotated)
    store = S3ObjectStore(resolved)
    try:
        page = await store.list_object_page()
    finally:
        await store.close()
    assert page.objects == ()


async def test_rotation_racing_initial_binding_cannot_remove_the_durable_marker(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(object_content_database, real_object_store.settings)
    async with object_content_database.session() as session, session.begin():
        actor_user_id = (await session.scalars(select(Users.id))).one()

    stored = await service.create(
        _candidate(real_object_store.settings),
        actor_user_id=actor_user_id,
    )
    connected_settings = service.settings_for(stored)
    readiness_store = S3ObjectStore(connected_settings)

    rotation_has_unbound_snapshot = asyncio.Event()
    release_rotation = asyncio.Event()
    binding_creation_started = asyncio.Event()
    release_binding_creation = asyncio.Event()
    original_create_binding = readiness_store.create_binding

    async def wait_before_rotation_binding(
        database: DatabaseSessionManager,
        settings: ObjectContentSettings,
        store: S3ObjectStore,
    ) -> None:
        rotation_has_unbound_snapshot.set()
        await release_rotation.wait()
        await ensure_store_binding_ready(database, settings, store)

    async def pause_binding_creation(creation: StoreBindingCreation) -> None:
        binding_creation_started.set()
        await release_binding_creation.wait()
        await original_create_binding(creation)

    monkeypatch.setattr(
        "eneo.object_content.object_store_connection.ensure_store_binding_ready",
        wait_before_rotation_binding,
    )
    monkeypatch.setattr(readiness_store, "create_binding", pause_binding_creation)

    rotation = asyncio.create_task(
        service.rotate_credentials(
            ObjectStoreCredentialRotation(
                expected_revision=stored.revision,
                access_key_id=real_object_store.settings.access_key_id,
                secret_access_key=real_object_store.settings.secret_access_key,
            ),
            actor_user_id=actor_user_id,
        )
    )
    await rotation_has_unbound_snapshot.wait()

    readiness = asyncio.create_task(
        ensure_store_binding_ready(
            object_content_database,
            connected_settings,
            readiness_store,
        )
    )
    await binding_creation_started.wait()
    release_rotation.set()
    with pytest.raises(ObjectStoreProbeUnavailable):
        await rotation

    release_binding_creation.set()
    await readiness

    async with object_content_database.session() as session, session.begin():
        state = await session.get(ObjectContentReconciliationState, 1)
        assert state is not None
        assert state.store_binding_id is not None
        assert state.store_binding_confirmed_at is not None
        assert await readiness_store.verify_binding(state.store_binding_id)
    await readiness_store.close()


async def test_existing_store_binding_refuses_a_new_destination_before_remote_io(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    async with object_content_database.session() as session, session.begin():
        state = await session.get(ObjectContentReconciliationState, 1)
        assert state is not None
        state.store_deployment_id = real_object_store.settings.deployment_id
        state.store_binding_id = real_object_store.settings.deployment_id
        state.store_binding_confirmed_at = datetime.now(UTC)

    factory_calls = 0

    def store_factory(_settings: ObjectContentSettings) -> S3ObjectStore:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("the remote store must not be opened")

    service = _service(
        object_content_database,
        real_object_store.settings,
        store_factory=store_factory,
    )

    with pytest.raises(ObjectStoreDestinationAlreadyBound):
        await service.create(
            _candidate(real_object_store.settings),
            actor_user_id=real_object_store.settings.deployment_id,
        )

    assert factory_calls == 0


async def test_invalid_legacy_connection_is_not_adopted_and_can_recover(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = real_object_store.settings
    connection_environment = {
        "OBJECT_CONTENT_ENDPOINT_URL": settings.endpoint_url,
        "OBJECT_CONTENT_REGION": settings.region,
        "OBJECT_CONTENT_BUCKET": settings.bucket,
        "OBJECT_CONTENT_ACCESS_KEY_ID": settings.access_key_id.get_secret_value(),
        "OBJECT_CONTENT_SECRET_ACCESS_KEY": "invalid-secret",
        "OBJECT_CONTENT_DEPLOYMENT_ID": str(settings.deployment_id),
        "OBJECT_CONTENT_ADDRESSING_STYLE": settings.addressing_style,
        "OBJECT_CONTENT_ALLOW_INSECURE_HTTP": "true",
    }
    for name, value in connection_environment.items():
        monkeypatch.setenv(name, value)

    encryption = EncryptionService(Fernet.generate_key().decode())
    invalid_runtime = ObjectContentRuntime(object_content_database)
    invalid_runtime.start(encryption=encryption)
    try:
        with pytest.raises(ObjectContentUnavailableError):
            await invalid_runtime.validate_configuration()
    finally:
        await invalid_runtime.stop()

    async with object_content_database.session() as session, session.begin():
        assert await session.scalar(select(ObjectStoreConnections)) is None

    monkeypatch.setenv(
        "OBJECT_CONTENT_SECRET_ACCESS_KEY",
        settings.secret_access_key.get_secret_value(),
    )
    recovered_runtime = ObjectContentRuntime(object_content_database)
    recovered_runtime.start(encryption=encryption)
    try:
        await recovered_runtime.validate_configuration()
        assert recovered_runtime.object_store_connection_source.value == "admin"
    finally:
        await recovered_runtime.stop()

    async with object_content_database.session() as session, session.begin():
        assert await session.scalar(select(ObjectStoreConnections)) is not None
