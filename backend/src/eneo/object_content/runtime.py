from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic

from sqlalchemy import exists, select
from sqlalchemy.exc import SQLAlchemyError

from eneo.database.database import DatabaseSessionManager, sessionmanager
from eneo.database.tables.object_content_table import ObjectContents
from eneo.object_content.configuration import (
    ObjectContentCoreSettings,
    ObjectContentSettings,
    load_object_content_core_settings,
    load_object_content_settings,
)
from eneo.object_content.content import (
    ContentState,
    ObjectContentConfigurationError,
    ObjectContentUnavailableError,
    StorageKind,
)
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.reconciliation import (
    ObjectContentReconciler,
    ReconciliationResult,
)
from eneo.object_content.reconciliation_repository import (
    ObjectContentHealthFacts,
)
from eneo.object_content.s3_object_store import S3ObjectStore

_ACTIVE_CONTENT_STATES = tuple(
    state.value for state in ContentState if state is not ContentState.TOMBSTONED
)
# Bound dependency amplification without hiding an outage or recovery for more
# than one second. This is an internal probe-safety invariant, not product policy.
_READINESS_CACHE_SECONDS = 1.0


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
        self._settings: ObjectContentSettings | None = None
        self._store: S3ObjectStore | None = None
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
        required_inline_bytes: int | None = None,
    ) -> None:
        if self._state is not ObjectContentRuntimeState.NOT_STARTED:
            raise RuntimeError("Object-content runtime is already initialized")

        self._readiness_cache = None
        resolved_core_settings = (
            core_settings
            if core_settings is not None
            else load_object_content_core_settings()
        )
        if (
            required_inline_bytes is not None
            and resolved_core_settings.inline_maximum_bytes < required_inline_bytes
        ):
            raise ObjectContentConfigurationError(
                "OBJECT_CONTENT_INLINE_MAXIMUM_BYTES must be at least the "
                "largest configured File upload limit"
            )
        resolved_settings = (
            settings if settings is not None else load_object_content_settings()
        )
        if resolved_settings is None:
            if store is not None:
                raise ValueError(
                    "An object-content store cannot be supplied without settings"
                )
            resolved_store = None
        else:
            resolved_store = store or S3ObjectStore(resolved_settings)
        self._core_settings = resolved_core_settings
        self._settings = resolved_settings
        self._store = resolved_store
        self._service = ObjectContentService(
            resolved_core_settings,
            self._database,
            object_store_settings=resolved_settings,
            object_store=resolved_store,
        )
        self._reconciler = ObjectContentReconciler(
            resolved_core_settings,
            self._database,
            object_store_settings=resolved_settings,
            object_store=resolved_store,
        )
        self._state = ObjectContentRuntimeState.ENABLED

    async def stop(self) -> None:
        store = self._store
        self._readiness_cache = None
        self._core_settings = None
        self._settings = None
        self._store = None
        self._service = None
        self._reconciler = None
        self._state = ObjectContentRuntimeState.NOT_STARTED
        if store is not None:
            await store.close()

    @property
    def state(self) -> ObjectContentRuntimeState:
        return self._state

    @property
    def enabled(self) -> bool:
        return self._state is ObjectContentRuntimeState.ENABLED

    @property
    def object_store_configured(self) -> bool:
        return self._settings is not None

    @property
    def inline_maximum_bytes(self) -> int:
        settings = self._core_settings
        if settings is None:
            raise ObjectContentUnavailableError(
                "Durable object content is not initialized"
            )
        return settings.inline_maximum_bytes

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
            readiness = await self._refresh_readiness()
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
            active_object_store_content = await self._has_active_object_store_content()
        except ObjectContentUnavailableError:
            # Readiness is a failure boundary: driver and pool failures must
            # produce one sanitized status instead of escaping through the
            # public probe.
            return ObjectContentReadiness(
                ready=False,
                code=ObjectContentReadinessCode.DATABASE_UNAVAILABLE,
            )

        if not self.object_store_configured:
            if active_object_store_content:
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
        active_object_store_content = await self._has_active_object_store_content()
        if not self.object_store_configured:
            if active_object_store_content:
                raise ObjectContentConfigurationError(
                    "Object-store configuration is required by active content"
                )
            return
        await self.service.check_object_store_ready()

    async def _has_active_object_store_content(self) -> bool:
        try:
            async with self._database.connect() as connection:
                result = await connection.execute(
                    select(
                        exists().where(
                            ObjectContents.storage_kind
                            == StorageKind.OBJECT_STORE.value,
                            ObjectContents.state.in_(_ACTIVE_CONTENT_STATES),
                        )
                    )
                )
                active_content = bool(result.scalar_one())
        except (OSError, SQLAlchemyError) as error:
            raise ObjectContentUnavailableError(
                "Unable to verify object-content authority state"
            ) from error
        return active_content

    async def reconcile_once(self) -> ReconciliationResult:
        if self._state is ObjectContentRuntimeState.NOT_STARTED:
            raise ObjectContentUnavailableError(
                "Durable object content is not initialized"
            )
        if (
            not self.object_store_configured
            and await self._has_active_object_store_content()
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
