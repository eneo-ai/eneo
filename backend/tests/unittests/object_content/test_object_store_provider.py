import asyncio
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import ObjectContentUnavailableError
from eneo.object_content.object_store_connection import (
    ObjectStoreConnectionActor,
    ObjectStoreConnectionService,
    StoredObjectStoreConnection,
)
from eneo.object_content.object_store_provider import ObjectStoreProvider
from eneo.object_content.s3_object_store import S3ObjectStore


class _Store:
    def __init__(self, revision: int) -> None:
        self.revision = revision
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _ConnectionService:
    def __init__(self, stored: StoredObjectStoreConnection | None) -> None:
        self.stored = stored
        self.adopted = _stored(1)
        self.adopt_calls = 0

    async def get(self) -> StoredObjectStoreConnection | None:
        return self.stored

    async def adopt_legacy(
        self,
        _settings: ObjectContentSettings,
    ) -> StoredObjectStoreConnection:
        self.adopt_calls += 1
        self.stored = self.adopted
        return self.adopted

    def settings_for(
        self,
        stored: StoredObjectStoreConnection,
    ) -> ObjectContentSettings:
        return _settings(stored.revision)


class _BlockingConnectionService(_ConnectionService):
    def __init__(self, stored: StoredObjectStoreConnection) -> None:
        super().__init__(stored)
        self.block_reads = False
        self.get_started = asyncio.Event()
        self.get_finished = asyncio.Event()
        self.release_get = asyncio.Event()
        self.get_calls = 0

    async def get(self) -> StoredObjectStoreConnection | None:
        self.get_calls += 1
        if self.block_reads:
            self.get_started.set()
            await self.release_get.wait()
        self.get_finished.set()
        return self.stored


class _CapturedBlockingConnectionService(_ConnectionService):
    def __init__(self, stored: StoredObjectStoreConnection) -> None:
        super().__init__(stored)
        self.get_started = asyncio.Event()
        self.release_get = asyncio.Event()

    async def get(self) -> StoredObjectStoreConnection | None:
        captured = self.stored
        self.get_started.set()
        await self.release_get.wait()
        return captured


class _BlockingAdoptionConnectionService(_ConnectionService):
    def __init__(self) -> None:
        super().__init__(None)
        self.adopt_started = asyncio.Event()
        self.release_adoption = asyncio.Event()

    async def adopt_legacy(
        self,
        _settings: ObjectContentSettings,
    ) -> StoredObjectStoreConnection:
        self.adopt_calls += 1
        self.adopt_started.set()
        await self.release_adoption.wait()
        self.stored = self.adopted
        return self.adopted


def _stored(revision: int) -> StoredObjectStoreConnection:
    now = datetime.now(UTC)
    return StoredObjectStoreConnection(
        revision=revision,
        endpoint_url="https://objects.example.test",
        region="se-1",
        bucket="eneo-content",
        access_key_id_encrypted="encrypted-access",
        secret_access_key_encrypted="encrypted-secret",
        deployment_id=UUID("a2d539af-fef0-42aa-a7f8-14376947be2c"),
        addressing_style="path",
        updated_by_actor=ObjectStoreConnectionActor.PLATFORM_ADMIN,
        updated_by_user_id=None,
        created_at=now,
        updated_at=now,
    )


def _settings(revision: int) -> ObjectContentSettings:
    return ObjectContentSettings(
        _env_file=None,
        endpoint_url="https://objects.example.test",
        region="se-1",
        bucket="eneo-content",
        access_key_id=f"access-{revision}",
        secret_access_key=f"secret-{revision}",
        deployment_id=UUID("a2d539af-fef0-42aa-a7f8-14376947be2c"),
    )


@pytest.mark.asyncio
async def test_remote_acquisition_observes_rotation_and_drains_the_old_client() -> None:
    service = _ConnectionService(_stored(1))
    stores: list[_Store] = []

    def store_factory(settings: ObjectContentSettings) -> S3ObjectStore:
        revision = int(settings.access_key_id.get_secret_value().rsplit("-", 1)[1])
        store = _Store(revision)
        stores.append(store)
        return cast(S3ObjectStore, store)

    provider = ObjectStoreProvider(
        connection_service=cast(ObjectStoreConnectionService, service),
        store_factory=store_factory,
    )
    await provider.initialize()

    async with provider.acquire() as first:
        assert cast(_Store, first.store).revision == 1
        service.stored = _stored(2)

        async with provider.acquire() as second:
            assert cast(_Store, second.store).revision == 2
            assert stores[0].closed is False

    assert stores[0].closed is True
    assert stores[1].closed is False

    await provider.close()
    assert stores[1].closed is True


@pytest.mark.asyncio
async def test_initialization_cannot_replace_a_newer_published_revision() -> None:
    service = _CapturedBlockingConnectionService(_stored(1))
    provider = ObjectStoreProvider(
        connection_service=cast(ObjectStoreConnectionService, service),
        store_factory=lambda settings: cast(
            S3ObjectStore,
            _Store(int(settings.access_key_id.get_secret_value().rsplit("-", 1)[1])),
        ),
    )

    initialization = asyncio.create_task(provider.initialize())
    await asyncio.wait_for(service.get_started.wait(), timeout=1)
    publication = asyncio.create_task(provider.publish(_stored(2)))
    await asyncio.sleep(0)
    service.release_get.set()
    await asyncio.gather(initialization, publication)

    async with provider.acquire(refresh=False) as lease:
        assert cast(_Store, lease.store).revision == 2
    assert provider.configuration_revision == 2

    await provider.close()


@pytest.mark.asyncio
async def test_concurrent_acquisitions_share_one_connection_refresh() -> None:
    service = _BlockingConnectionService(_stored(1))
    stores: list[_Store] = []

    def store_factory(settings: ObjectContentSettings) -> S3ObjectStore:
        revision = int(settings.access_key_id.get_secret_value().rsplit("-", 1)[1])
        store = _Store(revision)
        stores.append(store)
        return cast(S3ObjectStore, store)

    provider = ObjectStoreProvider(
        connection_service=cast(ObjectStoreConnectionService, service),
        store_factory=store_factory,
    )
    await provider.initialize()
    service.block_reads = True

    async def acquire_revision() -> int:
        async with provider.acquire() as lease:
            return cast(_Store, lease.store).revision

    acquisitions = [asyncio.create_task(acquire_revision()) for _ in range(5)]
    await asyncio.wait_for(service.get_started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert service.get_calls == 2

    service.release_get.set()

    assert await asyncio.gather(*acquisitions) == [1, 1, 1, 1, 1]
    assert service.get_calls == 2

    service.block_reads = False
    service.stored = _stored(2)
    async with provider.acquire() as lease:
        assert cast(_Store, lease.store).revision == 2

    assert service.get_calls == 3
    assert stores[0].closed is True

    await provider.close()


@pytest.mark.asyncio
async def test_admitted_revision_acquires_without_another_connection_read() -> None:
    service = _BlockingConnectionService(_stored(1))
    provider = ObjectStoreProvider(
        connection_service=cast(ObjectStoreConnectionService, service),
        store_factory=lambda settings: cast(S3ObjectStore, _Store(1)),
    )
    await provider.initialize()

    revision = provider.configuration_revision
    assert revision == 1
    service.block_reads = True

    async with provider.acquire(refresh=False, expected_revision=revision) as lease:
        assert lease.settings == _settings(1)

    assert service.get_calls == 1
    await provider.publish(_stored(2))
    with pytest.raises(
        ObjectContentUnavailableError,
        match="changed during the upload; try again",
    ) as error:
        async with provider.acquire(refresh=False, expected_revision=revision):
            pass
    assert type(error.value) is ObjectContentUnavailableError
    assert service.get_calls == 1
    await provider.close()


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_reuse_a_completed_refresh() -> None:
    service = _BlockingConnectionService(_stored(1))
    stores: list[_Store] = []

    def store_factory(settings: ObjectContentSettings) -> S3ObjectStore:
        revision = int(settings.access_key_id.get_secret_value().rsplit("-", 1)[1])
        store = _Store(revision)
        stores.append(store)
        return cast(S3ObjectStore, store)

    provider = ObjectStoreProvider(
        connection_service=cast(ObjectStoreConnectionService, service),
        store_factory=store_factory,
    )
    await provider.initialize()
    service.block_reads = True
    service.get_started.clear()
    service.get_finished.clear()

    async def acquire_revision() -> int:
        async with provider.acquire() as lease:
            return cast(_Store, lease.store).revision

    cancelled_acquisition = asyncio.create_task(acquire_revision())
    await asyncio.wait_for(service.get_started.wait(), timeout=1)
    cancelled_acquisition.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_acquisition

    service.release_get.set()
    await asyncio.wait_for(service.get_finished.wait(), timeout=1)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    service.block_reads = False
    service.stored = _stored(2)
    assert await acquire_revision() == 2
    assert service.get_calls == 3
    assert stores[0].closed is True

    await provider.close()


@pytest.mark.asyncio
async def test_legacy_adoption_cannot_replace_a_newer_published_revision() -> None:
    service = _BlockingAdoptionConnectionService()
    stores: list[_Store] = []

    def store_factory(settings: ObjectContentSettings) -> S3ObjectStore:
        revision = int(settings.access_key_id.get_secret_value().rsplit("-", 1)[1])
        store = _Store(revision)
        stores.append(store)
        return cast(S3ObjectStore, store)

    provider = ObjectStoreProvider(
        connection_service=cast(ObjectStoreConnectionService, service),
        legacy_settings=_settings(0),
        store_factory=store_factory,
    )
    await provider.initialize()

    adoption = asyncio.create_task(provider.adopt_validated_legacy())
    await asyncio.wait_for(service.adopt_started.wait(), timeout=1)
    await provider.publish(_stored(2))
    service.release_adoption.set()
    await adoption

    assert provider.stored_connection is not None
    assert provider.stored_connection.revision == 2
    assert [store.revision for store in stores] == [0, 2]
    assert stores[0].closed is True

    await provider.close()


@pytest.mark.asyncio
async def test_legacy_settings_are_adopted_only_after_validation() -> None:
    service = _ConnectionService(None)
    stores: list[_Store] = []

    def store_factory(settings: ObjectContentSettings) -> S3ObjectStore:
        store = _Store(
            0 if settings.access_key_id.get_secret_value() == "access-0" else 1
        )
        stores.append(store)
        return cast(S3ObjectStore, store)

    provider = ObjectStoreProvider(
        connection_service=cast(ObjectStoreConnectionService, service),
        legacy_settings=_settings(0),
        store_factory=store_factory,
    )

    await provider.initialize()

    assert provider.source.value == "environment"
    assert service.adopt_calls == 0

    await provider.adopt_validated_legacy()

    assert provider.source.value == "admin"
    assert service.adopt_calls == 1
    assert stores[0].closed is True

    await provider.close()
