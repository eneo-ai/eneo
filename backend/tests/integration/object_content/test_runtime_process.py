import asyncio
import os
from collections.abc import Callable

import pytest
from sqlalchemy import select, text
from testcontainers.postgres import PostgresContainer

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.object_content_table import ObjectContents
from eneo.database.tables.tenant_table import Tenants
from eneo.object_content.content import ObjectContentUnavailableError
from eneo.object_content.runtime import (
    ObjectContentReadinessCode,
    ObjectContentRuntime,
)
from eneo.object_content.s3_object_store import S3ObjectStore
from tests.integration.object_content.conftest import (
    POSTGRES_13_IMAGE,
    RealObjectStore,
)


@pytest.mark.asyncio
async def test_disabled_runtime_rejects_active_postgres_content(
    object_content_database: DatabaseSessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in tuple(os.environ):
        if name.upper().startswith("OBJECT_CONTENT_"):
            monkeypatch.delenv(name, raising=False)

    async with object_content_database.session() as session, session.begin():
        tenant_id = (await session.execute(select(Tenants.id).limit(1))).scalar_one()
        session.add(
            ObjectContents(
                tenant_id=tenant_id,
                created_by_user_id=None,
                object_key="v1/disabled-safety-test",
                state="pending",
                access_class="private_resource",
                sha256=b"\0" * 32,
                size_bytes=0,
                declared_media_type="application/octet-stream",
                verified_media_type="application/octet-stream",
                idempotency_key="disabled-safety-test",
                request_fingerprint=b"\0" * 32,
            )
        )

    runtime = ObjectContentRuntime(object_content_database)
    runtime.start()
    try:
        with pytest.raises(ObjectContentUnavailableError, match="active records"):
            await runtime.validate_configuration()

        readiness = await runtime.readiness()
        assert readiness.ready is False
        assert readiness.code is ObjectContentReadinessCode.CONFIGURATION_REQUIRED
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_readiness_tracks_real_postgres_stop_and_restart_without_process_restart(
    real_object_store: RealObjectStore,
    unused_tcp_port_factory: Callable[[], int],
) -> None:
    postgres = PostgresContainer(
        image=POSTGRES_13_IMAGE,
        username="object_content_readiness",
        password="object_content_readiness_password",
        dbname="object_content_readiness",
    )
    postgres.with_bind_ports(5432, unused_tcp_port_factory())
    with postgres:
        database = DatabaseSessionManager()
        database.init(postgres.get_connection_url().replace("psycopg2", "asyncpg"))
        async with database.connect() as connection:
            server_version = (
                await connection.execute(text("SHOW server_version_num"))
            ).scalar_one()
        assert int(server_version) // 10_000 == 13
        runtime = ObjectContentRuntime(database)
        runtime.start(
            settings=real_object_store.settings,
            store=S3ObjectStore(real_object_store.settings),
        )
        try:
            ready = await runtime.readiness()
            assert ready.ready is True
            assert ready.code is ObjectContentReadinessCode.READY

            postgres.get_wrapped_container().stop(timeout=10)
            unavailable = await runtime.readiness()
            assert unavailable.ready is False
            assert unavailable.code is ObjectContentReadinessCode.DATABASE_UNAVAILABLE

            postgres.get_wrapped_container().start()
            for _attempt in range(120):
                recovered = await runtime.readiness()
                if recovered.ready:
                    break
                await asyncio.sleep(0.25)
            else:
                pytest.fail("PostgreSQL readiness did not recover after restart")
            assert recovered.code is ObjectContentReadinessCode.READY
        finally:
            await runtime.stop()
            await database.close()
