from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from eneo.object_content.configuration import ObjectContentSettings
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
