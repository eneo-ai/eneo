from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic

from sqlalchemy import exists, select, text
from sqlalchemy.exc import SQLAlchemyError

from eneo.database.database import DatabaseSessionManager, sessionmanager
from eneo.database.tables.object_content_table import ObjectContents
from eneo.object_content.configuration import (
    ObjectContentSettings,
    load_object_content_settings,
)
from eneo.object_content.content import (
    ContentState,
    ObjectContentConfigurationError,
    ObjectContentDisabledError,
    ObjectContentUnavailableError,
)
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.reconciliation import (
    ObjectContentReconciler,
    ReconciliationResult,
)
from eneo.object_content.reconciliation_repository import ObjectContentHealthFacts
from eneo.object_content.s3_object_store import S3ObjectStore

_ACTIVE_CONTENT_STATES = tuple(
    state.value for state in ContentState if state is not ContentState.TOMBSTONED
)
# Bound dependency amplification without hiding an outage or recovery for more
# than one second. This is an internal probe-safety invariant, not product policy.
_READINESS_CACHE_SECONDS = 1.0


class ObjectContentReadinessCode(StrEnum):
    READY = "ready"
    DISABLED = "disabled"
    NOT_INITIALIZED = "not_initialized"
    CONFIGURATION_REQUIRED = "configuration_required"
    DATABASE_UNAVAILABLE = "database_unavailable"
    STORE_UNAVAILABLE = "store_unavailable"


@dataclass(frozen=True, slots=True)
class ObjectContentReadiness:
    ready: bool
    code: ObjectContentReadinessCode


class ObjectContentRuntimeState(StrEnum):
    NOT_STARTED = "not_started"
    DISABLED = "disabled"
    ENABLED = "enabled"


class ObjectContentRuntime:
    """Own the process-lifetime composition of the object-content Module."""

    def __init__(self, database: DatabaseSessionManager = sessionmanager) -> None:
        self._database = database
        self._state = ObjectContentRuntimeState.NOT_STARTED
        self._settings: ObjectContentSettings | None = None
        self._store: S3ObjectStore | None = None
        self._service: ObjectContentService | None = None
        self._reconciler: ObjectContentReconciler | None = None
        self._readiness_lock = asyncio.Lock()
        self._readiness_cache: tuple[ObjectContentReadiness, float] | None = None

    def start(
        self,
        *,
        settings: ObjectContentSettings | None = None,
        store: S3ObjectStore | None = None,
    ) -> None:
        if self._state is not ObjectContentRuntimeState.NOT_STARTED:
            raise RuntimeError("Object-content runtime is already initialized")

        self._readiness_cache = None
        resolved_settings = (
            settings if settings is not None else load_object_content_settings()
        )
        if resolved_settings is None:
            if store is not None:
                raise ValueError(
                    "An object-content store cannot be supplied without settings"
                )
            self._state = ObjectContentRuntimeState.DISABLED
            return

        resolved_store = store or S3ObjectStore(resolved_settings)
        self._settings = resolved_settings
        self._store = resolved_store
        self._service = ObjectContentService(
            resolved_settings,
            resolved_store,
            self._database,
        )
        self._reconciler = ObjectContentReconciler(
            resolved_settings,
            resolved_store,
            self._database,
        )
        self._state = ObjectContentRuntimeState.ENABLED

    async def stop(self) -> None:
        store = self._store
        self._readiness_cache = None
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
    def service(self) -> ObjectContentService:
        service = self._service
        if service is None:
            if self._state is ObjectContentRuntimeState.DISABLED:
                raise ObjectContentDisabledError("Durable object content is disabled")
            raise ObjectContentUnavailableError(
                "Durable object content is not initialized"
            )
        return service

    @property
    def reconciler(self) -> ObjectContentReconciler:
        reconciler = self._reconciler
        if reconciler is None:
            if self._state is ObjectContentRuntimeState.DISABLED:
                raise ObjectContentDisabledError("Durable object content is disabled")
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

    def _cached_readiness(self) -> ObjectContentReadiness | None:
        cached = self._readiness_cache
        if cached is None:
            return None
        readiness, expires_at = cached
        if monotonic() >= expires_at:
            return None
        return readiness

    async def _refresh_readiness(self) -> ObjectContentReadiness:
        if self._state is ObjectContentRuntimeState.DISABLED:
            # PostgreSQL must remain reachable to prove disabled is still safe.
            try:
                await self.validate_configuration()
            except ObjectContentConfigurationError:
                return ObjectContentReadiness(
                    ready=False,
                    code=ObjectContentReadinessCode.CONFIGURATION_REQUIRED,
                )
            except ObjectContentUnavailableError:
                return ObjectContentReadiness(
                    ready=False,
                    code=ObjectContentReadinessCode.DATABASE_UNAVAILABLE,
                )
            return ObjectContentReadiness(
                ready=True,
                code=ObjectContentReadinessCode.DISABLED,
            )

        service = self._service
        if service is None:
            return ObjectContentReadiness(
                ready=False,
                code=ObjectContentReadinessCode.NOT_INITIALIZED,
            )

        try:
            async with self._database.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except (OSError, SQLAlchemyError):
            # Readiness is a failure boundary: driver and pool failures must
            # produce one sanitized status instead of escaping through the
            # public probe.
            return ObjectContentReadiness(
                ready=False,
                code=ObjectContentReadinessCode.DATABASE_UNAVAILABLE,
            )
        try:
            await self.validate_configuration()
        except ObjectContentConfigurationError:
            return ObjectContentReadiness(
                ready=False,
                code=ObjectContentReadinessCode.CONFIGURATION_REQUIRED,
            )
        except ObjectContentUnavailableError:
            return ObjectContentReadiness(
                ready=False,
                code=ObjectContentReadinessCode.STORE_UNAVAILABLE,
            )
        return ObjectContentReadiness(
            ready=True,
            code=ObjectContentReadinessCode.READY,
        )

    async def validate_configuration(self) -> None:
        """Fail closed if disabled storage would strand durable content."""
        if self._state is ObjectContentRuntimeState.NOT_STARTED:
            raise ObjectContentUnavailableError(
                "Durable object content is not initialized"
            )
        if self._state is ObjectContentRuntimeState.ENABLED:
            await self.service.check_ready()
            return

        try:
            async with self._database.connect() as connection:
                active_content = (
                    await connection.execute(
                        select(
                            exists().where(
                                ObjectContents.state.in_(_ACTIVE_CONTENT_STATES)
                            )
                        )
                    )
                ).scalar_one()
        except (OSError, SQLAlchemyError) as error:
            raise ObjectContentUnavailableError(
                "Unable to verify the disabled object-content state"
            ) from error

        if active_content:
            raise ObjectContentConfigurationError(
                "Durable object content cannot be disabled while active records exist"
            )

    async def reconcile_once(self) -> ReconciliationResult:
        if self._state is ObjectContentRuntimeState.DISABLED:
            await self.validate_configuration()
            return ReconciliationResult.empty()
        await self.validate_configuration()
        return await self.reconciler.run_once()

    async def health_facts(self) -> ObjectContentHealthFacts:
        return await self.reconciler.health_facts()


object_content_runtime = ObjectContentRuntime()
