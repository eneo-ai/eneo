from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from eneo.database.tables.object_store_connection_table import (
    ACTIVE_DESTINATION_SLOT,
)
from eneo.main.logging import get_logger
from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import (
    ObjectContentConfigurationError,
    ObjectContentUnavailableError,
)
from eneo.object_content.object_store_connection import (
    ObjectStoreConnectionService,
    ObjectStoreConnectionSource,
    StoredObjectStoreConnection,
)
from eneo.object_content.s3_object_store import S3ObjectStore
from eneo.object_content.store_binding import UNSTORED_CONNECTION_REVISION

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ObjectStoreLease:
    """Immutable handle for one leased client and its store generation.

    ``slot`` and ``revision`` identify the connection row and revision the
    client was built from, captured atomically with the client. Durable
    remote-intent transactions pass them to ``require_store_generation`` so
    work performed against a rotated or cut-over destination can never be
    committed.
    """

    settings: ObjectContentSettings
    store: S3ObjectStore
    slot: int
    revision: int


@dataclass(slots=True, eq=False)
class _ObjectStoreSnapshot:
    revision: int
    source: ObjectStoreConnectionSource
    stored: StoredObjectStoreConnection | None
    lease: ObjectStoreLease
    active_users: int = 0
    superseded: bool = False


StoreFactory = Callable[[ObjectContentSettings], S3ObjectStore]


class ObjectStoreProvider:
    """Publish one revisioned object-store client snapshot per process."""

    def __init__(
        self,
        *,
        connection_service: ObjectStoreConnectionService | None,
        legacy_settings: ObjectContentSettings | None = None,
        store_factory: StoreFactory = S3ObjectStore,
    ) -> None:
        self._connection_service = connection_service
        self._legacy_settings = legacy_settings
        self._store_factory = store_factory
        self._current: _ObjectStoreSnapshot | None = None
        self._superseded: set[_ObjectStoreSnapshot] = set()
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None
        self._closed = False

    @classmethod
    def fixed(
        cls,
        settings: ObjectContentSettings,
        store: S3ObjectStore,
    ) -> ObjectStoreProvider:
        provider = cls(connection_service=None)
        provider._current = _ObjectStoreSnapshot(
            revision=UNSTORED_CONNECTION_REVISION,
            source=ObjectStoreConnectionSource.ADMIN,
            stored=None,
            lease=ObjectStoreLease(
                settings=settings,
                store=store,
                slot=ACTIVE_DESTINATION_SLOT,
                revision=UNSTORED_CONNECTION_REVISION,
            ),
        )
        return provider

    @property
    def configured(self) -> bool:
        return self._current is not None

    @property
    def maximum_bytes(self) -> int | None:
        snapshot = self._current
        return snapshot.lease.settings.maximum_multipart_bytes if snapshot else None

    @property
    def configuration_revision(self) -> int | None:
        snapshot = self._current
        return snapshot.revision if snapshot is not None else None

    @property
    def source(self) -> ObjectStoreConnectionSource:
        snapshot = self._current
        return snapshot.source if snapshot else ObjectStoreConnectionSource.UNCONFIGURED

    @property
    def stored_connection(self) -> StoredObjectStoreConnection | None:
        snapshot = self._current
        return snapshot.stored if snapshot else None

    @property
    def superseded_snapshot_count(self) -> int:
        return len(self._superseded)

    async def initialize(self) -> None:
        await self.refresh()

    async def adopt_validated_legacy(self) -> None:
        service = self._connection_service
        legacy = self._legacy_settings
        if (
            service is None
            or legacy is None
            or self.source is not ObjectStoreConnectionSource.ENVIRONMENT
        ):
            return
        stored = await service.adopt_legacy(legacy)
        if stored is None:
            return
        await self.publish(stored)

    async def refresh(self) -> None:
        service = self._connection_service
        if service is None:
            return
        task = self._refresh_task
        if task is None or task.done():
            task = asyncio.create_task(self._refresh_once(service))
            self._refresh_task = task
            task.add_done_callback(self._finish_refresh)
        await asyncio.shield(task)

    def _finish_refresh(self, task: asyncio.Task[None]) -> None:
        if self._refresh_task is task:
            self._refresh_task = None
        if not task.cancelled():
            task.exception()

    async def publish(self, stored: StoredObjectStoreConnection) -> None:
        async with self._refresh_lock:
            if self._closed:
                raise ObjectContentConfigurationError(
                    "Object-store configuration is shutting down"
                )
            current = self._current
            if (
                current is not None
                and current.source is ObjectStoreConnectionSource.ADMIN
                and current.revision >= stored.revision
            ):
                return
            await self._publish(stored)

    async def _refresh_once(self, service: ObjectStoreConnectionService) -> None:
        async with self._refresh_lock:
            if self._closed:
                raise ObjectContentConfigurationError(
                    "Object-store configuration is shutting down"
                )
            stored = await service.get()
            current = self._current
            if stored is not None:
                if (
                    current is not None
                    and current.source is ObjectStoreConnectionSource.ADMIN
                    and current.revision >= stored.revision
                ):
                    return
            elif self._legacy_settings is not None:
                if (
                    current is not None
                    and current.source is ObjectStoreConnectionSource.ENVIRONMENT
                ):
                    return
            elif current is None:
                return
            await self._publish(stored)

    @asynccontextmanager
    async def acquire(
        self,
        *,
        refresh: bool = True,
        expected_revision: int | None = None,
    ) -> AsyncGenerator[ObjectStoreLease]:
        if refresh:
            await self.refresh()
        snapshot = self._current
        if snapshot is None:
            raise ObjectContentConfigurationError(
                "Object-store content is not configured for this deployment"
            )
        if expected_revision is not None and snapshot.revision != expected_revision:
            raise ObjectContentUnavailableError(
                "Object-store configuration changed during the upload; try again"
            )
        snapshot.active_users += 1
        try:
            yield snapshot.lease
        finally:
            snapshot.active_users -= 1
            if snapshot.superseded and snapshot.active_users == 0:
                await self._close_superseded(snapshot)

    async def close(self) -> None:
        async with self._refresh_lock:
            self._closed = True
            snapshots = set(self._superseded)
            if self._current is not None:
                snapshots.add(self._current)
            self._current = None
            self._superseded.clear()
        for snapshot in snapshots:
            if snapshot.active_users:
                logger.warning(
                    "Closing object-store snapshot with active operations",
                    extra={
                        "revision": snapshot.revision,
                        "active_operations": snapshot.active_users,
                    },
                )
            await snapshot.lease.store.close()

    async def _publish(
        self,
        stored: StoredObjectStoreConnection | None,
    ) -> None:
        service = self._connection_service
        if stored is not None:
            if service is None:
                raise RuntimeError("Connection service is required for stored settings")
            settings = service.settings_for(stored)
            replacement = _ObjectStoreSnapshot(
                revision=stored.revision,
                source=ObjectStoreConnectionSource.ADMIN,
                stored=stored,
                lease=ObjectStoreLease(
                    settings=settings,
                    store=self._store_factory(settings),
                    slot=ACTIVE_DESTINATION_SLOT,
                    revision=stored.revision,
                ),
            )
        elif self._legacy_settings is not None:
            replacement = _ObjectStoreSnapshot(
                revision=UNSTORED_CONNECTION_REVISION,
                source=ObjectStoreConnectionSource.ENVIRONMENT,
                stored=None,
                lease=ObjectStoreLease(
                    settings=self._legacy_settings,
                    store=self._store_factory(self._legacy_settings),
                    slot=ACTIVE_DESTINATION_SLOT,
                    revision=UNSTORED_CONNECTION_REVISION,
                ),
            )
        else:
            replacement = None

        previous = self._current
        self._current = replacement
        if previous is not None:
            previous.superseded = True
            if previous.active_users:
                self._superseded.add(previous)
                logger.info(
                    "Object-store credentials rotated with operations still active",
                    extra={
                        "previous_revision": previous.revision,
                        "active_operations": previous.active_users,
                    },
                )
            else:
                await previous.lease.store.close()

    async def _close_superseded(self, snapshot: _ObjectStoreSnapshot) -> None:
        if snapshot not in self._superseded:
            return
        self._superseded.remove(snapshot)
        await snapshot.lease.store.close()
