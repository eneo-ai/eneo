from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.object_content_table import (
    ObjectContentReconciliationState,
)
from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import ObjectContentUnavailableError
from eneo.object_content.runtime import (
    ObjectContentReadinessCode,
    ObjectContentRuntime,
    ObjectContentRuntimeState,
)
from eneo.object_content.s3_object_store import (
    ObjectStoreUnavailableError,
    S3ObjectStore,
    StoreBindingCreation,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class _ReadinessDatabase(DatabaseSessionManager):
    def __init__(
        self,
        *,
        available: bool = True,
        active_object_content: bool = False,
    ) -> None:
        super().__init__()
        self.available = available
        self.active_object_content = active_object_content
        self.binding_state = ObjectContentReconciliationState()
        self.connect_count = 0
        self.connect_in_flight = 0
        self.peak_connect_in_flight = 0

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[AsyncConnection]:
        self.connect_count += 1
        self.connect_in_flight += 1
        self.peak_connect_in_flight = max(
            self.peak_connect_in_flight,
            self.connect_in_flight,
        )
        try:
            # Force overlap so this test proves the runtime lock is load-bearing.
            await asyncio.sleep(0)
            if not self.available:
                raise OSError("test PostgreSQL outage")
            connection = MagicMock(spec=AsyncConnection)
            result = MagicMock()
            result.scalar_one.return_value = self.active_object_content
            connection.execute = AsyncMock(return_value=result)
            yield cast(AsyncConnection, connection)
        finally:
            self.connect_in_flight -= 1

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        session = MagicMock(spec=AsyncSession)
        result = MagicMock()
        result.one_or_none.return_value = self.binding_state
        session.scalars = AsyncMock(return_value=result)
        snapshot = MagicMock()
        snapshot.one_or_none.side_effect = lambda: (
            self.binding_state.store_deployment_id,
            self.binding_state.store_binding_id,
            self.binding_state.store_binding_confirmed_at,
            self.binding_state.store_binding_create_started_at,
        )
        session.execute = AsyncMock(return_value=snapshot)

        async def scalar(statement: object) -> object:
            if "now()" in str(statement).lower():
                return datetime.now(UTC)
            return False

        session.scalar = AsyncMock(side_effect=scalar)
        session.flush = AsyncMock()
        transaction = AsyncMock()
        transaction.__aenter__.return_value = None
        transaction.__aexit__.return_value = None
        session.begin = MagicMock(return_value=transaction)
        yield cast(AsyncSession, session)


class _ReadinessStore:
    def __init__(self, ready: list[bool] | None = None) -> None:
        self._ready = list(ready or [True])
        self.closed = False
        self.check_ready_count = 0
        self.binding_created = False

    async def check_ready(self) -> None:
        self.check_ready_count += 1
        ready = self._ready.pop(0) if len(self._ready) > 1 else self._ready[0]
        if not ready:
            raise ObjectStoreUnavailableError("test object-store outage")

    async def verify_binding(self, _binding_id: UUID) -> bool:
        return self.binding_created

    async def prepare_binding_creation(
        self,
        binding_id: UUID,
    ) -> StoreBindingCreation | None:
        if self.binding_created:
            return None
        return StoreBindingCreation(
            binding_id=binding_id,
            body=b"test binding",
            checksum_sha256="test checksum",
        )

    async def create_binding(self, _creation: StoreBindingCreation) -> None:
        self.binding_created = True

    async def close(self) -> None:
        self.closed = True


def _settings() -> ObjectContentSettings:
    return ObjectContentSettings(
        _env_file=None,
        endpoint_url="http://object-content:8333",
        region="local",
        bucket="eneo-content",
        access_key_id="test-access",
        secret_access_key="test-secret",
        deployment_id=UUID("a2d539af-fef0-42aa-a7f8-14376947be2c"),
        allow_insecure_http=True,
    )


def test_runtime_fails_closed_before_start() -> None:
    runtime = ObjectContentRuntime()

    with pytest.raises(ObjectContentUnavailableError, match="not initialized"):
        runtime.service


@pytest.mark.asyncio
async def test_absent_configuration_is_an_explicit_healthy_disabled_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in tuple(os.environ):
        if name.upper().startswith("OBJECT_CONTENT_"):
            monkeypatch.delenv(name, raising=False)
    runtime = ObjectContentRuntime(database=_ReadinessDatabase())

    runtime.start()
    await runtime.validate_configuration()
    readiness = await runtime.readiness()
    reconciliation = await runtime.reconcile_once()

    assert runtime.state is ObjectContentRuntimeState.DISABLED
    assert runtime.enabled is False
    assert readiness.ready is True
    assert readiness.code is ObjectContentReadinessCode.DISABLED
    assert reconciliation.content_processed == 0
    assert reconciliation.object_cycle_completed is False
    with pytest.raises(ObjectContentUnavailableError, match="disabled") as error:
        runtime.service
    assert error.value.code == "object_content_disabled"

    await runtime.stop()
    assert runtime.state is ObjectContentRuntimeState.NOT_STARTED


@pytest.mark.asyncio
async def test_disabled_runtime_fails_closed_when_active_content_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in tuple(os.environ):
        if name.upper().startswith("OBJECT_CONTENT_"):
            monkeypatch.delenv(name, raising=False)
    runtime = ObjectContentRuntime(
        database=_ReadinessDatabase(active_object_content=True)
    )
    runtime.start()

    with pytest.raises(ObjectContentUnavailableError, match="active records"):
        await runtime.validate_configuration()
    readiness = await runtime.readiness()

    assert readiness.ready is False
    assert readiness.code is ObjectContentReadinessCode.CONFIGURATION_REQUIRED
    with pytest.raises(ObjectContentUnavailableError, match="active records"):
        await runtime.reconcile_once()


@pytest.mark.asyncio
async def test_reconciliation_before_start_remains_a_loud_initialization_error() -> (
    None
):
    runtime = ObjectContentRuntime(database=_ReadinessDatabase())

    with pytest.raises(ObjectContentUnavailableError, match="not initialized"):
        await runtime.reconcile_once()


@pytest.mark.asyncio
async def test_readiness_recovers_after_cache_expiry_without_process_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    monkeypatch.setattr("eneo.object_content.runtime.monotonic", lambda: now)
    store = _ReadinessStore([False, True])
    runtime = ObjectContentRuntime(database=_ReadinessDatabase())
    runtime.start(settings=_settings(), store=cast("S3ObjectStore", store))

    unavailable = await runtime.readiness()
    cached_unavailable = await runtime.readiness()
    now = 1.1
    recovered = await runtime.readiness()

    assert unavailable.ready is False
    assert unavailable.code is ObjectContentReadinessCode.STORE_UNAVAILABLE
    assert cached_unavailable == unavailable
    assert store.check_ready_count == 2
    assert recovered.ready is True
    assert recovered.code is ObjectContentReadinessCode.READY

    await runtime.stop()
    assert store.closed


@pytest.mark.asyncio
async def test_readiness_reports_database_outage_and_recovers_after_cache_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    monkeypatch.setattr("eneo.object_content.runtime.monotonic", lambda: now)
    store = _ReadinessStore()
    database = _ReadinessDatabase(available=False)
    runtime = ObjectContentRuntime(database=database)
    runtime.start(settings=_settings(), store=cast("S3ObjectStore", store))

    unavailable = await runtime.readiness()
    database.available = True
    cached_unavailable = await runtime.readiness()
    now = 1.1
    recovered = await runtime.readiness()

    assert unavailable.ready is False
    assert unavailable.code is ObjectContentReadinessCode.DATABASE_UNAVAILABLE
    assert cached_unavailable == unavailable
    assert database.connect_count == 2
    assert recovered.ready is True
    assert recovered.code is ObjectContentReadinessCode.READY

    await runtime.stop()


@pytest.mark.asyncio
async def test_concurrent_enabled_readiness_coalesces_dependency_probes_and_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    monkeypatch.setattr(
        "eneo.object_content.runtime.monotonic",
        lambda: now,
    )
    store = _ReadinessStore()
    database = _ReadinessDatabase()
    runtime = ObjectContentRuntime(database=database)
    runtime.start(settings=_settings(), store=cast("S3ObjectStore", store))

    readiness = await asyncio.gather(*(runtime.readiness() for _ in range(16)))

    assert all(result.ready for result in readiness)
    assert {result.code for result in readiness} == {ObjectContentReadinessCode.READY}
    assert database.connect_count == 1
    assert database.peak_connect_in_flight == 1
    assert store.check_ready_count == 1

    now = 1.1
    refreshed = await runtime.readiness()

    assert refreshed.ready is True
    assert database.connect_count == 2
    assert store.check_ready_count == 2

    await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_stop_is_idempotent() -> None:
    client = MagicMock()
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))
    runtime = ObjectContentRuntime(database=_ReadinessDatabase())
    runtime.start(settings=_settings(), store=store)

    await runtime.stop()
    await runtime.stop()

    client.close.assert_called_once_with()
