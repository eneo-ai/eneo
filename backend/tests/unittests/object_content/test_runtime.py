from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from botocore.exceptions import ClientError
from sqlalchemy.ext.asyncio import AsyncConnection

from eneo.database.database import DatabaseSessionManager
from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import ObjectContentUnavailableError
from eneo.object_content.runtime import (
    ObjectContentReadinessCode,
    ObjectContentRuntime,
)
from eneo.object_content.s3_object_store import S3ObjectStore

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class _ReadinessDatabase(DatabaseSessionManager):
    def __init__(self, *, available: bool = True) -> None:
        super().__init__()
        self.available = available

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[AsyncConnection]:
        if not self.available:
            raise OSError("test PostgreSQL outage")
        connection = MagicMock(spec=AsyncConnection)
        connection.execute.return_value = None
        yield cast(AsyncConnection, connection)


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
async def test_readiness_recovers_without_restarting_the_process() -> None:
    client = MagicMock()
    client.list_objects_v2.side_effect = [
        ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "unavailable"}},
            "ListObjectsV2",
        ),
        {"Contents": []},
    ]
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))
    runtime = ObjectContentRuntime(database=_ReadinessDatabase())
    runtime.start(settings=_settings(), store=store)

    unavailable = await runtime.readiness()
    recovered = await runtime.readiness()

    assert unavailable.ready is False
    assert unavailable.code is ObjectContentReadinessCode.STORE_UNAVAILABLE
    assert recovered.ready is True
    assert recovered.code is ObjectContentReadinessCode.READY

    await runtime.stop()
    client.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_readiness_reports_database_outage_without_leaking_details() -> None:
    client = MagicMock()
    client.list_objects_v2.return_value = {"Contents": []}
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))
    database = _ReadinessDatabase(available=False)
    runtime = ObjectContentRuntime(database=database)
    runtime.start(settings=_settings(), store=store)

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
