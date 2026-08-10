from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal, NamedTuple, TypeVar, cast
from urllib.parse import urlparse
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from sqlalchemy import and_, func, or_, select, update
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
    ObjectStoreObjects,
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
    canonical_endpoint_origin,
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
    ObjectStoreError,
    ObjectStoreFailureKind,
    ObjectStoreIntegrityError,
    ObjectStoreNotFoundError,
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

logger = logging.getLogger(__name__)

#: Content whose object must exist on any destination Eneo activates. Content
#: already recorded as missing on the source is excluded: its object is absent
#: everywhere, so requiring it would block every future switch.
_SERVED_REMOTE_CONTENT = or_(
    ObjectContents.state == "available",
    and_(
        ObjectContents.state == "retained",
        or_(
            ObjectContents.failure_code.is_(None),
            ObjectContents.failure_code != "backend_missing",
        ),
    ),
)
_VERIFICATION_PAGE_SIZE = 1000
_VERIFICATION_CONCURRENCY = 16


class ServedSnapshot(NamedTuple):
    """The served remote set's identity at one instant."""

    total: int
    fingerprint: bytes


def _snapshot_entry(object_key: str, size_bytes: int, media_type: str) -> bytes:
    """Length-prefixed encoding of one served object, delimiter-proof."""
    key = object_key.encode()
    media = media_type.encode()
    return b"%d:%s%d:%d:%s" % (len(key), key, size_bytes, len(media), media)


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


class ObjectStoreSwitchBackDiverged(ObjectStoreDestinationSwitchBlocked):
    """Objects stored since the switch are absent from the archived bucket."""

    code = "object_store_switch_back_diverged"


class ObjectStorePolicyChangedDuringSwitch(ObjectStoreDestinationSwitchBlocked):
    """The storage policy moved while the candidate was being verified.

    Every path that can create a remote object requires a policy change —
    selecting object storage for new writes, or resuming moves — and every
    policy change advances the policy revision. A revision that moved during
    verification therefore means the frozen state this switch counted on may
    not have held, so the switch starts over instead of trusting it.
    """

    code = "object_store_policy_changed_during_switch"


class ObjectStoreDestinationCopyIncomplete(ObjectStoreConnectionError):
    """The target does not hold every object this deployment must serve.

    Eneo cannot observe the operator's copy, so it proves the result instead:
    every durable key the deployment still serves must already exist on the
    candidate. This is what makes the switch safe no matter when the copy ran
    or what happened to the source in between.
    """

    code = "object_store_destination_copy_incomplete"


class ObjectStorePreviousDestinationPresent(ObjectStoreConnectionError):
    """An archived previous destination still occupies the temporary slot."""

    code = "object_store_previous_destination_present"


class ObjectStoreNewWritesNotRedirected(ObjectStoreConnectionError):
    """New writes still target object storage; the administrator must act."""

    code = "object_store_new_writes_not_redirected"


class ObjectStoreMovesNotPaused(ObjectStoreConnectionError):
    """Storage moves are not paused; the administrator must pause them.

    A paused move queue is what turns the switch preconditions from a
    point-in-time observation into a guarantee over the whole copy window:
    with new writes on PostgreSQL and moves paused, nothing can create a new
    object on the active destination between the operator's copy and the
    switch.
    """

    code = "object_store_moves_not_paused"


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
        # A candidate row belongs to a switch that is still being admitted, so
        # only a retiring row is a destination anyone can return to.
        row = await self._session.scalar(
            select(ObjectStoreConnections).where(
                ObjectStoreConnections.id == TEMPORARY_DESTINATION_SLOT,
                ObjectStoreConnections.role == "retiring",
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
        # Compare what the destination will actually be, not what was typed:
        # `https://host/`, `https://HOST` and `https://host:443` all name one
        # destination. Comparing raw input would let the active bucket pass
        # as "new" and switch onto itself.
        canonical = self._settings(candidate, deployment_id=stored.deployment_id)
        if self._same_place(canonical, stored):
            raise ObjectStoreConnectionInvalid(
                "The new destination is the same as the current one"
            )
        # The temporary slot records the destination being claimed, so an
        # archived previous destination must be released first. Switching
        # would overwrite that record anyway; requiring the operator to
        # forget it makes giving up the way back a deliberate act.
        async with self._transaction() as session:
            archived = await ObjectStoreConnectionRepository(session).get_previous()
        if archived is not None:
            raise ObjectStorePreviousDestinationPresent(
                "Remove the archived previous destination before changing "
                "destination again"
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
        # Fast feedback before any remote work; re-checked under lock in the
        # final transaction.
        async with self._transaction() as session:
            await self._require_no_remote_keys_since(
                session, archived_at=previous.updated_at
            )
        return await self._switch(
            candidate,
            actor_user_id=actor_user_id,
            stored=stored,
            binding=binding,
            require_previous_revision=previous.revision,
        )

    async def forget_previous_destination(self, *, actor_user_id: UUID) -> None:
        """Drop the archived previous-destination record (bucket untouched)."""
        del actor_user_id  # authorization happens at the router boundary
        async with self._transaction(mutation=True) as session:
            row = await session.scalar(
                select(ObjectStoreConnections)
                .where(
                    ObjectStoreConnections.id == TEMPORARY_DESTINATION_SLOT,
                    ObjectStoreConnections.role == "retiring",
                )
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
        require_previous_revision: int | None = None,
    ) -> DestinationSwitch:
        if not binding.confirmed or binding.binding_id is None:
            raise ObjectStoreDestinationSwitchBlocked(
                "The current destination has no established storage binding"
            )
        # Fast feedback before any remote work; re-checked under lock below.
        # The policy revision observed here is the identity of the quiet
        # state: it must still hold when the swap commits.
        async with self._transaction() as session:
            policy_revision = await self._require_switchable(session)

        settings = self._settings(
            candidate,
            deployment_id=stored.deployment_id,
        )
        fresh_marker, candidate_revision = await self._admit_switch_target(
            candidate,
            settings,
            binding_id=binding.binding_id,
            expected_revision=stored.revision,
            # Switch-back's target is already recorded in the temporary slot,
            # so it needs no candidate record and must not overwrite the row
            # it is restoring.
            persist_candidate=require_previous_revision is None,
        )

        try:
            # Freeze the source before counting it. Advancing the generation
            # takes the same exclusive lock the write fence reads under, so
            # remote work admitted earlier either commits before this point
            # (and is therefore part of what gets verified) or fails its own
            # generation check afterwards. Comparing timestamps could not
            # order these: a transaction's now() predates its commit. Work
            # admitted under the advanced generation instead requires a policy
            # change, which the commit refuses via the captured revision.
            fenced = await self._advance_generation(expected_revision=stored.revision)
            verified_snapshot = await self._require_target_holds_every_object(settings)
            switch = await self._commit_switch(
                candidate,
                settings=settings,
                actor_user_id=actor_user_id,
                stored=fenced,
                require_previous_revision=require_previous_revision,
                expected_policy_revision=policy_revision,
                verified_snapshot=verified_snapshot,
            )
        except (
            ObjectStoreDestinationSwitchBlocked,
            ObjectStoreDestinationCopyIncomplete,
            ObjectStoreMovesNotPaused,
            ObjectStoreNewWritesNotRedirected,
        ):
            # The switch rejected itself with the shared state untouched, so
            # the target must not stay paired to this installation. A revision
            # conflict (ObjectStoreConnectionConflict) deliberately does NOT
            # clean up: it means another actor advanced the connection — a
            # competing switch may have adopted this very marker, and the
            # recorded candidate keeps the bucket recoverable either way. An
            # ambiguous outcome (ObjectStoreConnectionMutationOutcomeUnknown)
            # keeps the marker too: the swap may have committed.
            if fresh_marker:
                await self._abandon_switch_claim(
                    settings,
                    binding_id=binding.binding_id,
                    candidate_revision=candidate_revision,
                )
            raise

        # The committed switch re-asserts its own marker. A concurrent
        # attempt's cleanup can race the admission check and remove the marker
        # this switch verified, and no ordering of lock-free remote deletes
        # can fully prevent that — so the endgame is made harmless instead:
        # whatever happened during the race, the active destination ends up
        # marked. Failure here is logged, not raised; the switch has committed
        # and readiness surfaces a persistently missing marker.
        try:
            await self._create_switch_marker(
                self._probe_settings(settings), binding_id=binding.binding_id
            )
        except Exception:
            logger.warning(
                "object_content.switch_marker_reassert_failed",
                extra={"endpoint_url": settings.endpoint_url},
                exc_info=True,
            )
        return switch

    async def _commit_switch(
        self,
        candidate: ObjectStoreConnectionInput,
        *,
        settings: ObjectContentSettings,
        actor_user_id: UUID,
        stored: StoredObjectStoreConnection,
        require_previous_revision: int | None,
        expected_policy_revision: int,
        verified_snapshot: ServedSnapshot,
    ) -> DestinationSwitch:
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
            if await self._require_switchable(session) != expected_policy_revision:
                raise ObjectStorePolicyChangedDuringSwitch(
                    "The storage policy changed while the destination was "
                    "being verified; confirm nothing was written to object "
                    "storage, then try again"
                )
            # The exclusive active-row lock held here blocks every
            # generation-fenced remote intent, so no NEW object can become
            # served past this instant; local transitions can still remove
            # objects, which is harmless — their already-verified target
            # copies are merely surplus. Requiring the exact identity the
            # scan verified — count and order-stable digest — catches any
            # change during the scan without a policy move: a crash-
            # recovered pending upload promoted under the advanced
            # generation, and equally a completed deletion paired with such
            # a promotion, which preserves the count while changing the set.
            if await self._served_snapshot(session) != verified_snapshot:
                raise ObjectStoreDestinationCopyIncomplete(
                    "The served content changed while the new destination "
                    "was being verified; bring the copy up to date and try "
                    "again"
                )

            previous = await session.scalar(
                select(ObjectStoreConnections)
                .where(ObjectStoreConnections.id == TEMPORARY_DESTINATION_SLOT)
                .with_for_update()
            )
            if require_previous_revision is not None:
                # Switch-back races forget_previous_destination: only the
                # exact archived row it was asked to restore may be restored.
                if previous is None or previous.revision != require_previous_revision:
                    raise ObjectStoreConnectionConflict(
                        "The archived destination was removed or changed "
                        "while it was being tested"
                    )
                await self._require_no_remote_keys_since(
                    session, archived_at=previous.updated_at
                )
            elif (
                previous is not None
                and previous.role == "candidate"
                and not self._same_place(settings, _stored(previous))
            ):
                # The slot holds a different destination's live candidate — a
                # concurrent change recorded it after this one's admission.
                # Overwriting it as the archive would leave that bucket's
                # marker with no record recovery relies on, so this switch
                # yields instead.
                raise ObjectStoreConnectionConflict(
                    "Another destination change claimed its candidate while "
                    "this one was being tested"
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
            await StoreBindingRepository(session).clear_slot(
                slot=TEMPORARY_DESTINATION_SLOT
            )
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

    async def _require_switchable(self, session: AsyncSession) -> int:
        """Refuse the switch while any write could still reach a destination.

        Returns the deployment policy revision the quiet state was observed
        under, so the committing transaction can prove the policy never moved
        in between: creating a remote object requires selecting object storage
        or resuming moves, and either change advances this revision.
        """
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
        policy = (
            await session.execute(
                select(
                    ObjectContentDeploymentPolicy.new_write_storage_target,
                    ObjectContentDeploymentPolicy.moves_paused,
                    ObjectContentDeploymentPolicy.revision,
                ).where(ObjectContentDeploymentPolicy.id == 1)
            )
        ).one_or_none()
        if policy is None or policy[0] != "postgres_inline":
            raise ObjectStoreNewWritesNotRedirected(
                "Select PostgreSQL for new writes before switching destination"
            )
        if not policy[1]:
            raise ObjectStoreMovesNotPaused(
                "Pause storage moves before switching destination; a paused "
                "queue guarantees nothing is written to object storage while "
                "the copy is made"
            )
        nonterminal_moves = await session.scalar(
            select(func.count())
            .select_from(ObjectContentMoves)
            .where(ObjectContentMoves.state.in_(("pending", "target_verified")))
        )
        if nonterminal_moves:
            raise ObjectStoreDestinationSwitchBlocked(
                "Storage moves are still queued or running; let them finish "
                "(resume them if paused) before switching"
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
        return int(policy[2])

    async def _require_no_remote_keys_since(
        self,
        session: AsyncSession,
        *,
        archived_at: datetime,
        error: type[ObjectStoreConnectionError] = ObjectStoreSwitchBackDiverged,
        detail: str = (
            "Objects were stored after the destinations were switched; "
            "copy the current bucket to the previous destination and use "
            "the change-destination flow instead of switching back"
        ),
    ) -> None:
        """Refuse once the destination's key set has moved on.

        For switch-back, every durable remote key created after the swap
        exists only on the current destination, so the archived bucket cannot
        serve it. The same query closes the window between verifying a
        candidate copy and committing the swap.
        """
        new_keys = await session.scalar(
            select(func.count())
            .select_from(ObjectStoreObjects)
            .where(ObjectStoreObjects.created_at > archived_at)
        )
        if new_keys:
            raise error(detail)

    async def _advance_generation(
        self,
        *,
        expected_revision: int,
    ) -> StoredObjectStoreConnection:
        """Retire the generation in-flight remote work is running under.

        The exclusive lock this takes is the counterpart of the shared lock
        every durable remote-intent transaction reads the revision under, so
        after this commits no earlier work can still make itself durable.
        """
        async with self._transaction(mutation=True) as session:
            row = await session.scalar(
                select(ObjectStoreConnections)
                .where(ObjectStoreConnections.id == ACTIVE_DESTINATION_SLOT)
                .with_for_update()
            )
            if row is None or row.revision != expected_revision:
                raise ObjectStoreConnectionConflict(
                    "The object-store connection changed while it was being tested"
                )
            row.revision = row.revision + 1
            await session.flush()
            await session.refresh(row)
            return _stored(row)

    async def _require_target_holds_every_object(
        self,
        settings: ObjectContentSettings,
    ) -> ServedSnapshot:
        """Prove the candidate holds every key, at the right size and type.

        Eneo never sees the operator's copy, so timing rules cannot establish
        that the copy is current: quiescence can be interrupted and restored,
        and a copy can predate work that followed it. Asking the candidate for
        each key the deployment must serve settles it directly, and also
        catches the far more common accident of a copy that silently covered
        nothing.

        This deliberately verifies presence and the object metadata reads
        check first — length and media type — not byte equality. Proving the
        bytes would re-read the whole bucket inside one admin request; byte
        equality is what the operator's mandated byte comparison
        (``rclone check --download``) establishes, and every read re-verifies
        the canonical SHA-256 and fails closed, so a corrupt copy can never
        serve wrong bytes.

        The work is driven from the database side and paged, so both the
        request count and the memory held are bounded by what this deployment
        stores — never by what the candidate endpoint chooses to return.
        """
        async with self._transaction() as session:
            expected_total = await session.scalar(
                select(func.count())
                .select_from(ObjectStoreObjects)
                .join(
                    ObjectContents, ObjectContents.id == ObjectStoreObjects.content_id
                )
                .where(_SERVED_REMOTE_CONTENT)
            )
        if not expected_total:
            return ServedSnapshot(total=0, fingerprint=sha256(b"").digest())

        missing = 0
        scanned = 0
        fingerprint = sha256()
        last_key = ""
        store = self._store_factory(self._probe_settings(settings))
        try:
            while True:
                async with self._transaction() as session:
                    rows = (
                        await session.execute(
                            select(
                                ObjectStoreObjects.object_key,
                                ObjectContents.size_bytes,
                                ObjectContents.verified_media_type,
                            )
                            .join(
                                ObjectContents,
                                ObjectContents.id == ObjectStoreObjects.content_id,
                            )
                            .where(
                                _SERVED_REMOTE_CONTENT,
                                ObjectStoreObjects.object_key > last_key,
                            )
                            .order_by(ObjectStoreObjects.object_key)
                            .limit(_VERIFICATION_PAGE_SIZE)
                        )
                    ).all()
                if not rows:
                    break
                page = [(str(key), int(size), str(media)) for key, size, media in rows]
                for key, size, media in page:
                    fingerprint.update(_snapshot_entry(key, size, media))
                scanned += len(page)
                missing += await self._count_missing_or_mismatched(store, page)
                last_key = page[-1][0]
        except ObjectStoreUnavailableError as error:
            self._raise_probe_error(error)
            raise
        finally:
            await store.close()

        if missing:
            raise ObjectStoreDestinationCopyIncomplete(
                f"The new destination is missing {missing} of {expected_total} "
                "stored objects, or holds them with a different size or media "
                "type than reads verify; complete the copy preserving object "
                "metadata and try again"
            )
        return ServedSnapshot(total=scanned, fingerprint=fingerprint.digest())

    async def _served_snapshot(self, session: AsyncSession) -> ServedSnapshot:
        """The served set's identity: its count and an order-stable digest.

        Computed from the database alone, so the committing transaction can
        recompute it under the exclusive active-row lock and compare it with
        what the scan actually checked. Count equality alone is not enough:
        a deletion completed during the scan plus a recovered publication
        promoted after its key range was checked preserves the count while
        changing the set.
        """
        digest = sha256()
        count = 0
        last_key = ""
        while True:
            rows = (
                await session.execute(
                    select(
                        ObjectStoreObjects.object_key,
                        ObjectContents.size_bytes,
                        ObjectContents.verified_media_type,
                    )
                    .join(
                        ObjectContents,
                        ObjectContents.id == ObjectStoreObjects.content_id,
                    )
                    .where(
                        _SERVED_REMOTE_CONTENT,
                        ObjectStoreObjects.object_key > last_key,
                    )
                    .order_by(ObjectStoreObjects.object_key)
                    .limit(_VERIFICATION_PAGE_SIZE)
                )
            ).all()
            if not rows:
                return ServedSnapshot(total=count, fingerprint=digest.digest())
            for key, size, media in rows:
                digest.update(_snapshot_entry(str(key), int(size), str(media)))
            count += len(rows)
            last_key = str(rows[-1][0])

    async def _count_missing_or_mismatched(
        self,
        store: S3ObjectStore,
        rows: Sequence[tuple[str, int, str]],
    ) -> int:
        """Count one page's keys that are absent or metadata-mismatched.

        Existence alone is not enough: every read first verifies the object's
        length and media type against the canonical row, so a truncated copy
        or one that dropped Content-Type would pass an existence check and
        then fail every read on the activated destination. Byte equality is
        deliberately out of scope here — see
        ``_require_target_holds_every_object``.
        """
        mismatched = 0
        for start in range(0, len(rows), _VERIFICATION_CONCURRENCY):
            batch = rows[start : start + _VERIFICATION_CONCURRENCY]
            outcomes = await asyncio.gather(
                *(store.head(key) for key, _, _ in batch),
                return_exceptions=True,
            )
            for (_, size_bytes, media_type), outcome in zip(
                batch, outcomes, strict=True
            ):
                if isinstance(outcome, ObjectStoreNotFoundError):
                    mismatched += 1
                elif isinstance(outcome, BaseException):
                    raise outcome
                elif (
                    outcome.size_bytes != size_bytes or outcome.media_type != media_type
                ):
                    mismatched += 1
        return mismatched

    async def _release_stale_candidate(
        self,
        settings: ObjectContentSettings,
        *,
        binding_id: UUID,
    ) -> None:
        """Unclaim a bucket left behind by an interrupted switch.

        A switch that lost its process after writing the marker leaves its
        candidate recorded, so a later switch to a different destination can
        return that bucket to the world instead of overwriting the only record
        of it.
        """
        # Take ownership of the stale record before touching its bucket, the
        # same revision handshake cleanup uses: a retry of the interrupted
        # attempt that adopts the row first wins, and this release backs off
        # without issuing a remote delete.
        async with self._transaction(mutation=True) as session:
            row = await session.scalar(
                select(ObjectStoreConnections)
                .where(
                    ObjectStoreConnections.id == TEMPORARY_DESTINATION_SLOT,
                    ObjectStoreConnections.role == "candidate",
                )
                .with_for_update()
            )
            stale = _stored(row) if row is not None else None
            if stale is None or self._same_place(settings, stale):
                return
            assert row is not None
            row.revision = row.revision + 1
            owned_revision = row.revision
            # The lease keeps a retry of the interrupted attempt from
            # adopting the marker while its deletion is in flight.
            await StoreBindingRepository(session).hold_release_lease(
                slot=TEMPORARY_DESTINATION_SLOT,
                # Sized to outlive the remote deletion, including its
                # visibility confirmation, so the guard cannot expire while
                # the DELETE it guards is still in flight.
                lease_seconds=(
                    settings.binding_claim_seconds
                    + settings.delete_visibility_timeout_seconds
                ),
            )

        stale_settings = self.settings_for(stale)
        store = self._store_factory(self._probe_settings(stale_settings))
        try:
            await store.remove_binding(binding_id)
        except ObjectStoreBindingError:
            # The bucket's marker belongs to another installation — the
            # interrupted attempt lost its marker race — so nothing of ours
            # exists there and there is nothing to remove. Fall through to
            # retire the owned record; preserving it would wedge every later
            # destination change behind a marker that is not ours to remove.
            pass
        except ObjectStoreError as error:
            raise ObjectStoreDestinationAlreadyBound(
                f"An interrupted destination change still claims bucket "
                f"'{stale.bucket}'; make it reachable and try again, or "
                "retry that destination to finish the change"
            ) from error
        finally:
            await store.close()

        async with self._transaction(mutation=True) as session:
            current = await session.scalar(
                select(ObjectStoreConnections)
                .where(
                    ObjectStoreConnections.id == TEMPORARY_DESTINATION_SLOT,
                    ObjectStoreConnections.role == "candidate",
                )
                .with_for_update()
            )
            # Only retire the exact record whose marker was just removed: a
            # concurrent attempt may have adopted the slot in the meantime,
            # and deleting that would strand its bucket instead.
            if current is None or current.revision != owned_revision:
                return
            await StoreBindingRepository(session).clear_slot(
                slot=TEMPORARY_DESTINATION_SLOT
            )
            await session.delete(current)

    async def _record_candidate(
        self,
        session: AsyncSession,
        candidate: ObjectStoreConnectionInput,
        *,
        settings: ObjectContentSettings,
    ) -> int:
        """Persist the destination being claimed, before its marker exists.

        The row lock serialises two administrators changing destination at
        once: the first records its candidate, and the second is refused
        rather than overwriting the only record of a bucket whose marker is
        about to be written.
        """
        row = await session.scalar(
            select(ObjectStoreConnections)
            .where(ObjectStoreConnections.id == TEMPORARY_DESTINATION_SLOT)
            .with_for_update()
        )
        if row is None:
            row = ObjectStoreConnections()
            row.id = TEMPORARY_DESTINATION_SLOT
            row.revision = 1
            session.add(row)
        else:
            if row.role == "candidate" and not self._same_place(settings, _stored(row)):
                raise ObjectStoreDestinationAlreadyBound(
                    f"Another destination change is already claiming bucket "
                    f"'{row.bucket}'; finish or release it first"
                )
            row.revision = row.revision + 1
        row.role = "candidate"
        row.endpoint_url = settings.endpoint_url
        row.region = settings.region
        row.bucket = settings.bucket
        row.access_key_id_encrypted = self._encryption.encrypt(
            candidate.access_key_id.get_secret_value()
        )
        row.secret_access_key_encrypted = self._encryption.encrypt(
            candidate.secret_access_key.get_secret_value()
        )
        row.deployment_id = settings.deployment_id
        row.addressing_style = settings.addressing_style
        row.updated_by_actor = ObjectStoreConnectionActor.PLATFORM_ADMIN.value
        await session.flush()
        return row.revision

    async def _abandon_switch_claim(
        self,
        settings: ObjectContentSettings,
        *,
        binding_id: UUID,
        candidate_revision: int | None,
    ) -> None:
        """Best-effort unclaim of the target after a self-inflicted rejection.

        The candidate row's revision serialises ownership of the marker: this
        attempt first advances the revision under lock — proving no one else
        adopted the destination — and only then touches the store. A same-
        target retry adopts the row the same way, so whichever side moves the
        revision first wins and the loser never issues a remote delete. A
        failure here is logged and swallowed — the marker, the claim, and the
        candidate keep the state recoverable by retrying.
        """
        try:
            owned_revision: int | None = None
            if candidate_revision is not None:
                async with self._transaction(mutation=True) as session:
                    row = await session.scalar(
                        select(ObjectStoreConnections)
                        .where(
                            ObjectStoreConnections.id == TEMPORARY_DESTINATION_SLOT,
                            ObjectStoreConnections.role == "candidate",
                        )
                        .with_for_update()
                    )
                    if row is None or row.revision != candidate_revision:
                        return
                    row.revision = row.revision + 1
                    owned_revision = row.revision
                    # The lease keeps a same-target retry from adopting the
                    # marker while its deletion is in flight.
                    await StoreBindingRepository(session).hold_release_lease(
                        slot=TEMPORARY_DESTINATION_SLOT,
                        # Sized to outlive the remote deletion, including its
                        # visibility confirmation, so the guard cannot expire while
                        # the DELETE it guards is still in flight.
                        lease_seconds=(
                            settings.binding_claim_seconds
                            + settings.delete_visibility_timeout_seconds
                        ),
                    )

            store = self._store_factory(self._probe_settings(settings))
            try:
                await store.remove_binding(binding_id)
            finally:
                await store.close()

            async with self._transaction(mutation=True) as session:
                row = await session.scalar(
                    select(ObjectStoreConnections)
                    .where(
                        ObjectStoreConnections.id == TEMPORARY_DESTINATION_SLOT,
                        ObjectStoreConnections.role == "candidate",
                    )
                    .with_for_update()
                )
                if owned_revision is not None:
                    # Give way if anything re-recorded the candidate after
                    # ownership was taken; that owner's marker is not ours.
                    if row is None or row.revision != owned_revision:
                        return
                await StoreBindingRepository(session).clear_slot(
                    slot=TEMPORARY_DESTINATION_SLOT
                )
                if owned_revision is not None and row is not None:
                    await session.delete(row)
        except Exception:
            logger.warning(
                "object_content.switch_claim_abandon_failed",
                extra={"endpoint_url": settings.endpoint_url},
                exc_info=True,
            )

    async def _admit_switch_target(
        self,
        candidate: ObjectStoreConnectionInput,
        settings: ObjectContentSettings,
        *,
        binding_id: UUID,
        expected_revision: int,
        persist_candidate: bool,
    ) -> tuple[bool, int | None]:
        """Admit a bucket that already holds this deployment's copied bytes.

        Unlike first-time creation, the content namespace is expected to be
        non-empty. A marker naming another installation is refused. For a
        bucket with no marker yet, every fallible check runs first and the
        permanent marker is written last, so a rejected switch never leaves
        the target paired to this installation. Returns whether a fresh
        marker was written — so a later rejection can remove it again — and
        the revision of the candidate record this attempt owns.
        """
        if persist_candidate:
            await self._release_stale_candidate(settings, binding_id=binding_id)

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
            if not persist_candidate:
                return False, None
            # Adopt the destination by advancing the candidate row it is
            # recorded in: an interrupted earlier attempt's cleanup checks the
            # revision before it may delete this marker, so the adoption is
            # what makes the observed marker safe to rely on.
            adopted_revision: int | None = None
            async with self._transaction(mutation=True) as session:
                active_revision = await session.scalar(
                    select(ObjectStoreConnections.revision).where(
                        ObjectStoreConnections.id == ACTIVE_DESTINATION_SLOT
                    )
                )
                if active_revision != expected_revision:
                    raise ObjectStoreConnectionConflict(
                        "The object-store connection changed while it was being tested"
                    )
                owner = await session.scalar(
                    select(ObjectStoreConnections)
                    .where(
                        ObjectStoreConnections.id == TEMPORARY_DESTINATION_SLOT,
                        ObjectStoreConnections.role == "candidate",
                    )
                    .with_for_update()
                )
                # The lease is inspected only after the candidate row lock is
                # held: a releasing cleanup writes its lease under that same
                # lock, so checking first would read a pre-commit snapshot,
                # then adopt right after the release commits.
                if await StoreBindingRepository(session).release_lease_active(
                    slot=TEMPORARY_DESTINATION_SLOT
                ):
                    raise ObjectStoreDestinationSwitchBlocked(
                        "An earlier destination change is still being "
                        "released; try again shortly"
                    )
                if owner is not None:
                    adopted_revision = await self._record_candidate(
                        session,
                        candidate,
                        settings=settings,
                    )
                    await StoreBindingRepository(session).record_switch_claim(
                        slot=TEMPORARY_DESTINATION_SLOT,
                        deployment_id=settings.deployment_id,
                        binding_id=binding_id,
                    )
            if adopted_revision is not None:
                return False, adopted_revision
            # A marker with no live candidate record is ownerless: a finished
            # release failed to remove it, or its record was already consumed.
            # It cannot be trusted to persist, so reclaim the bucket and go
            # through the full claimed admission below instead.
            reclaim_store = self._store_factory(probe_settings)
            try:
                await reclaim_store.remove_binding(binding_id)
            except ObjectStoreBindingError as error:
                # Another installation claimed the bucket while the marker
                # was ownerless; it is theirs now.
                raise ObjectStoreProbeBindingMismatch(
                    "Object storage is bound to another Eneo installation"
                ) from error
            except ObjectStoreUnavailableError as error:
                self._raise_probe_error(error)
                raise
            finally:
                await reclaim_store.close()

        # Unmarked target: prove readiness and a complete write/read/delete
        # round trip before claiming the bucket.
        await self._probe(settings, binding=None)

        # Record the claim before the marker exists, revalidating the active
        # revision so a rotation that raced this switch cannot leave an
        # untracked pairing behind. The candidate connection is recorded in
        # the same transaction, so a process loss after the marker is written
        # still leaves the touched bucket identifiable and recoverable.
        candidate_revision: int | None = None
        async with self._transaction(mutation=True) as session:
            active_revision = await session.scalar(
                select(ObjectStoreConnections.revision).where(
                    ObjectStoreConnections.id == ACTIVE_DESTINATION_SLOT
                )
            )
            if active_revision != expected_revision:
                raise ObjectStoreConnectionConflict(
                    "The object-store connection changed while it was being tested"
                )
            if persist_candidate:
                candidate_revision = await self._record_candidate(
                    session,
                    candidate,
                    settings=settings,
                )
            await StoreBindingRepository(session).record_switch_claim(
                slot=TEMPORARY_DESTINATION_SLOT,
                deployment_id=settings.deployment_id,
                binding_id=binding_id,
            )

        try:
            await self._create_switch_marker(probe_settings, binding_id=binding_id)
        except ObjectStoreProbeBindingMismatch:
            # Another installation won the conditional marker creation, so
            # nothing of ours was written and the recorded claim and
            # candidate have no counterpart. Both are released in one
            # ownership-checked transaction that locks the candidate row
            # first — the same order adoption and stale release use — and
            # touches nothing when a newer attempt has adopted the row: its
            # claim is then not ours to clear. A lingering candidate for a
            # foreign-marked bucket could never be released later (its
            # marker is not ours to remove) and would wedge every subsequent
            # destination change. An unavailable outcome instead keeps
            # everything: our marker may exist.
            async with self._transaction(mutation=True) as session:
                if candidate_revision is None:
                    await StoreBindingRepository(session).clear_slot(
                        slot=TEMPORARY_DESTINATION_SLOT
                    )
                else:
                    row = await session.scalar(
                        select(ObjectStoreConnections)
                        .where(
                            ObjectStoreConnections.id == TEMPORARY_DESTINATION_SLOT,
                            ObjectStoreConnections.role == "candidate",
                            ObjectStoreConnections.revision == candidate_revision,
                        )
                        .with_for_update()
                    )
                    if row is not None:
                        await StoreBindingRepository(session).clear_slot(
                            slot=TEMPORARY_DESTINATION_SLOT
                        )
                        await session.delete(row)
            raise
        return True, candidate_revision

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
    def _same_place(
        settings: ObjectContentSettings,
        stored: StoredObjectStoreConnection,
    ) -> bool:
        """Whether two configurations address the same bucket.

        Region and addressing style are access details, not identity: the
        same bucket reached with a different signing region is still the same
        bytes, and must never be admitted as a new destination.
        """
        return canonical_endpoint_origin(
            settings.endpoint_url
        ) == canonical_endpoint_origin(stored.endpoint_url) and (
            settings.bucket == stored.bucket
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
