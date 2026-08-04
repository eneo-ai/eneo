from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, TypeVar, cast
from urllib.parse import urlparse
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.object_store_connection_table import ObjectStoreConnections
from eneo.object_content.configuration import (
    ObjectContentCoreSettings,
    ObjectContentSettings,
    ObjectStoreOperatorSettings,
)
from eneo.object_content.content import capture_content
from eneo.object_content.reconciliation_repository import (
    ObjectContentReconciliationRepository,
    StoreBindingSnapshot,
)
from eneo.object_content.s3_object_store import (
    ObjectStoreBindingError,
    ObjectStoreFailureKind,
    ObjectStoreIntegrityError,
    ObjectStoreUnavailableError,
    S3ObjectStore,
    classify_object_store_failure,
    new_object_key,
)
from eneo.settings.encryption_service import EncryptionService

_PROBE_BODY = b"eneo-object-store-connection-probe-v1\n"
_PROBE_MEDIA_TYPE = "application/octet-stream"
_PROBE_REQUEST_TIMEOUT_SECONDS = 15.0
_PROBE_END_TO_END_TIMEOUT_SECONDS = 45.0
_PROBE_DELETE_TIMEOUT_SECONDS = 10
_ResultT = TypeVar("_ResultT")


class ObjectStoreConnectionActor(StrEnum):
    MIGRATION = "migration"
    PLATFORM_ADMIN = "platform_admin"


class ObjectStoreConnectionSource(StrEnum):
    UNCONFIGURED = "unconfigured"
    ENVIRONMENT = "environment"
    ADMIN = "admin"


class ObjectStoreConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint_url: str = Field(min_length=1, max_length=2048)
    region: str = Field(min_length=1, max_length=128)
    bucket: str = Field(min_length=3, max_length=63)
    access_key_id: SecretStr
    secret_access_key: SecretStr
    addressing_style: Literal["path", "virtual"] = "path"


class ObjectStoreCredentialRotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    access_key_id: SecretStr
    secret_access_key: SecretStr


@dataclass(frozen=True, slots=True)
class StoredObjectStoreConnection:
    revision: int
    endpoint_url: str
    region: str
    bucket: str
    access_key_id_encrypted: str
    secret_access_key_encrypted: str
    deployment_id: UUID
    addressing_style: Literal["path", "virtual"]
    updated_by_actor: ObjectStoreConnectionActor
    updated_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ObjectStoreConnectionError(RuntimeError):
    code = "object_store_connection_error"


class ObjectStoreConnectionNotConfigured(ObjectStoreConnectionError):
    code = "object_store_connection_not_configured"


class ObjectStoreConnectionAlreadyConfigured(ObjectStoreConnectionError):
    code = "object_store_connection_already_configured"


class ObjectStoreDestinationAlreadyBound(ObjectStoreConnectionError):
    code = "object_store_destination_already_bound"


class ObjectStoreConnectionConflict(ObjectStoreConnectionError):
    code = "object_store_connection_revision_conflict"


class ObjectStoreConnectionInvalid(ObjectStoreConnectionError):
    code = "object_store_connection_invalid"


class ObjectStorePlainHttpNotPermitted(ObjectStoreConnectionInvalid):
    code = "object_store_plain_http_not_permitted"


class ObjectStoreEndpointNotPermitted(ObjectStoreConnectionInvalid):
    code = "object_store_endpoint_not_permitted"


class ObjectStoreCredentialEncryptionUnavailable(ObjectStoreConnectionError):
    code = "object_store_credential_encryption_unavailable"


class ObjectStoreCredentialDataInvalid(ObjectStoreConnectionError):
    code = "object_store_credential_data_invalid"


class ObjectStoreConnectionDatabaseUnavailable(ObjectStoreConnectionError):
    code = "object_store_connection_database_unavailable"


class ObjectStoreConnectionMutationOutcomeUnknown(ObjectStoreConnectionError):
    code = "object_store_connection_mutation_outcome_unknown"


class ObjectStoreProbeAuthenticationFailed(ObjectStoreConnectionError):
    code = "object_store_probe_authentication_failed"


class ObjectStoreProbeTlsFailed(ObjectStoreConnectionError):
    code = "object_store_probe_tls_failed"


class ObjectStoreProbeConnectionFailed(ObjectStoreConnectionError):
    code = "object_store_probe_connection_failed"


class ObjectStoreProbeUnavailable(ObjectStoreConnectionError):
    code = "object_store_probe_unavailable"


class ObjectStoreProbeBindingMismatch(ObjectStoreConnectionError):
    code = "object_store_probe_binding_mismatch"


class ObjectStoreProbeIntegrityFailed(ObjectStoreConnectionError):
    code = "object_store_probe_integrity_failed"


class ObjectStoreProbeCleanupFailed(ObjectStoreConnectionError):
    code = "object_store_probe_cleanup_failed"


def _stored(row: ObjectStoreConnections) -> StoredObjectStoreConnection:
    if row.addressing_style not in {"path", "virtual"}:
        raise ObjectStoreCredentialDataInvalid(
            "Stored object-store addressing style is invalid"
        )
    try:
        actor = ObjectStoreConnectionActor(row.updated_by_actor)
    except ValueError as error:
        raise ObjectStoreCredentialDataInvalid(
            "Stored object-store actor is invalid"
        ) from error
    return StoredObjectStoreConnection(
        revision=row.revision,
        endpoint_url=row.endpoint_url,
        region=row.region,
        bucket=row.bucket,
        access_key_id_encrypted=row.access_key_id_encrypted,
        secret_access_key_encrypted=row.secret_access_key_encrypted,
        deployment_id=row.deployment_id,
        addressing_style=cast(Literal["path", "virtual"], row.addressing_style),
        updated_by_actor=actor,
        updated_by_user_id=row.updated_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ObjectStoreConnectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> StoredObjectStoreConnection | None:
        row = await self._session.scalar(
            select(ObjectStoreConnections).where(ObjectStoreConnections.id == 1)
        )
        return _stored(row) if row is not None else None

    async def create(
        self,
        *,
        settings: ObjectContentSettings,
        access_key_id_encrypted: str,
        secret_access_key_encrypted: str,
        actor: ObjectStoreConnectionActor,
        actor_user_id: UUID | None,
    ) -> StoredObjectStoreConnection | None:
        row = await self._session.scalar(
            insert(ObjectStoreConnections)
            .values(
                id=1,
                revision=1,
                endpoint_url=settings.endpoint_url,
                region=settings.region,
                bucket=settings.bucket,
                access_key_id_encrypted=access_key_id_encrypted,
                secret_access_key_encrypted=secret_access_key_encrypted,
                deployment_id=settings.deployment_id,
                addressing_style=settings.addressing_style,
                updated_by_actor=actor.value,
                updated_by_user_id=actor_user_id,
            )
            .on_conflict_do_nothing(index_elements=[ObjectStoreConnections.id])
            .returning(ObjectStoreConnections)
        )
        if row is None:
            return None
        return _stored(row)

    async def import_if_absent(
        self,
        *,
        settings: ObjectContentSettings,
        access_key_id_encrypted: str,
        secret_access_key_encrypted: str,
    ) -> None:
        await self._session.execute(
            insert(ObjectStoreConnections)
            .values(
                id=1,
                revision=1,
                endpoint_url=settings.endpoint_url,
                region=settings.region,
                bucket=settings.bucket,
                access_key_id_encrypted=access_key_id_encrypted,
                secret_access_key_encrypted=secret_access_key_encrypted,
                deployment_id=settings.deployment_id,
                addressing_style=settings.addressing_style,
                updated_by_actor=ObjectStoreConnectionActor.MIGRATION.value,
                updated_by_user_id=None,
            )
            .on_conflict_do_nothing(index_elements=[ObjectStoreConnections.id])
        )

    async def rotate_credentials(
        self,
        *,
        expected_revision: int,
        access_key_id_encrypted: str,
        secret_access_key_encrypted: str,
        actor_user_id: UUID,
    ) -> StoredObjectStoreConnection:
        row = await self._session.scalar(
            update(ObjectStoreConnections)
            .where(
                ObjectStoreConnections.id == 1,
                ObjectStoreConnections.revision == expected_revision,
            )
            .values(
                revision=ObjectStoreConnections.revision + 1,
                access_key_id_encrypted=access_key_id_encrypted,
                secret_access_key_encrypted=secret_access_key_encrypted,
                updated_by_actor=ObjectStoreConnectionActor.PLATFORM_ADMIN.value,
                updated_by_user_id=actor_user_id,
                updated_at=func.now(),
            )
            .returning(ObjectStoreConnections)
        )
        if row is None:
            raise ObjectStoreConnectionConflict(
                "The object-store connection changed while it was being tested"
            )
        return _stored(row)


StoreFactory = Callable[[ObjectContentSettings], S3ObjectStore]


class ObjectStoreConnectionService:
    """Own encrypted persistence and candidate verification for one destination."""

    def __init__(
        self,
        *,
        database: DatabaseSessionManager,
        core_settings: ObjectContentCoreSettings,
        operator_settings: ObjectStoreOperatorSettings,
        encryption: EncryptionService,
        store_factory: StoreFactory = S3ObjectStore,
    ) -> None:
        self._database = database
        self._core_settings = core_settings
        self._operator_settings = operator_settings
        self._encryption = encryption
        self._store_factory = store_factory

    @property
    def credential_encryption_active(self) -> bool:
        return self._encryption.is_active()

    async def get(self) -> StoredObjectStoreConnection | None:
        async with self._transaction() as session:
            return await ObjectStoreConnectionRepository(session).get()

    async def create(
        self,
        candidate: ObjectStoreConnectionInput,
        *,
        actor_user_id: UUID,
    ) -> StoredObjectStoreConnection:
        self._require_encryption()
        async with self._transaction() as session:
            if await ObjectStoreConnectionRepository(session).get() is not None:
                raise ObjectStoreConnectionAlreadyConfigured(
                    "Object storage is already configured"
                )
            await self._require_unbound_destination(session)

        settings = self._settings(candidate, deployment_id=uuid4())
        await self._probe(settings, binding=None)

        access_key_id_encrypted = self._encryption.encrypt(
            candidate.access_key_id.get_secret_value()
        )
        secret_access_key_encrypted = self._encryption.encrypt(
            candidate.secret_access_key.get_secret_value()
        )
        async with self._transaction(mutation=True) as session:
            if await ObjectStoreConnectionRepository(session).get() is not None:
                raise ObjectStoreConnectionAlreadyConfigured(
                    "Object storage is already configured"
                )
            await self._require_unbound_destination(session)
            stored = await ObjectStoreConnectionRepository(session).create(
                settings=settings,
                access_key_id_encrypted=access_key_id_encrypted,
                secret_access_key_encrypted=secret_access_key_encrypted,
                actor=ObjectStoreConnectionActor.PLATFORM_ADMIN,
                actor_user_id=actor_user_id,
            )
            if stored is None:
                raise ObjectStoreConnectionAlreadyConfigured(
                    "Object storage is already configured"
                )
            return stored

    async def rotate_credentials(
        self,
        replacement: ObjectStoreCredentialRotation,
        *,
        actor_user_id: UUID,
    ) -> StoredObjectStoreConnection:
        self._require_encryption()
        async with self._transaction() as session:
            stored = await ObjectStoreConnectionRepository(session).get()
            if stored is None:
                raise ObjectStoreConnectionNotConfigured(
                    "Object storage is not managed in Admin"
                )
            binding = await ObjectContentReconciliationRepository(
                session
            ).store_binding_snapshot()
        if stored.revision != replacement.expected_revision:
            raise ObjectStoreConnectionConflict(
                "The object-store connection changed before rotation"
            )

        candidate = ObjectStoreConnectionInput(
            endpoint_url=stored.endpoint_url,
            region=stored.region,
            bucket=stored.bucket,
            access_key_id=replacement.access_key_id,
            secret_access_key=replacement.secret_access_key,
            addressing_style=stored.addressing_style,
        )
        settings = self._settings(candidate, deployment_id=stored.deployment_id)
        await self._probe(
            settings,
            binding=None if binding.unbound else binding,
        )

        async with self._transaction(mutation=True) as session:
            return await ObjectStoreConnectionRepository(session).rotate_credentials(
                expected_revision=replacement.expected_revision,
                access_key_id_encrypted=self._encryption.encrypt(
                    replacement.access_key_id.get_secret_value()
                ),
                secret_access_key_encrypted=self._encryption.encrypt(
                    replacement.secret_access_key.get_secret_value()
                ),
                actor_user_id=actor_user_id,
            )

    async def adopt_legacy(
        self,
        settings: ObjectContentSettings,
    ) -> StoredObjectStoreConnection | None:
        if not self._encryption.is_active():
            return None
        async with self._transaction() as session:
            binding = await ObjectContentReconciliationRepository(
                session
            ).store_binding_snapshot()
            if (
                binding.deployment_id is not None
                and binding.deployment_id != settings.deployment_id
            ):
                raise ObjectStoreDestinationAlreadyBound(
                    "Legacy object storage does not match PostgreSQL"
                )
            repository = ObjectStoreConnectionRepository(session)
            await repository.import_if_absent(
                settings=settings,
                access_key_id_encrypted=self._encryption.encrypt(
                    settings.access_key_id.get_secret_value()
                ),
                secret_access_key_encrypted=self._encryption.encrypt(
                    settings.secret_access_key.get_secret_value()
                ),
            )
            stored = await repository.get()
        if stored is None or not self._same_destination(stored, settings):
            raise ObjectStoreConnectionConflict(
                "Concurrent legacy object-store configuration did not match"
            )
        return stored

    @asynccontextmanager
    async def _transaction(
        self,
        *,
        mutation: bool = False,
    ) -> AsyncGenerator[AsyncSession]:
        body_completed = False
        try:
            async with self._database.session() as session, session.begin():
                yield session
                body_completed = True
        except ObjectStoreConnectionError:
            raise
        except (OSError, SQLAlchemyError) as error:
            if mutation and body_completed:
                raise ObjectStoreConnectionMutationOutcomeUnknown(
                    "The database could not confirm whether the change was committed"
                ) from error
            raise ObjectStoreConnectionDatabaseUnavailable(
                "Object-store connection data is temporarily unavailable"
            ) from error

    def settings_for(
        self,
        stored: StoredObjectStoreConnection,
    ) -> ObjectContentSettings:
        self._require_encryption()
        for encrypted in (
            stored.access_key_id_encrypted,
            stored.secret_access_key_encrypted,
        ):
            if not self._encryption.is_encrypted(encrypted):
                raise ObjectStoreCredentialDataInvalid(
                    "Stored object-store credentials are not encrypted"
                )
        try:
            access_key_id = self._encryption.decrypt(stored.access_key_id_encrypted)
            secret_access_key = self._encryption.decrypt(
                stored.secret_access_key_encrypted
            )
        except (ValueError, RuntimeError) as error:
            raise ObjectStoreCredentialDataInvalid(
                "Stored object-store credentials cannot be decrypted"
            ) from error
        return self._settings(
            ObjectStoreConnectionInput(
                endpoint_url=stored.endpoint_url,
                region=stored.region,
                bucket=stored.bucket,
                access_key_id=SecretStr(access_key_id),
                secret_access_key=SecretStr(secret_access_key),
                addressing_style=stored.addressing_style,
            ),
            deployment_id=stored.deployment_id,
            operator_supplied_endpoint=(
                stored.updated_by_actor is ObjectStoreConnectionActor.MIGRATION
            ),
        )

    async def _require_unbound_destination(self, session: AsyncSession) -> None:
        binding = await ObjectContentReconciliationRepository(
            session
        ).store_binding_snapshot()
        if binding.binding_id is not None:
            raise ObjectStoreDestinationAlreadyBound(
                "This installation is already bound to an object-store destination"
            )

    def _settings(
        self,
        candidate: ObjectStoreConnectionInput,
        *,
        deployment_id: UUID,
        operator_supplied_endpoint: bool = False,
    ) -> ObjectContentSettings:
        if (
            not operator_supplied_endpoint
            and not self._operator_settings.permits_admin_endpoint(
                candidate.endpoint_url
            )
        ):
            raise ObjectStoreEndpointNotPermitted(
                "The object-store endpoint is not permitted by deployment policy"
            )
        if (
            urlparse(candidate.endpoint_url).scheme == "http"
            and not self._operator_settings.allow_insecure_http
        ):
            raise ObjectStorePlainHttpNotPermitted(
                "This deployment does not permit plain HTTP object storage"
            )
        values = {
            **self._core_settings.model_dump(),
            **self._operator_settings.model_dump(),
            **candidate.model_dump(),
            "deployment_id": deployment_id,
        }
        try:
            return ObjectContentSettings.model_validate(values)
        except ValidationError as error:
            raise ObjectStoreConnectionInvalid(
                "The object-store connection settings are invalid"
            ) from error

    async def _probe(
        self,
        settings: ObjectContentSettings,
        *,
        binding: StoreBindingSnapshot | None,
    ) -> None:
        probe_settings = ObjectContentSettings.model_validate(
            {
                **settings.model_dump(),
                "connect_timeout_seconds": _PROBE_REQUEST_TIMEOUT_SECONDS,
                "read_timeout_seconds": _PROBE_REQUEST_TIMEOUT_SECONDS,
                "sdk_max_attempts": 1,
                "readiness_timeout_seconds": _PROBE_REQUEST_TIMEOUT_SECONDS,
                "readiness_max_attempts": 1,
                "binding_claim_seconds": max(
                    settings.binding_claim_seconds,
                    int(_PROBE_END_TO_END_TIMEOUT_SECONDS),
                ),
                "delete_visibility_timeout_seconds": _PROBE_DELETE_TIMEOUT_SECONDS,
            }
        )
        store = self._store_factory(probe_settings)
        key = new_object_key(probe_settings)
        upload_attempted = False
        primary_error: BaseException | None = None
        try:
            async with asyncio.timeout(_PROBE_END_TO_END_TIMEOUT_SECONDS):
                if binding is None:
                    await store.prepare_binding_creation(uuid4())
                else:
                    await store.check_ready()
                    if (
                        binding.deployment_id != probe_settings.deployment_id
                        or binding.binding_id is None
                        or not binding.confirmed
                        or not await store.verify_binding(binding.binding_id)
                    ):
                        raise ObjectStoreBindingError(
                            "Object storage does not match PostgreSQL"
                        )

                async with capture_content(
                    _probe_chunks(),
                    declared_media_type=_PROBE_MEDIA_TYPE,
                    verified_media_type=_PROBE_MEDIA_TYPE,
                    maximum_size_bytes=len(_PROBE_BODY),
                    spool_memory_bytes=probe_settings.spool_memory_bytes,
                    multipart_part_bytes=probe_settings.multipart_part_bytes,
                ) as captured:
                    upload_attempted = True
                    await _await_quiescent(store.upload(key, captured))
                    async with store.open_verified_read(
                        key,
                        expected_sha256=captured.sha256,
                        expected_size_bytes=captured.size_bytes,
                        expected_media_type=captured.verified_media_type,
                    ) as opened:
                        observed = b"".join([chunk async for chunk in opened.chunks])
                    if observed != _PROBE_BODY:
                        raise ObjectStoreIntegrityError(
                            "Object-store probe read returned different bytes"
                        )
        except BaseException as error:
            primary_error = error
        finally:
            try:
                if upload_attempted:
                    try:
                        await _await_quiescent(store.delete_and_confirm(key))
                    except (
                        ObjectStoreUnavailableError,
                        ObjectStoreIntegrityError,
                    ):
                        primary_error = ObjectStoreProbeCleanupFailed(
                            "Object-store probe cleanup could not be confirmed"
                        )
                if binding is None and primary_error is None:
                    try:
                        await store.prepare_binding_creation(uuid4())
                    except (
                        ObjectStoreUnavailableError,
                        ObjectStoreIntegrityError,
                    ) as error:
                        primary_error = error
            finally:
                await store.close()

        if primary_error is not None:
            self._raise_probe_error(primary_error)

    @staticmethod
    def _raise_probe_error(error: BaseException) -> None:
        if isinstance(error, asyncio.CancelledError):
            raise error
        if isinstance(error, ObjectStoreConnectionError):
            raise error
        if isinstance(error, ObjectStoreBindingError):
            raise ObjectStoreProbeBindingMismatch(
                "Object storage is bound to another Eneo installation"
            ) from error
        if isinstance(error, ObjectStoreIntegrityError):
            raise ObjectStoreProbeIntegrityFailed(
                "Object storage did not preserve the probe bytes"
            ) from error
        if isinstance(error, TimeoutError):
            raise ObjectStoreProbeConnectionFailed(
                "Object storage did not respond before the probe deadline"
            ) from error
        if isinstance(error, ObjectStoreUnavailableError):
            kind = classify_object_store_failure(error)
            if kind is ObjectStoreFailureKind.AUTHENTICATION:
                raise ObjectStoreProbeAuthenticationFailed(
                    "Object-storage authentication or permission check failed"
                ) from error
            if kind is ObjectStoreFailureKind.TLS:
                raise ObjectStoreProbeTlsFailed(
                    "Object-storage TLS verification failed"
                ) from error
            if kind is ObjectStoreFailureKind.CONNECTION:
                raise ObjectStoreProbeConnectionFailed(
                    "Object storage could not be reached"
                ) from error
        raise ObjectStoreProbeUnavailable(
            "Object storage could not complete the connection probe"
        ) from error

    def _require_encryption(self) -> None:
        if not self._encryption.is_active():
            raise ObjectStoreCredentialEncryptionUnavailable(
                "Credential encryption is not configured"
            )

    @staticmethod
    def _same_destination(
        stored: StoredObjectStoreConnection,
        settings: ObjectContentSettings,
    ) -> bool:
        return (
            stored.endpoint_url == settings.endpoint_url
            and stored.region == settings.region
            and stored.bucket == settings.bucket
            and stored.deployment_id == settings.deployment_id
            and stored.addressing_style == settings.addressing_style
        )


async def _probe_chunks() -> AsyncGenerator[bytes]:
    yield _PROBE_BODY


async def _await_quiescent(operation: Awaitable[_ResultT]) -> _ResultT:
    """Delay cancellation until a blocking SDK mutation has stopped running."""
    task = asyncio.ensure_future(operation)
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if cancellation is None:
                cancellation = error
            continue
        except BaseException:
            if cancellation is not None:
                raise cancellation
            raise
        if cancellation is not None:
            raise cancellation
        return result
    if cancellation is not None:
        try:
            task.result()
        except BaseException:
            pass
        raise cancellation
    return task.result()
