import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import DatabaseSessionManager
from eneo.object_content.configuration import (
    ObjectContentCoreSettings,
    ObjectContentSettings,
    ObjectStoreOperatorSettings,
)
from eneo.object_content.content import CapturedContent
from eneo.object_content.object_store_connection import (
    ObjectStoreConnectionDatabaseUnavailable,
    ObjectStoreConnectionService,
    ObjectStoreProbeCleanupFailed,
    ObjectStoreProbeConnectionFailed,
)
from eneo.object_content.s3_object_store import (
    ObjectStoreUnavailableError,
    S3ObjectStore,
    StoreBindingCreation,
)
from eneo.settings.encryption_service import EncryptionService


class _DelayedUploadStore:
    def __init__(self) -> None:
        self.object_exists = False
        self.closed = False

    async def prepare_binding_creation(
        self,
        _binding_id: UUID,
    ) -> StoreBindingCreation | None:
        return None

    async def upload(self, _key: str, _content: CapturedContent) -> None:
        await asyncio.sleep(0.05)
        self.object_exists = True

    async def delete_and_confirm(self, _key: str) -> None:
        self.object_exists = False

    async def close(self) -> None:
        self.closed = True


class _CleanupFailureStore(_DelayedUploadStore):
    async def upload(self, _key: str, _content: CapturedContent) -> None:
        self.object_exists = True
        raise ObjectStoreUnavailableError("upload outcome is ambiguous")

    async def delete_and_confirm(self, _key: str) -> None:
        raise ObjectStoreUnavailableError("cleanup could not be confirmed")


class _ExternallyCancelledStore(_DelayedUploadStore):
    def __init__(self, *, fail_upload: bool) -> None:
        super().__init__()
        self.fail_upload = fail_upload
        self.upload_started = asyncio.Event()
        self.release_upload = asyncio.Event()
        self.cleanup_complete = False

    async def upload(self, _key: str, _content: CapturedContent) -> None:
        self.upload_started.set()
        await self.release_upload.wait()
        if self.fail_upload:
            raise ObjectStoreUnavailableError("upload failed after cancellation")
        self.object_exists = True

    async def delete_and_confirm(self, _key: str) -> None:
        self.object_exists = False
        self.cleanup_complete = True


class _UnavailableDatabase:
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        raise SQLAlchemyError("database unavailable")
        yield cast(AsyncSession, None)


def _settings() -> ObjectContentSettings:
    return ObjectContentSettings(
        _env_file=None,
        endpoint_url="https://objects.example.test",
        region="se-1",
        bucket="eneo-content",
        access_key_id="access",
        secret_access_key="secret",
        deployment_id=UUID("a2d539af-fef0-42aa-a7f8-14376947be2c"),
    )


def _service(
    store: object, database: object = object()
) -> ObjectStoreConnectionService:
    return ObjectStoreConnectionService(
        database=cast(DatabaseSessionManager, database),
        core_settings=ObjectContentCoreSettings(_env_file=None),
        operator_settings=ObjectStoreOperatorSettings(_env_file=None),
        encryption=EncryptionService(Fernet.generate_key().decode()),
        store_factory=lambda _settings: cast(S3ObjectStore, store),
    )


@pytest.mark.asyncio
async def test_probe_waits_for_timed_out_upload_before_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _DelayedUploadStore()
    service = _service(store)
    monkeypatch.setattr(
        "eneo.object_content.object_store_connection._PROBE_END_TO_END_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        "eneo.object_content.object_store_connection._PROBE_REQUEST_TIMEOUT_SECONDS",
        0.001,
    )

    with pytest.raises(ObjectStoreProbeConnectionFailed):
        await service._probe(_settings(), binding=None)

    assert store.object_exists is False
    assert store.closed is True


@pytest.mark.asyncio
async def test_probe_reports_cleanup_failure_after_ambiguous_upload() -> None:
    store = _CleanupFailureStore()

    with pytest.raises(ObjectStoreProbeCleanupFailed):
        await _service(store)._probe(_settings(), binding=None)

    assert store.object_exists is True
    assert store.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_upload", [False, True])
async def test_probe_preserves_external_cancellation_after_cleanup(
    fail_upload: bool,
) -> None:
    store = _ExternallyCancelledStore(fail_upload=fail_upload)
    probe = asyncio.create_task(_service(store)._probe(_settings(), binding=None))
    await store.upload_started.wait()

    probe.cancel()
    store.release_upload.set()

    with pytest.raises(asyncio.CancelledError):
        await probe

    assert store.object_exists is False
    assert store.cleanup_complete is True
    assert store.closed is True


@pytest.mark.asyncio
async def test_connection_database_failure_uses_typed_contract() -> None:
    with pytest.raises(ObjectStoreConnectionDatabaseUnavailable):
        await _service(_DelayedUploadStore(), _UnavailableDatabase()).get()
