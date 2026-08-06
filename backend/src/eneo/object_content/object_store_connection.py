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
from eneo.database.tables.object_content_policy_table import (
    ObjectContentDeploymentPolicy,
)
from eneo.database.tables.object_content_table import (
    ObjectContentMoves,
    ObjectContentMultipartCandidates,
    ObjectContentOrphanCandidates,
    ObjectContents,
)
from eneo.database.tables.object_store_connection_table import (
    ACTIVE_DESTINATION_SLOT,
    TEMPORARY_DESTINATION_SLOT,
    ObjectStoreConnections,
)
from eneo.object_content.configuration import (
    ObjectContentCoreSettings,
    ObjectContentSettings,
    ObjectStoreOperatorSettings,
)
from eneo.object_content.content import (
    ObjectContentConfigurationError,
    ObjectContentUnavailableError,
    capture_content,
)
from eneo.object_content.reconciliation_repository import (
    ObjectContentReconciliationRepository,
)
from eneo.object_content.s3_object_store import (
    ObjectStoreBindingError,
    ObjectStoreFailureKind,
    ObjectStoreIntegrityError,
    ObjectStoreProbeCleanupError,
    ObjectStoreUnavailableError,
    S3ObjectStore,
    classify_object_store_failure,
    new_object_key,
)
from eneo.object_content.store_binding import (
    StoreBindingRepository,
    StoreBindingSnapshot,
    ensure_store_binding_ready,
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


@dataclass(frozen=True, slots=True)
class DestinationSwitch:
    """Both destination projections as they were committed together.

    The router answers from this result, so a successful switch is never
    reported as a failure because a later read could not reach the database.
    """

    active: StoredObjectStoreConnection
    previous: StoredObjectStoreConnection


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


class ObjectStoreDestinationSwitchBlocked(ObjectStoreConnectionError):
    """Remote work is still in flight; the administrator waits and retries."""

    code = "object_store_destination_switch_blocked"


class ObjectStoreNewWritesNotRedirected(ObjectStoreConnectionError):
    """New writes still target object storage; the administrator must act."""

    code = "object_store_new_writes_not_redirected"


class ObjectStorePreviousDestinationMissing(ObjectStoreConnectionError):
    code = "object_store_previous_destination_missing"


class ObjectStoreConnectionInvalid(ObjectStoreConnectionError):
    code = "object_store_connection_invalid"


class ObjectStorePlainHttpNotPermitted(ObjectStoreConnectionInvalid):
    code = "object_store_plain_http_not_permitted"


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
            select(ObjectStoreConnections).where(
                ObjectStoreConnections.id == ACTIVE_DESTINATION_SLOT
            )
        )
        return _stored(row) if row is not None else None

    async def get_previous(self) -> StoredObjectStoreConnection | None:
        row = await self._session.scalar(
            select(ObjectStoreConnections).where(
                ObjectStoreConnections.id == TEMPORARY_DESTINATION_SLOT
            )
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

    async def get_previous(self) -> StoredObjectStoreConnection | None:
        """Return the archived previous destination, if a switch kept one."""
        async with self._transaction() as session:
            return await ObjectStoreConnectionRepository(session).get_previous()

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
            binding = await StoreBindingRepository(session).snapshot()
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
        if not binding.confirmed:
            probe_settings = self._probe_settings(settings)
            store = self._store_factory(probe_settings)
            try:
                await ensure_store_binding_ready(
                    self._database,
                    probe_settings,
                    store,
                )
            except BaseException as error:
                self._raise_probe_error(error)
            finally:
                await store.close()
            async with self._transaction() as session:
                binding = await StoreBindingRepository(session).snapshot()
        await self._probe(settings, binding=binding)

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
            binding = await StoreBindingRepository(session).snapshot()
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

    async def replace_destination(
        self,
        candidate: ObjectStoreConnectionInput,
        *,
        actor_user_id: UUID,
    ) -> DestinationSwitch:
        """Switch the deployment to a destination the operator already filled.

        The operator copies the content namespace to the new bucket first
        (see the migration guide); this operation owns the safety around
        that copy: cheap preconditions proving no write can be in flight, a
        probe of the new destination, marker admission that refuses a bucket
        paired with another installation, and one fenced transaction that
        archives the previous destination for switch-back. Nothing is
        deleted anywhere; the switch is reversible while the previous
        destination record is kept.
        """
        self._require_encryption()
        async with self._transaction() as session:
            stored = await ObjectStoreConnectionRepository(session).get()
            binding = await StoreBindingRepository(session).snapshot()
        if stored is None:
            raise ObjectStoreConnectionNotConfigured(
                "Object storage is not managed in Admin"
            )
        if (
            candidate.endpoint_url == stored.endpoint_url
            and candidate.bucket == stored.bucket
        ):
            raise ObjectStoreConnectionInvalid(
                "The new destination is the same as the current one"
            )
        return await self._switch(
            candidate,
            actor_user_id=actor_user_id,
            stored=stored,
            binding=binding,
        )

    async def switch_back(
        self,
        *,
        actor_user_id: UUID,
    ) -> DestinationSwitch:
        """Return to the archived previous destination with its stored keys."""
        self._require_encryption()
        async with self._transaction() as session:
            stored = await ObjectStoreConnectionRepository(session).get()
            previous = await ObjectStoreConnectionRepository(session).get_previous()
            binding = await StoreBindingRepository(session).snapshot()
        if stored is None:
            raise ObjectStoreConnectionNotConfigured(
                "Object storage is not managed in Admin"
            )
        if previous is None:
            raise ObjectStorePreviousDestinationMissing(
                "There is no archived previous destination"
            )
        candidate = ObjectStoreConnectionInput(
            endpoint_url=previous.endpoint_url,
            region=previous.region,
            bucket=previous.bucket,
            access_key_id=SecretStr(
                self._encryption.decrypt(previous.access_key_id_encrypted)
            ),
            secret_access_key=SecretStr(
                self._encryption.decrypt(previous.secret_access_key_encrypted)
            ),
            addressing_style=previous.addressing_style,
        )
        return await self._switch(
            candidate,
            actor_user_id=actor_user_id,
            stored=stored,
            binding=binding,
        )

    async def forget_previous_destination(self, *, actor_user_id: UUID) -> None:
        """Drop the archived previous-destination record (bucket untouched)."""
        del actor_user_id  # authorization happens at the router boundary
        async with self._transaction(mutation=True) as session:
            row = await session.scalar(
                select(ObjectStoreConnections)
                .where(ObjectStoreConnections.id == TEMPORARY_DESTINATION_SLOT)
                .with_for_update()
            )
            if row is None:
                raise ObjectStorePreviousDestinationMissing(
                    "There is no archived previous destination"
                )
            await session.delete(row)

    async def _switch(
        self,
        candidate: ObjectStoreConnectionInput,
        *,
        actor_user_id: UUID,
        stored: StoredObjectStoreConnection,
        binding: StoreBindingSnapshot,
    ) -> DestinationSwitch:
        if not binding.confirmed or binding.binding_id is None:
            raise ObjectStoreDestinationSwitchBlocked(
                "The current destination has no established storage binding"
            )
        # Fast feedback before any remote work; re-checked under lock below.
        async with self._transaction() as session:
            await self._require_switchable(session)

        settings = self._settings(
            candidate,
            deployment_id=stored.deployment_id,
        )
        await self._admit_switch_target(settings, binding_id=binding.binding_id)

        access_key_id_encrypted = self._encryption.encrypt(
            candidate.access_key_id.get_secret_value()
        )
        secret_access_key_encrypted = self._encryption.encrypt(
            candidate.secret_access_key.get_secret_value()
        )
        async with self._transaction(mutation=True) as session:
            active = await session.scalar(
                select(ObjectStoreConnections)
                .where(ObjectStoreConnections.id == ACTIVE_DESTINATION_SLOT)
                .with_for_update()
            )
            if active is None or active.revision != stored.revision:
                raise ObjectStoreConnectionConflict(
                    "The object-store connection changed while it was being tested"
                )
            await self._require_switchable(session)

            previous = await session.scalar(
                select(ObjectStoreConnections)
                .where(ObjectStoreConnections.id == TEMPORARY_DESTINATION_SLOT)
                .with_for_update()
            )
            if previous is None:
                previous = ObjectStoreConnections()
                previous.id = TEMPORARY_DESTINATION_SLOT
                previous.revision = 1
                session.add(previous)
            else:
                previous.revision = previous.revision + 1
            previous.role = "retiring"
            previous.endpoint_url = active.endpoint_url
            previous.region = active.region
            previous.bucket = active.bucket
            previous.access_key_id_encrypted = active.access_key_id_encrypted
            previous.secret_access_key_encrypted = active.secret_access_key_encrypted
            previous.deployment_id = active.deployment_id
            previous.addressing_style = active.addressing_style
            previous.updated_by_actor = active.updated_by_actor
            previous.updated_by_user_id = active.updated_by_user_id

            active.endpoint_url = settings.endpoint_url
            active.region = settings.region
            active.bucket = settings.bucket
            active.access_key_id_encrypted = access_key_id_encrypted
            active.secret_access_key_encrypted = secret_access_key_encrypted
            active.addressing_style = settings.addressing_style
            active.revision = active.revision + 1
            active.updated_by_actor = ObjectStoreConnectionActor.PLATFORM_ADMIN.value
            active.updated_by_user_id = actor_user_id
            active.updated_at = func.now()

            # The old bucket's remote observations no longer describe the
            # active destination: restart both inventory cycles and drop the
            # cleanup candidates observed against it. The switch preconditions
            # proved none of those rows holds a live lease.
            await ObjectContentReconciliationRepository(
                session
            ).reset_remote_inventory()
            await session.flush()
            await session.refresh(active)
            await session.refresh(previous)
            return DestinationSwitch(
                active=_stored(active),
                previous=_stored(previous),
            )

    async def _require_switchable(self, session: AsyncSession) -> None:
        """Refuse the switch while any write could still reach a destination."""
        transient_remote = await session.scalar(
            select(func.count())
            .select_from(ObjectContents)
            .where(
                ObjectContents.storage_kind == "object_store",
                ObjectContents.state.in_(("pending", "delete_pending")),
            )
        )
        if transient_remote:
            raise ObjectStoreDestinationSwitchBlocked(
                "Remote content is still being written or deleted; let the "
                "worker finish first"
            )
        policy_target = await session.scalar(
            select(ObjectContentDeploymentPolicy.new_write_storage_target).where(
                ObjectContentDeploymentPolicy.id == 1
            )
        )
        if policy_target != "postgres_inline":
            raise ObjectStoreNewWritesNotRedirected(
                "Select PostgreSQL for new writes before switching destination"
            )
        nonterminal_moves = await session.scalar(
            select(func.count())
            .select_from(ObjectContentMoves)
            .where(ObjectContentMoves.state.in_(("pending", "target_verified")))
        )
        if nonterminal_moves:
            raise ObjectStoreDestinationSwitchBlocked(
                "Storage moves are still queued or running; wait for them or "
                "let them fail out first"
            )
        now = await session.scalar(select(func.now()))
        for table in (ObjectContentOrphanCandidates, ObjectContentMultipartCandidates):
            live_leases = await session.scalar(
                select(func.count())
                .select_from(table)
                .where(table.lease_owner.is_not(None), table.lease_until > now)
            )
            if live_leases:
                raise ObjectStoreDestinationSwitchBlocked(
                    "An upload or cleanup operation is still in flight; "
                    "try again shortly"
                )

    async def _admit_switch_target(
        self,
        settings: ObjectContentSettings,
        *,
        binding_id: UUID,
    ) -> None:
        """Admit a bucket that already holds this deployment's copied bytes.

        Unlike first-time creation, the content namespace is expected to be
        non-empty. A marker naming another installation is refused. For a
        bucket with no marker yet, every fallible check runs first and the
        permanent marker is written last, so a rejected switch never leaves
        the target paired to this installation.
        """
        probe_settings = self._probe_settings(settings)
        store = self._store_factory(probe_settings)
        try:
            try:
                marker_matches = await store.verify_binding(binding_id)
            except ObjectStoreBindingError as error:
                raise ObjectStoreProbeBindingMismatch(
                    "Object storage is bound to another Eneo installation"
                ) from error
            except ObjectStoreUnavailableError as error:
                self._raise_probe_error(error)
                raise
        finally:
            await store.close()

        if marker_matches:
            # Switch-back and retried switches: the pairing already exists, so
            # verify it as usual.
            await self._probe(
                settings,
                binding=StoreBindingSnapshot(
                    deployment_id=settings.deployment_id,
                    binding_id=binding_id,
                    confirmed=True,
                ),
            )
            return

        # Unmarked target: prove readiness and a complete write/read/delete
        # round trip before claiming the bucket.
        await self._probe(settings, binding=None)
        await self._create_switch_marker(probe_settings, binding_id=binding_id)

    async def _create_switch_marker(
        self,
        probe_settings: ObjectContentSettings,
        *,
        binding_id: UUID,
    ) -> None:
        """Write the durable pairing marker as the final remote admission."""
        store = self._store_factory(probe_settings)
        try:
            creation = await store.prepare_binding_creation(
                binding_id,
                require_empty_namespace=False,
            )
            if creation is not None:
                await store.create_binding(creation)
        except ObjectStoreBindingError as error:
            raise ObjectStoreProbeBindingMismatch(
                "Object storage is bound to another Eneo installation"
            ) from error
        except ObjectStoreUnavailableError as error:
            self._raise_probe_error(error)
            raise
        finally:
            await store.close()

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
        )

    async def _require_unbound_destination(self, session: AsyncSession) -> None:
        binding = await StoreBindingRepository(session).snapshot()
        if binding.binding_id is not None:
            raise ObjectStoreDestinationAlreadyBound(
                "This installation is already bound to an object-store destination"
            )

    def _settings(
        self,
        candidate: ObjectStoreConnectionInput,
        *,
        deployment_id: UUID,
    ) -> ObjectContentSettings:
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
        probe_settings = self._probe_settings(settings)
        store = self._store_factory(probe_settings)
        key = new_object_key(probe_settings)
        upload_attempted = False
        primary_error: BaseException | None = None
        binding_cleanup_error: ObjectStoreProbeCleanupError | None = None

        async def probe_binding_creation() -> None:
            nonlocal binding_cleanup_error
            try:
                await store.probe_binding_creation()
            except ObjectStoreProbeCleanupError as error:
                binding_cleanup_error = error
                raise

        try:
            async with asyncio.timeout(_PROBE_END_TO_END_TIMEOUT_SECONDS):
                await store.check_ready()
                if binding is None:
                    await _await_quiescent(probe_binding_creation())
                else:
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
            primary_error = (
                binding_cleanup_error
                if isinstance(error, TimeoutError) and binding_cleanup_error is not None
                else error
            )
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
            finally:
                await store.close()

        if primary_error is not None:
            self._raise_probe_error(primary_error)

    @staticmethod
    def _probe_settings(
        settings: ObjectContentSettings,
    ) -> ObjectContentSettings:
        delete_visibility_timeout_seconds = min(
            settings.delete_visibility_timeout_seconds,
            _PROBE_DELETE_TIMEOUT_SECONDS,
        )
        return ObjectContentSettings.model_validate(
            {
                **settings.model_dump(),
                "connect_timeout_seconds": min(
                    settings.connect_timeout_seconds,
                    _PROBE_REQUEST_TIMEOUT_SECONDS,
                ),
                "read_timeout_seconds": min(
                    settings.read_timeout_seconds,
                    _PROBE_REQUEST_TIMEOUT_SECONDS,
                ),
                "sdk_max_attempts": 1,
                "readiness_timeout_seconds": min(
                    settings.readiness_timeout_seconds,
                    _PROBE_REQUEST_TIMEOUT_SECONDS,
                ),
                "readiness_max_attempts": 1,
                "delete_visibility_timeout_seconds": (
                    delete_visibility_timeout_seconds
                ),
                "delete_poll_interval_seconds": min(
                    settings.delete_poll_interval_seconds,
                    delete_visibility_timeout_seconds,
                ),
            }
        )

    @staticmethod
    def _raise_probe_error(error: BaseException) -> None:
        if isinstance(error, asyncio.CancelledError):
            raise error
        if isinstance(error, ObjectStoreConnectionError):
            raise error
        if isinstance(error, ObjectContentConfigurationError):
            raise ObjectStoreProbeBindingMismatch(
                "Object storage does not match PostgreSQL"
            ) from error
        if isinstance(error, ObjectContentUnavailableError):
            if isinstance(error.__cause__, ObjectStoreUnavailableError):
                ObjectStoreConnectionService._raise_probe_error(error.__cause__)
            raise ObjectStoreProbeUnavailable(
                "Object storage could not establish its durable binding"
            ) from error
        if isinstance(error, ObjectStoreBindingError):
            raise ObjectStoreProbeBindingMismatch(
                "Object storage is bound to another Eneo installation"
            ) from error
        if isinstance(error, ObjectStoreIntegrityError):
            raise ObjectStoreProbeIntegrityFailed(
                "Object storage did not preserve the probe bytes"
            ) from error
        if isinstance(error, ObjectStoreProbeCleanupError):
            raise ObjectStoreProbeCleanupFailed(
                "Object-store binding probe cleanup could not be confirmed"
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
