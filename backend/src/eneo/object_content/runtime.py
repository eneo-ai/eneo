from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.exc import SQLAlchemyError

from eneo.database.database import DatabaseSessionManager, sessionmanager
from eneo.database.tables.object_content_table import (
    ObjectContentMoves,
    ObjectContentMultipartCandidates,
    ObjectContentOrphanCandidates,
    ObjectContents,
)
from eneo.main.logging import get_logger
from eneo.object_content.configuration import (
    ObjectContentCoreSettings,
    ObjectContentSettings,
    ObjectStoreOperatorSettings,
    load_object_content_core_settings,
    load_object_content_settings,
    load_object_store_operator_settings,
)
from eneo.object_content.content import (
    ContentMoveState,
    ContentState,
    ObjectContentConfigurationError,
    ObjectContentUnavailableError,
    StorageKind,
)
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.object_store_connection import (
    ObjectStoreConnectionDatabaseUnavailable,
    ObjectStoreConnectionError,
    ObjectStoreConnectionInput,
    ObjectStoreConnectionService,
    ObjectStoreConnectionSource,
    ObjectStoreCredentialRotation,
    StoredObjectStoreConnection,
)
from eneo.object_content.object_store_provider import ObjectStoreProvider
from eneo.object_content.reconciliation import (
    ObjectContentReconciler,
    ReconciliationResult,
)
from eneo.object_content.reconciliation_repository import (
    ObjectContentHealthFacts,
)
from eneo.object_content.s3_object_store import S3ObjectStore
from eneo.settings.encryption_service import EncryptionService

_ACTIVE_CONTENT_STATES = tuple(
    state.value for state in ContentState if state is not ContentState.TOMBSTONED
)
# Bound dependency amplification without hiding an outage or recovery for more
# than one second. This is an internal probe-safety invariant, not product policy.
_READINESS_CACHE_SECONDS = 1.0

logger = get_logger(__name__)


class ObjectContentReadinessCode(StrEnum):
    READY = "ready"
    OBJECT_STORE_NOT_CONFIGURED = "object_store_not_configured"
    NOT_INITIALIZED = "not_initialized"
    CONFIGURATION_REQUIRED = "configuration_required"
    DATABASE_UNAVAILABLE = "database_unavailable"
    STORE_DEGRADED = "store_degraded"


@dataclass(frozen=True, slots=True)
class ObjectContentReadiness:
    ready: bool
    code: ObjectContentReadinessCode


@dataclass(frozen=True, slots=True)
class StorageCapability:
    target: StorageKind
    configured: bool
    selectable: bool
    readiness_code: ObjectContentReadinessCode


class ObjectContentRuntimeState(StrEnum):
    NOT_STARTED = "not_started"
    ENABLED = "enabled"


class ObjectContentRuntime:
    """Own the process-lifetime composition of the object-content Module."""

    def __init__(self, database: DatabaseSessionManager = sessionmanager) -> None:
        self._database = database
        self._state = ObjectContentRuntimeState.NOT_STARTED
        self._core_settings: ObjectContentCoreSettings | None = None
        self._legacy_settings: ObjectContentSettings | None = None
        self._object_store_provider: ObjectStoreProvider | None = None
        self._connection_service: ObjectStoreConnectionService | None = None
        self._configuration_initialized = False
        self._service: ObjectContentService | None = None
        self._reconciler: ObjectContentReconciler | None = None
        self._readiness_lock = asyncio.Lock()
        self._readiness_cache: tuple[ObjectContentReadiness, float] | None = None

    def start(
        self,
        *,
        core_settings: ObjectContentCoreSettings | None = None,
        settings: ObjectContentSettings | None = None,
        store: S3ObjectStore | None = None,
        operator_settings: ObjectStoreOperatorSettings | None = None,
        encryption: EncryptionService | None = None,
        store_factory: Callable[[ObjectContentSettings], S3ObjectStore] = S3ObjectStore,
    ) -> None:
        if self._state is not ObjectContentRuntimeState.NOT_STARTED:
            raise RuntimeError("Object-content runtime is already initialized")

        self._readiness_cache = None
        resolved_core_settings = (
            core_settings
            if core_settings is not None
            else load_object_content_core_settings()
        )
        if settings is not None:
            resolved_store = store or store_factory(settings)
            provider = ObjectStoreProvider.fixed(settings, resolved_store)
            legacy_settings = None
            connection_service = None
        else:
            if store is not None:
                raise ValueError(
                    "An object-content store cannot be supplied without settings"
                )
            legacy_settings = load_object_content_settings()
            resolved_operator_settings = (
                operator_settings
                if operator_settings is not None
                else load_object_store_operator_settings()
            )
            connection_service = ObjectStoreConnectionService(
                database=self._database,
                core_settings=resolved_core_settings,
                operator_settings=resolved_operator_settings,
                encryption=encryption or EncryptionService(),
                store_factory=store_factory,
            )
            provider = ObjectStoreProvider(
                connection_service=connection_service,
                legacy_settings=legacy_settings,
                store_factory=store_factory,
            )
        self._core_settings = resolved_core_settings
        self._legacy_settings = legacy_settings
        self._object_store_provider = provider
        self._connection_service = connection_service
        self._configuration_initialized = settings is not None
        self._service = ObjectContentService(
            resolved_core_settings,
            self._database,
            object_store_provider=provider,
        )
        self._reconciler = ObjectContentReconciler(
            resolved_core_settings,
            self._database,
            object_store_provider=provider,
        )
        self._state = ObjectContentRuntimeState.ENABLED

    async def stop(self) -> None:
        provider = self._object_store_provider
        self._readiness_cache = None
        self._core_settings = None
        self._legacy_settings = None
        self._object_store_provider = None
        self._connection_service = None
        self._configuration_initialized = False
        self._service = None
        self._reconciler = None
        self._state = ObjectContentRuntimeState.NOT_STARTED
        if provider is not None:
            await provider.close()

    @property
    def state(self) -> ObjectContentRuntimeState:
        return self._state

    @property
    def enabled(self) -> bool:
        return self._state is ObjectContentRuntimeState.ENABLED

    @property
    def object_store_configured(self) -> bool:
        provider = self._object_store_provider
        return provider is not None and provider.configured

    @property
    def inline_maximum_bytes(self) -> int:
        settings = self._core_settings
        if settings is None:
            raise ObjectContentUnavailableError(
                "Durable object content is not initialized"
            )
        return settings.inline_maximum_bytes

    @property
    def object_store_maximum_bytes(self) -> int | None:
        provider = self._object_store_provider
        return provider.maximum_bytes if provider is not None else None

    @property
    def object_store_connection_source(self) -> ObjectStoreConnectionSource:
        provider = self._object_store_provider
        return (
            provider.source
            if provider is not None
            else ObjectStoreConnectionSource.UNCONFIGURED
        )

    @property
    def stored_object_store_connection(self) -> StoredObjectStoreConnection | None:
        provider = self._object_store_provider
        return provider.stored_connection if provider is not None else None

    @property
    def legacy_object_store_settings(self) -> ObjectContentSettings | None:
        return self._legacy_settings

    @property
    def object_store_credentials_can_be_managed(self) -> bool:
        service = self._connection_service
        return service is not None and service.credential_encryption_active

    @property
    def service(self) -> ObjectContentService:
        service = self._service
        if service is None:
            raise ObjectContentUnavailableError(
                "Durable object content is not initialized"
            )
        return service

    @property
    def reconciler(self) -> ObjectContentReconciler:
        reconciler = self._reconciler
        if reconciler is None:
            raise ObjectContentUnavailableError(
                "Durable object content is not initialized"
            )
        return reconciler

    async def refresh_object_store_configuration(self) -> None:
        provider = self._object_store_provider
        if provider is None:
            raise ObjectContentUnavailableError(
                "Durable object content is not initialized"
            )
        if not self._configuration_initialized:
            await provider.initialize()
            self._configuration_initialized = True
        else:
            await provider.refresh()
        self._readiness_cache = None

    async def create_object_store_connection(
        self,
        candidate: ObjectStoreConnectionInput,
        *,
        actor_user_id: UUID,
    ) -> StoredObjectStoreConnection:
        connection_service = self._connection_service
        if connection_service is None:
            raise ObjectContentConfigurationError(
                "Admin-managed object storage is unavailable in this runtime"
            )
        stored = await connection_service.create(
            candidate,
            actor_user_id=actor_user_id,
        )
        await self._publish_saved_object_store_connection(stored)
        return stored

    async def rotate_object_store_credentials(
        self,
        replacement: ObjectStoreCredentialRotation,
        *,
        actor_user_id: UUID,
    ) -> StoredObjectStoreConnection:
        connection_service = self._connection_service
        if connection_service is None:
            raise ObjectContentConfigurationError(
                "Admin-managed object storage is unavailable in this runtime"
            )
        stored = await connection_service.rotate_credentials(
            replacement,
            actor_user_id=actor_user_id,
        )
        await self._publish_saved_object_store_connection(stored)
        return stored

    async def _publish_saved_object_store_connection(
        self,
        stored: StoredObjectStoreConnection,
    ) -> None:
        self._readiness_cache = None
        provider = self._object_store_provider
        if provider is None:
            logger.warning(
                "object_store.connection_publication_skipped",
                extra={"revision": stored.revision},
            )
            return
        try:
            await provider.publish(stored)
        except Exception:
            logger.exception(
                "object_store.connection_publication_failed",
                extra={"revision": stored.revision},
            )

    async def readiness(self) -> ObjectContentReadiness:
        if self._state is ObjectContentRuntimeState.NOT_STARTED:
            return ObjectContentReadiness(
                ready=False,
                code=ObjectContentReadinessCode.NOT_INITIALIZED,
            )

        cached = self._cached_readiness()
        if cached is not None:
            return cached

        # One caller refreshes dependency state. Waiters check the cache again
        # after acquiring the lock instead of repeating the same remote work.
        async with self._readiness_lock:
            cached = self._cached_readiness()
            if cached is not None:
                return cached
            try:
                await self.refresh_object_store_configuration()
                readiness = await self._refresh_readiness()
            except (
                OSError,
                SQLAlchemyError,
                ObjectContentUnavailableError,
                ObjectStoreConnectionDatabaseUnavailable,
            ):
                readiness = ObjectContentReadiness(
                    ready=False,
                    code=ObjectContentReadinessCode.DATABASE_UNAVAILABLE,
                )
            except ObjectStoreConnectionError:
                readiness = ObjectContentReadiness(
                    ready=False,
                    code=ObjectContentReadinessCode.CONFIGURATION_REQUIRED,
                )
            self._readiness_cache = (
                readiness,
                monotonic() + _READINESS_CACHE_SECONDS,
            )
            return readiness

    async def storage_capabilities(self) -> tuple[StorageCapability, ...]:
        readiness = await self.readiness()
        return (
            StorageCapability(
                target=StorageKind.POSTGRES_INLINE,
                configured=True,
                selectable=self.enabled,
                readiness_code=(
                    ObjectContentReadinessCode.READY
                    if self.enabled
                    else ObjectContentReadinessCode.NOT_INITIALIZED
                ),
            ),
            StorageCapability(
                target=StorageKind.OBJECT_STORE,
                configured=self.object_store_configured,
                selectable=(
                    self.object_store_configured
                    and readiness.code is ObjectContentReadinessCode.READY
                ),
                readiness_code=readiness.code,
            ),
        )

    def _cached_readiness(self) -> ObjectContentReadiness | None:
        cached = self._readiness_cache
        if cached is None:
            return None
        readiness, expires_at = cached
        if monotonic() >= expires_at:
            return None
        return readiness

    async def _refresh_readiness(self) -> ObjectContentReadiness:
        service = self._service
        if service is None:
            return ObjectContentReadiness(
                ready=False,
                code=ObjectContentReadinessCode.NOT_INITIALIZED,
            )

        try:
            requires_object_store = await self._requires_object_store_configuration()
        except ObjectContentUnavailableError:
            # Readiness is a failure boundary: driver and pool failures must
            # produce one sanitized status instead of escaping through the
            # public probe.
            return ObjectContentReadiness(
                ready=False,
                code=ObjectContentReadinessCode.DATABASE_UNAVAILABLE,
            )

        if not self.object_store_configured:
            if requires_object_store:
                return ObjectContentReadiness(
                    ready=False,
                    code=ObjectContentReadinessCode.CONFIGURATION_REQUIRED,
                )
            return ObjectContentReadiness(
                ready=True,
                code=ObjectContentReadinessCode.OBJECT_STORE_NOT_CONFIGURED,
            )

        try:
            await service.check_object_store_ready()
        except ObjectContentConfigurationError:
            return ObjectContentReadiness(
                ready=False,
                code=ObjectContentReadinessCode.CONFIGURATION_REQUIRED,
            )
        except ObjectContentUnavailableError:
            return ObjectContentReadiness(
                ready=True,
                code=ObjectContentReadinessCode.STORE_DEGRADED,
            )
        return ObjectContentReadiness(
            ready=True,
            code=ObjectContentReadinessCode.READY,
        )

    async def validate_configuration(self) -> None:
        """Validate that configured byte authorities remain reachable by design."""
        if self._state is ObjectContentRuntimeState.NOT_STARTED:
            raise ObjectContentUnavailableError(
                "Durable object content is not initialized"
            )
        await self.refresh_object_store_configuration()
        requires_object_store = await self._requires_object_store_configuration()
        if not self.object_store_configured:
            if requires_object_store:
                raise ObjectContentConfigurationError(
                    "Object-store configuration is required by active content"
                )
            return
        await self.service.check_object_store_ready()
        provider = self._object_store_provider
        if provider is not None:
            await provider.adopt_validated_legacy()

    async def _requires_object_store_configuration(self) -> bool:
        try:
            async with self._database.connect() as connection:
                result = await connection.execute(
                    select(
                        or_(
                            exists().where(
                                ObjectContents.storage_kind
                                == StorageKind.OBJECT_STORE.value,
                                ObjectContents.state.in_(_ACTIVE_CONTENT_STATES),
                            ),
                            exists().where(
                                ObjectContentMoves.target_kind
                                == StorageKind.OBJECT_STORE.value,
                                ObjectContentMoves.state.in_(
                                    (
                                        ContentMoveState.PENDING.value,
                                        ContentMoveState.TARGET_VERIFIED.value,
                                    )
                                ),
                            ),
                            exists().where(
                                ObjectContentOrphanCandidates.object_key.is_not(None),
                            ),
                            exists().where(
                                ObjectContentMultipartCandidates.object_key.is_not(
                                    None
                                ),
                            ),
                        )
                    )
                )
                requires_object_store = bool(result.scalar_one())
        except (OSError, SQLAlchemyError) as error:
            raise ObjectContentUnavailableError(
                "Unable to verify object-content authority state"
            ) from error
        return requires_object_store

    async def reconcile_once(self) -> ReconciliationResult:
        if self._state is ObjectContentRuntimeState.NOT_STARTED:
            raise ObjectContentUnavailableError(
                "Durable object content is not initialized"
            )
        await self.refresh_object_store_configuration()
        if (
            not self.object_store_configured
            and await self._requires_object_store_configuration()
        ):
            raise ObjectContentConfigurationError(
                "Object-store configuration is required by active content"
            )
        if self.object_store_configured:
            try:
                await self.service.check_object_store_ready()
            except ObjectContentConfigurationError:
                raise
            except ObjectContentUnavailableError:
                # The reconciler still advances local lifecycle/audit work and
                # treats a transient object-store outage as a bounded no-op.
                pass
        return await self.reconciler.run_once()

    async def health_facts(self) -> ObjectContentHealthFacts:
        return await self.reconciler.health_facts()


object_content_runtime = ObjectContentRuntime()
