from __future__ import annotations

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

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[AsyncConnection]:
        if not self.available:
            raise OSError("test PostgreSQL outage")
        connection = MagicMock(spec=AsyncConnection)
        result = MagicMock()
        result.scalar_one.return_value = self.active_object_content
        connection.execute = AsyncMock(return_value=result)
        yield cast(AsyncConnection, connection)

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        session = MagicMock(spec=AsyncSession)
        result = MagicMock()
        result.one_or_none.return_value = self.binding_state
        session.scalars = AsyncMock(return_value=result)

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

    async def check_ready(self) -> None:
        ready = self._ready.pop(0) if len(self._ready) > 1 else self._ready[0]
        if not ready:
            raise ObjectStoreUnavailableError("test object-store outage")

    async def ensure_binding(
        self,
        _binding_id: UUID,
        *,
        allow_create: bool,
    ) -> None:
        assert allow_create

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
async def test_readiness_recovers_without_restarting_the_process() -> None:
    store = _ReadinessStore([False, True])
    runtime = ObjectContentRuntime(database=_ReadinessDatabase())
    runtime.start(settings=_settings(), store=cast("S3ObjectStore", store))

    unavailable = await runtime.readiness()
    recovered = await runtime.readiness()

    assert unavailable.ready is False
    assert unavailable.code is ObjectContentReadinessCode.STORE_UNAVAILABLE
    assert recovered.ready is True
    assert recovered.code is ObjectContentReadinessCode.READY

    await runtime.stop()
    assert store.closed


@pytest.mark.asyncio
async def test_readiness_reports_database_outage_without_leaking_details() -> None:
    store = _ReadinessStore()
    database = _ReadinessDatabase(available=False)
    runtime = ObjectContentRuntime(database=database)
    runtime.start(settings=_settings(), store=cast("S3ObjectStore", store))

    unavailable = await runtime.readiness()
    database.available = True
    recovered = await runtime.readiness()

    assert unavailable.ready is False
    assert unavailable.code is ObjectContentReadinessCode.DATABASE_UNAVAILABLE
    assert recovered.ready is True
    assert recovered.code is ObjectContentReadinessCode.READY

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
