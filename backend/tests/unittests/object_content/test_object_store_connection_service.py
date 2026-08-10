import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from botocore.exceptions import ClientError
from cryptography.fernet import Fernet
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import DatabaseSessionManager
from eneo.object_content.configuration import (
    ObjectContentCoreSettings,
    ObjectContentSettings,
    ObjectStoreOperatorSettings,
)
from eneo.object_content.content import CapturedContent, ContentRead
from eneo.object_content.object_store_connection import (
    ObjectStoreConnectionActor,
    ObjectStoreConnectionDatabaseUnavailable,
    ObjectStoreConnectionInput,
    ObjectStoreConnectionMutationOutcomeUnknown,
    ObjectStoreConnectionRepository,
    ObjectStoreConnectionService,
    ObjectStoreCredentialRotation,
    ObjectStoreProbeAuthenticationFailed,
    ObjectStoreProbeCleanupFailed,
    ObjectStoreProbeConnectionFailed,
    ObjectStoreProbeUnavailable,
    StoredObjectStoreConnection,
)
from eneo.object_content.s3_object_store import (
    ObjectStoreProbeCleanupError,
    ObjectStoreUnavailableError,
    S3ObjectStore,
)
from eneo.object_content.store_binding import (
    StoreBindingRepository,
    StoreBindingSnapshot,
)
from eneo.settings.encryption_service import EncryptionService


class _DelayedUploadStore:
    def __init__(self) -> None:
        self.object_exists = False
        self.closed = False

    async def probe_binding_creation(self) -> None:
        return None

    async def check_ready(self) -> None:
        return None

    async def upload(self, _key: str, _content: CapturedContent) -> None:
        await asyncio.sleep(0.05)
        self.object_exists = True

    async def delete_and_confirm(self, _key: str) -> None:
        self.object_exists = False

    async def close(self) -> None:
        self.closed = True


class _ListDeniedStore(_DelayedUploadStore):
    def __init__(self) -> None:
        super().__init__()
        self.readiness_checks = 0

    async def check_ready(self) -> None:
        self.readiness_checks += 1
        raise ObjectStoreUnavailableError("list permission denied")


class _AuthenticationDeniedStore(_DelayedUploadStore):
    async def check_ready(self) -> None:
        try:
            raise ClientError(
                {
                    "Error": {"Code": "AccessDenied"},
                    "ResponseMetadata": {"HTTPStatusCode": 403},
                },
                "ListObjectsV2",
            )
        except ClientError as error:
            raise ObjectStoreUnavailableError("authentication denied") from error


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


class _CancelledBindingCleanupStore(_DelayedUploadStore):
    def __init__(self) -> None:
        super().__init__()
        self.probe_started = asyncio.Event()
        self.release_probe = asyncio.Event()

    async def probe_binding_creation(self) -> None:
        self.probe_started.set()
        await self.release_probe.wait()
        raise ObjectStoreProbeCleanupError("binding probe cleanup failed")


class _ConditionalBindingRejectedStore(_DelayedUploadStore):
    def __init__(self) -> None:
        super().__init__()
        self.payload = b""
        self.binding_write_attempted = False

    async def probe_binding_creation(self) -> None:
        self.binding_write_attempted = True
        raise ObjectStoreUnavailableError("conditional writes are not supported")

    async def upload(self, _key: str, content: CapturedContent) -> None:
        self.payload = content.file.read()
        self.object_exists = True

    @asynccontextmanager
    async def open_verified_read(
        self,
        _key: str,
        *,
        expected_size_bytes: int,
        expected_media_type: str,
        **_kwargs: object,
    ) -> AsyncGenerator[ContentRead]:
        async def chunks() -> AsyncGenerator[bytes]:
            yield self.payload

        stream = chunks()
        try:
            yield ContentRead(
                chunks=stream,
                content_length=expected_size_bytes,
                media_type=expected_media_type,
                content_range=None,
            )
        finally:
            await stream.aclose()


class _UnavailableDatabase:
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        raise SQLAlchemyError("database unavailable")
        yield cast(AsyncSession, None)


class _SequencedCommitFailureSession:
    def __init__(self, database: "_SequencedCommitFailureDatabase") -> None:
        self._database = database

    @asynccontextmanager
    async def begin(self) -> AsyncGenerator[None]:
        self._database.transactions += 1
        transaction = self._database.transactions
        yield
        if transaction == self._database.fail_transaction:
            raise SQLAlchemyError("commit outcome is unknown")


class _SequencedCommitFailureDatabase:
    def __init__(self, *, fail_transaction: int | None = None) -> None:
        self.fail_transaction = fail_transaction
        self.transactions = 0

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        yield cast(AsyncSession, _SequencedCommitFailureSession(self))


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


def _stored_connection() -> StoredObjectStoreConnection:
    now = datetime.now(UTC)
    return StoredObjectStoreConnection(
        revision=1,
        endpoint_url="https://objects.example.test",
        region="se-1",
        bucket="eneo-content",
        access_key_id_encrypted="encrypted-access",
        secret_access_key_encrypted="encrypted-secret",
        deployment_id=_settings().deployment_id,
        addressing_style="path",
        updated_by_actor=ObjectStoreConnectionActor.STORAGE_ADMIN,
        updated_by_user_id=None,
        created_at=now,
        updated_at=now,
    )


def _service(
    store: object,
    database: object = object(),
    *,
    operator_settings: ObjectStoreOperatorSettings | None = None,
) -> ObjectStoreConnectionService:
    return ObjectStoreConnectionService(
        database=cast(DatabaseSessionManager, database),
        core_settings=ObjectContentCoreSettings(_env_file=None),
        operator_settings=operator_settings
        or ObjectStoreOperatorSettings(_env_file=None),
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
async def test_binding_probe_cleanup_does_not_replace_external_cancellation() -> None:
    store = _CancelledBindingCleanupStore()
    probe = asyncio.create_task(_service(store)._probe(_settings(), binding=None))
    await store.probe_started.wait()

    probe.cancel()
    store.release_probe.set()

    with pytest.raises(asyncio.CancelledError):
        await probe

    assert store.closed is True


@pytest.mark.asyncio
async def test_binding_probe_cleanup_failure_wins_after_internal_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _CancelledBindingCleanupStore()
    monkeypatch.setattr(
        "eneo.object_content.object_store_connection._PROBE_END_TO_END_TIMEOUT_SECONDS",
        0.01,
    )
    probe = asyncio.create_task(_service(store)._probe(_settings(), binding=None))
    await store.probe_started.wait()
    await asyncio.sleep(0.02)
    store.release_probe.set()

    with pytest.raises(ObjectStoreProbeCleanupFailed):
        await probe

    assert store.closed is True


@pytest.mark.asyncio
async def test_connection_is_not_saved_when_conditional_binding_write_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored_connection()
    store = _ConditionalBindingRejectedStore()
    database = _SequencedCommitFailureDatabase()
    service = _service(
        store,
        database,
        operator_settings=ObjectStoreOperatorSettings(
            _env_file=None,
        ),
    )
    persistence_attempted = False

    async def no_connection(
        _repository: ObjectStoreConnectionRepository,
    ) -> StoredObjectStoreConnection | None:
        return None

    async def unbound_snapshot(
        _repository: StoreBindingRepository,
    ) -> StoreBindingSnapshot:
        return StoreBindingSnapshot(None, None, False)

    async def persist_connection(
        _repository: ObjectStoreConnectionRepository,
        **_kwargs: object,
    ) -> StoredObjectStoreConnection:
        nonlocal persistence_attempted
        persistence_attempted = True
        return stored

    monkeypatch.setattr(ObjectStoreConnectionRepository, "get", no_connection)
    monkeypatch.setattr(
        StoreBindingRepository,
        "snapshot",
        unbound_snapshot,
    )
    monkeypatch.setattr(ObjectStoreConnectionRepository, "create", persist_connection)

    with pytest.raises(ObjectStoreProbeUnavailable):
        await service.create(
            ObjectStoreConnectionInput(
                endpoint_url=stored.endpoint_url,
                region=stored.region,
                bucket=stored.bucket,
                access_key_id="access",
                secret_access_key="secret",
            ),
            actor_user_id=stored.deployment_id,
        )

    assert store.binding_write_attempted is True
    assert persistence_attempted is False
    assert database.transactions == 1


@pytest.mark.asyncio
async def test_probe_caps_preserve_valid_operator_timeout_relationships() -> None:
    store = _ConditionalBindingRejectedStore()
    observed_settings: ObjectContentSettings | None = None

    def store_factory(settings: ObjectContentSettings) -> S3ObjectStore:
        nonlocal observed_settings
        observed_settings = settings
        return cast(S3ObjectStore, store)

    service = ObjectStoreConnectionService(
        database=cast(DatabaseSessionManager, object()),
        core_settings=ObjectContentCoreSettings(_env_file=None),
        operator_settings=ObjectStoreOperatorSettings(_env_file=None),
        encryption=EncryptionService(Fernet.generate_key().decode()),
        store_factory=store_factory,
    )
    settings = ObjectContentSettings.model_validate(
        {
            **_settings().model_dump(),
            "connect_timeout_seconds": 1.0,
            "read_timeout_seconds": 1.0,
            "sdk_max_attempts": 1,
            "reconciliation_lease_seconds": 7,
            "delete_visibility_timeout_seconds": 30,
            "delete_poll_interval_seconds": 20.0,
        }
    )

    with pytest.raises(ObjectStoreProbeUnavailable):
        await service._probe(settings, binding=None)

    assert observed_settings is not None
    assert observed_settings.connect_timeout_seconds == 1.0
    assert observed_settings.read_timeout_seconds == 1.0
    assert observed_settings.delete_visibility_timeout_seconds == 10
    assert observed_settings.delete_poll_interval_seconds == 10


@pytest.mark.asyncio
async def test_unbound_rotation_keeps_probe_bounds_and_authentication_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored_connection()
    observed_settings: ObjectContentSettings | None = None
    store = _AuthenticationDeniedStore()

    def store_factory(settings: ObjectContentSettings) -> S3ObjectStore:
        nonlocal observed_settings
        observed_settings = settings
        return cast(S3ObjectStore, store)

    service = ObjectStoreConnectionService(
        database=cast(DatabaseSessionManager, _SequencedCommitFailureDatabase()),
        core_settings=ObjectContentCoreSettings(_env_file=None),
        operator_settings=ObjectStoreOperatorSettings(
            _env_file=None,
        ),
        encryption=EncryptionService(Fernet.generate_key().decode()),
        store_factory=store_factory,
    )

    async def get_connection(
        _repository: ObjectStoreConnectionRepository,
    ) -> StoredObjectStoreConnection:
        return stored

    async def unbound_snapshot(
        _repository: StoreBindingRepository,
    ) -> StoreBindingSnapshot:
        return StoreBindingSnapshot(None, None, False)

    monkeypatch.setattr(ObjectStoreConnectionRepository, "get", get_connection)
    monkeypatch.setattr(
        StoreBindingRepository,
        "snapshot",
        unbound_snapshot,
    )

    with pytest.raises(ObjectStoreProbeAuthenticationFailed):
        await service.rotate_credentials(
            ObjectStoreCredentialRotation(
                expected_revision=stored.revision,
                access_key_id="replacement-access",
                secret_access_key="replacement-secret",
            ),
            actor_user_id=stored.deployment_id,
        )

    assert observed_settings is not None
    assert observed_settings.connect_timeout_seconds == 5
    assert observed_settings.read_timeout_seconds == 15
    assert observed_settings.sdk_max_attempts == 1
    assert observed_settings.readiness_timeout_seconds == 2
    assert observed_settings.readiness_max_attempts == 1


@pytest.mark.asyncio
async def test_connection_database_failure_uses_typed_contract() -> None:
    with pytest.raises(ObjectStoreConnectionDatabaseUnavailable):
        await _service(_DelayedUploadStore(), _UnavailableDatabase()).get()


@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "rotate"])
async def test_admin_mutations_report_unknown_commit_outcome(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    stored = _stored_connection()
    database = _SequencedCommitFailureDatabase(fail_transaction=2)
    service = _service(
        _DelayedUploadStore(),
        database,
        operator_settings=ObjectStoreOperatorSettings(
            _env_file=None,
        ),
    )

    async def get_connection(
        _repository: ObjectStoreConnectionRepository,
    ) -> StoredObjectStoreConnection | None:
        return stored if operation == "rotate" else None

    async def unbound_snapshot(
        _repository: StoreBindingRepository,
    ) -> StoreBindingSnapshot:
        if operation == "rotate":
            return StoreBindingSnapshot(
                stored.deployment_id,
                stored.deployment_id,
                True,
            )
        return StoreBindingSnapshot(None, None, False)

    async def probe_succeeds(*_args: object, **_kwargs: object) -> None:
        return None

    async def create_connection(
        _repository: ObjectStoreConnectionRepository,
        **_kwargs: object,
    ) -> StoredObjectStoreConnection:
        return stored

    async def rotate_connection(
        _repository: ObjectStoreConnectionRepository,
        **_kwargs: object,
    ) -> StoredObjectStoreConnection:
        return stored

    monkeypatch.setattr(ObjectStoreConnectionRepository, "get", get_connection)
    monkeypatch.setattr(ObjectStoreConnectionRepository, "create", create_connection)
    monkeypatch.setattr(
        ObjectStoreConnectionRepository,
        "rotate_credentials",
        rotate_connection,
    )
    monkeypatch.setattr(
        StoreBindingRepository,
        "snapshot",
        unbound_snapshot,
    )
    monkeypatch.setattr(service, "_probe", probe_succeeds)

    with pytest.raises(ObjectStoreConnectionMutationOutcomeUnknown):
        if operation == "create":
            await service.create(
                ObjectStoreConnectionInput(
                    endpoint_url=stored.endpoint_url,
                    region=stored.region,
                    bucket=stored.bucket,
                    access_key_id="access",
                    secret_access_key="secret",
                ),
                actor_user_id=stored.deployment_id,
            )
        else:
            await service.rotate_credentials(
                ObjectStoreCredentialRotation(
                    expected_revision=stored.revision,
                    access_key_id="access",
                    secret_access_key="secret",
                ),
                actor_user_id=stored.deployment_id,
            )

    assert database.transactions == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "rotate"])
async def test_admin_connection_requires_bucket_readiness_before_persistence(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    stored = _stored_connection()
    store = _ListDeniedStore()
    database = _SequencedCommitFailureDatabase()
    service = _service(
        store,
        database,
        operator_settings=ObjectStoreOperatorSettings(
            _env_file=None,
        ),
    )
    persistence_attempted = False

    async def get_connection(
        _repository: ObjectStoreConnectionRepository,
    ) -> StoredObjectStoreConnection | None:
        return None if operation == "create" else stored

    async def binding_snapshot(
        _repository: StoreBindingRepository,
    ) -> StoreBindingSnapshot:
        if operation == "create":
            return StoreBindingSnapshot(None, None, False)
        return StoreBindingSnapshot(
            stored.deployment_id,
            UUID("86a18657-8af1-4b6b-8e90-b78e6b41e7cb"),
            True,
        )

    async def persist_rotation(
        _repository: ObjectStoreConnectionRepository,
        **_kwargs: object,
    ) -> StoredObjectStoreConnection:
        nonlocal persistence_attempted
        persistence_attempted = True
        return stored

    monkeypatch.setattr(ObjectStoreConnectionRepository, "get", get_connection)
    monkeypatch.setattr(
        StoreBindingRepository,
        "snapshot",
        binding_snapshot,
    )
    monkeypatch.setattr(
        ObjectStoreConnectionRepository,
        "create" if operation == "create" else "rotate_credentials",
        persist_rotation,
    )

    with pytest.raises(ObjectStoreProbeUnavailable):
        if operation == "create":
            await service.create(
                ObjectStoreConnectionInput(
                    endpoint_url=stored.endpoint_url,
                    region=stored.region,
                    bucket=stored.bucket,
                    access_key_id="access",
                    secret_access_key="secret",
                ),
                actor_user_id=stored.deployment_id,
            )
        else:
            await service.rotate_credentials(
                ObjectStoreCredentialRotation(
                    expected_revision=stored.revision,
                    access_key_id="replacement-access",
                    secret_access_key="replacement-secret",
                ),
                actor_user_id=stored.deployment_id,
            )

    assert store.readiness_checks == 1
    assert persistence_attempted is False
    assert stored.revision == 1
    assert stored.access_key_id_encrypted == "encrypted-access"
    assert stored.secret_access_key_encrypted == "encrypted-secret"
