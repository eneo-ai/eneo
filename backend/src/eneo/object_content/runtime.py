from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from eneo.database.database import DatabaseSessionManager, sessionmanager
from eneo.object_content.configuration import (
    ObjectContentSettings,
    load_object_content_settings,
)
from eneo.object_content.content import ObjectContentUnavailableError
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.reconciliation import ObjectContentReconciler
from eneo.object_content.reconciliation_repository import ObjectContentHealthFacts
from eneo.object_content.s3_object_store import S3ObjectStore


class ObjectContentReadinessCode(StrEnum):
    READY = "ready"
    NOT_INITIALIZED = "not_initialized"
    DATABASE_UNAVAILABLE = "database_unavailable"
    STORE_UNAVAILABLE = "store_unavailable"


@dataclass(frozen=True, slots=True)
class ObjectContentReadiness:
    ready: bool
    code: ObjectContentReadinessCode


class ObjectContentRuntime:
    """Own the process-lifetime composition of the object-content Module."""

    def __init__(self, database: DatabaseSessionManager = sessionmanager) -> None:
        self._database = database
        self._settings: ObjectContentSettings | None = None
        self._store: S3ObjectStore | None = None
        self._service: ObjectContentService | None = None
        self._reconciler: ObjectContentReconciler | None = None
        self._readiness_lock = asyncio.Lock()

    def start(
        self,
        *,
        settings: ObjectContentSettings | None = None,
        store: S3ObjectStore | None = None,
    ) -> None:
        if self._store is not None:
            raise RuntimeError("Object-content runtime is already initialized")

        resolved_settings = settings or load_object_content_settings()
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

    async def stop(self) -> None:
        store = self._store
        self._settings = None
        self._store = None
        self._service = None
        self._reconciler = None
        if store is not None:
            await store.close()

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
        service = self._service
        if service is None:
            return ObjectContentReadiness(
                ready=False,
                code=ObjectContentReadinessCode.NOT_INITIALIZED,
            )

        # Serialize concurrent deployment probes into bounded SDK calls. The
        # concrete adapter owns connect/read/retry timeouts; cancelling a
        # to_thread call here would not stop its worker thread.
        async with self._readiness_lock:
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
                await service.check_ready()
            except ObjectContentUnavailableError:
                return ObjectContentReadiness(
                    ready=False,
                    code=ObjectContentReadinessCode.STORE_UNAVAILABLE,
                )
        return ObjectContentReadiness(
            ready=True,
            code=ObjectContentReadinessCode.READY,
        )

    async def health_facts(self) -> ObjectContentHealthFacts:
        return await self.reconciler.health_facts()


object_content_runtime = ObjectContentRuntime()
