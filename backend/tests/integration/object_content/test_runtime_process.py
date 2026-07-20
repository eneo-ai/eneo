import asyncio
import base64
import os
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
from botocore.config import Config
from botocore.session import get_session
from sqlalchemy import select, text
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config as AlembicConfig
from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.object_content_table import (
    ObjectContentReconciliationState,
    ObjectContents,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.object_content.content import (
    ContentState,
    ObjectContentConfigurationError,
    ObjectContentUnavailableError,
)
from eneo.object_content.reconciliation_repository import (
    ObjectContentReconciliationRepository,
)
from eneo.object_content.runtime import (
    ObjectContentReadinessCode,
    ObjectContentRuntime,
)
from eneo.object_content.s3_object_store import S3ObjectStore, new_object_key
from tests.integration.object_content.conftest import (
    POSTGRES_13_IMAGE,
    RealObjectStore,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


def _raw_client(real_store: RealObjectStore) -> "S3Client":
    settings = real_store.settings
    return cast(
        "S3Client",
        get_session().create_client(
            "s3",
            endpoint_url=settings.endpoint_url,
            region_name=settings.region,
            aws_access_key_id=settings.access_key_id.get_secret_value(),
            aws_secret_access_key=settings.secret_access_key.get_secret_value(),
            verify=True,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": settings.addressing_style},
            ),
        ),
    )


async def _clear_deployment_namespace(
    real_store: RealObjectStore,
    client: "S3Client",
) -> None:
    continuation_token: str | None = None
    while True:
        page = await real_store.store.list_object_page(
            continuation_token=continuation_token
        )
        for item in page.objects:
            await real_store.store.delete_and_confirm(item.key)
        continuation_token = page.next_token
        if continuation_token is None:
            break
    client.delete_object(
        Bucket=real_store.settings.bucket,
        Key=f"v1/.eneo-bindings/{real_store.settings.deployment_id.hex}",
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
        backend_dir = Path(__file__).resolve().parents[3]
        alembic_config = AlembicConfig(str(backend_dir / "alembic.ini"))
        alembic_config.set_main_option(
            "script_location",
            str(backend_dir / "alembic"),
        )
        alembic_config.set_main_option(
            "sqlalchemy.url",
            postgres.get_connection_url(),
        )
        command.upgrade(alembic_config, "head")

        database = DatabaseSessionManager()
        database.init(postgres.get_connection_url().replace("psycopg2", "asyncpg"))
        async with database.connect() as connection:
            server_version = (
                await connection.execute(text("SHOW server_version_num"))
            ).scalar_one()
        assert int(server_version) // 10_000 == 13
        runtime = ObjectContentRuntime(database)
        marker_key = f"v1/.eneo-bindings/{real_object_store.settings.deployment_id.hex}"
        client = _raw_client(real_object_store)
        await _clear_deployment_namespace(real_object_store, client)
        runtime.start(
            settings=real_object_store.settings,
            store=S3ObjectStore(real_object_store.settings),
        )
        try:
            ready = await runtime.readiness()
            assert ready.ready is True
            assert ready.code is ObjectContentReadinessCode.READY

            postgres.get_wrapped_container().stop(timeout=10)
            for _attempt in range(20):
                unavailable = await runtime.readiness()
                if not unavailable.ready:
                    break
                await asyncio.sleep(0.25)
            else:
                pytest.fail("PostgreSQL outage did not fail readiness")
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
            client.delete_object(
                Bucket=real_object_store.settings.bucket,
                Key=marker_key,
            )
            client.close()


@pytest.mark.asyncio
async def test_reachable_unpaired_store_blocks_readiness_and_all_reconciliation(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
    real_unpaired_object_store: RealObjectStore,
) -> None:
    settings = real_object_store.settings
    marker_key = f"v1/.eneo-bindings/{settings.deployment_id.hex}"
    object_key = new_object_key(settings)
    payload = b"paired-object-content"
    digest = sha256(payload).digest()
    store_a_client = _raw_client(real_object_store)
    store_b_client = _raw_client(real_unpaired_object_store)
    runtime_a = ObjectContentRuntime(object_content_database)
    runtime_b = ObjectContentRuntime(object_content_database)
    try:
        await _clear_deployment_namespace(real_object_store, store_a_client)
        await _clear_deployment_namespace(
            real_unpaired_object_store,
            store_b_client,
        )

        runtime_a.start(
            settings=settings,
            store=S3ObjectStore(settings),
        )
        await runtime_a.validate_configuration()

        store_a_client.put_object(
            Bucket=settings.bucket,
            Key=object_key,
            Body=payload,
            ContentLength=len(payload),
            ContentType="application/octet-stream",
            ChecksumSHA256=base64.b64encode(digest).decode(),
        )
        async with object_content_database.session() as session, session.begin():
            tenant_id = (await session.scalars(select(Tenants.id))).one()
            content = ObjectContents(
                tenant_id=tenant_id,
                created_by_user_id=None,
                object_key=object_key,
                state=ContentState.AVAILABLE.value,
                access_class="private_resource",
                sha256=digest,
                size_bytes=len(payload),
                declared_media_type="application/octet-stream",
                verified_media_type="application/octet-stream",
                idempotency_key=uuid4().hex,
                request_fingerprint=digest,
                reference_count=1,
                available_at=datetime.now(UTC),
            )
            session.add(content)
            await session.flush()
            content_id = content.id

        await runtime_a.stop()
        runtime_b.start(
            settings=real_unpaired_object_store.settings,
            store=S3ObjectStore(real_unpaired_object_store.settings),
        )

        readiness = await runtime_b.readiness()
        assert readiness.ready is False
        assert readiness.code is ObjectContentReadinessCode.CONFIGURATION_REQUIRED
        with pytest.raises(ObjectContentConfigurationError):
            await runtime_b.reconcile_once()

        async with object_content_database.session() as session, session.begin():
            row = await session.get(ObjectContents, content_id)
            assert row is not None
            assert row.state == ContentState.AVAILABLE.value
            assert row.failure_code is None
    finally:
        await runtime_a.stop()
        await runtime_b.stop()
        store_a_client.delete_object(Bucket=settings.bucket, Key=object_key)
        store_a_client.delete_object(Bucket=settings.bucket, Key=marker_key)
        store_b_client.delete_object(
            Bucket=real_unpaired_object_store.settings.bucket,
            Key=marker_key,
        )
        store_a_client.close()
        store_b_client.close()


@pytest.mark.asyncio
async def test_concurrent_processes_establish_one_database_store_binding(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    settings = real_object_store.settings
    marker_key = f"v1/.eneo-bindings/{settings.deployment_id.hex}"
    client = _raw_client(real_object_store)
    first = ObjectContentRuntime(object_content_database)
    second = ObjectContentRuntime(object_content_database)
    try:
        await _clear_deployment_namespace(real_object_store, client)
        first.start(settings=settings, store=S3ObjectStore(settings))
        second.start(settings=settings, store=S3ObjectStore(settings))

        await asyncio.gather(
            first.validate_configuration(),
            second.validate_configuration(),
        )

        async with object_content_database.session() as session, session.begin():
            state = await session.get(ObjectContentReconciliationState, 1)
            assert state is not None
            assert state.store_deployment_id == settings.deployment_id
            assert state.store_binding_id is not None
            assert state.store_binding_confirmed_at is not None
    finally:
        await first.stop()
        await second.stop()
        client.delete_object(Bucket=settings.bucket, Key=marker_key)
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "marker_written_before_restart",
    [False, True],
    ids=("database-initialized", "marker-written"),
)
async def test_binding_establishment_recovers_both_crash_windows(
    marker_written_before_restart: bool,
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    settings = real_object_store.settings
    marker_key = f"v1/.eneo-bindings/{settings.deployment_id.hex}"
    client = _raw_client(real_object_store)
    runtime = ObjectContentRuntime(object_content_database)
    try:
        await _clear_deployment_namespace(real_object_store, client)
        async with object_content_database.session() as session, session.begin():
            binding = await ObjectContentReconciliationRepository(
                session
            ).get_or_initialize_store_binding(settings.deployment_id)
        assert not binding.confirmed

        if marker_written_before_restart:
            await real_object_store.store.ensure_binding(
                binding.binding_id,
                allow_create=True,
            )

        runtime.start(settings=settings, store=S3ObjectStore(settings))
        await runtime.validate_configuration()

        async with object_content_database.session() as session, session.begin():
            state = await session.get(ObjectContentReconciliationState, 1)
            assert state is not None
            assert state.store_binding_id == binding.binding_id
            assert state.store_binding_confirmed_at is not None
    finally:
        await runtime.stop()
        client.delete_object(Bucket=settings.bucket, Key=marker_key)
        client.close()
