"""A store that keeps old versions of deleted bytes is never reported removed.

A delete in a versioned bucket only adds a delete marker: the bytes stay
readable through their version. A bucket with versioning, suspended
versioning or Object Lock therefore refuses to start, so do credentials that
cannot read those settings, and a delete is confirmed only when no version of
the bytes is left.
"""

import asyncio
import json
import os
from collections.abc import Generator
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import boto3
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from eneo.database.database import DatabaseSessionManager
from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import (
    ObjectContentConfigurationError,
    ObjectContentError,
)
from eneo.object_content.s3_object_store import (
    ObjectStoreError,
    S3ObjectStore,
    new_object_key,
)
from eneo.object_content.store_binding import ensure_store_binding_ready
from tests.integration.object_content.conftest import (
    _CONFORMANCE_IMAGE,
    _CONTAINER_BOUND_TEST_FILE_MODE,
    BINDING_CLAIM_SECONDS,
    READINESS_WAIT_SECONDS,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

PLAIN = "finality-plain"
VERSIONED = "finality-versioned"
SUSPENDED = "finality-suspended"
LOCKED = "finality-locked"
LATER_VERSIONED = "finality-later-versioned"
# An identity that may list and write the plain bucket but not read it, so it
# cannot read the bucket's versioning setting.
UNREADABLE = ("finality-unreadable", "finality-unreadable-secret")
_IDENTITIES = {
    "identities": [
        {
            "name": "finality-admin",
            "credentials": [
                {"accessKey": "finality-admin", "secretKey": "finality-admin-secret"}
            ],
            "actions": ["Admin"],
        },
        {
            "name": "finality-unreadable",
            "credentials": [{"accessKey": UNREADABLE[0], "secretKey": UNREADABLE[1]}],
            "actions": [f"List:{PLAIN}", f"Write:{PLAIN}", f"Write:{PLAIN}/*"],
        },
    ]
}


def _admin(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="local",
        aws_access_key_id="finality-admin",
        aws_secret_access_key="finality-admin-secret",
    )


@pytest.fixture(scope="module")
def versioning_endpoint(unused_tcp_port_factory) -> Generator[str, None, None]:
    """A store of its own: the shared one's identity cannot change buckets."""
    with TemporaryDirectory(prefix="eneo-finality-store-") as directory:
        config_path = Path(directory) / "s3.json"
        config_path.write_text(json.dumps(_IDENTITIES), encoding="utf-8")
        os.chmod(config_path, _CONTAINER_BOUND_TEST_FILE_MODE)
        container = (
            DockerContainer(_CONFORMANCE_IMAGE)
            .with_bind_ports(8333, unused_tcp_port_factory())
            .with_volume_mapping(str(config_path), "/etc/seaweedfs/s3.json", mode="ro")
            .with_command(
                "mini -dir=/data "
                f"-bucket={PLAIN},{VERSIONED},{SUSPENDED},{LATER_VERSIONED} "
                "-s3.config=/etc/seaweedfs/s3.json -s3.iam=false "
                "-webdav=false -admin.ui=false -master.telemetry=false"
            )
            .waiting_for(
                LogMessageWaitStrategy(
                    "All enabled components are running"
                ).with_startup_timeout(90)
            )
        )
        yield from _started(container)


def _started(container: DockerContainer) -> Generator[str, None, None]:
    with container:
        endpoint = (
            f"http://{container.get_container_host_ip()}:"
            f"{container.get_exposed_port(8333)}"
        )
        admin = _admin(endpoint)
        enabled = {"Status": "Enabled"}
        admin.put_bucket_versioning(Bucket=VERSIONED, VersioningConfiguration=enabled)
        admin.put_bucket_versioning(Bucket=SUSPENDED, VersioningConfiguration=enabled)
        admin.put_bucket_versioning(
            Bucket=SUSPENDED, VersioningConfiguration={"Status": "Suspended"}
        )
        admin.create_bucket(Bucket=LOCKED, ObjectLockEnabledForBucket=True)
        yield endpoint


def _settings(
    endpoint: str,
    bucket: str,
    credentials: tuple[str, str] = ("finality-admin", "finality-admin-secret"),
) -> ObjectContentSettings:
    return ObjectContentSettings(
        _env_file=None,
        endpoint_url=endpoint,
        region="local",
        bucket=bucket,
        access_key_id=credentials[0],
        secret_access_key=credentials[1],
        deployment_id=uuid4(),
        allow_insecure_http=True,
        readiness_timeout_seconds=READINESS_WAIT_SECONDS,
        binding_claim_seconds=BINDING_CLAIM_SECONDS,
    )


@pytest.mark.parametrize("bucket", [VERSIONED, SUSPENDED, LOCKED])
async def test_a_store_that_keeps_old_versions_refuses_to_start(
    object_content_database: DatabaseSessionManager,
    versioning_endpoint: str,
    bucket: str,
) -> None:
    settings = _settings(versioning_endpoint, bucket)
    store = S3ObjectStore(settings)
    try:
        with pytest.raises(ObjectContentConfigurationError):
            await ensure_store_binding_ready(object_content_database, settings, store)
    finally:
        await store.close()


async def test_a_store_without_old_versions_starts(
    object_content_database: DatabaseSessionManager,
    versioning_endpoint: str,
) -> None:
    """Mutant: every store refuses to start."""
    settings = _settings(versioning_endpoint, PLAIN)
    store = S3ObjectStore(settings)
    try:
        await ensure_store_binding_ready(object_content_database, settings, store)
    finally:
        await store.close()


async def test_credentials_that_cannot_read_versioning_refuse_to_start(
    object_content_database: DatabaseSessionManager,
    versioning_endpoint: str,
) -> None:
    """The refusal names the permission. Mutant: a denied read of the setting
    counts as a bucket without versioning, or as a passing outage."""
    settings = _settings(versioning_endpoint, PLAIN, UNREADABLE)
    store = S3ObjectStore(settings)
    try:
        with pytest.raises(ObjectContentConfigurationError) as refused:
            await ensure_store_binding_ready(object_content_database, settings, store)
    finally:
        await store.close()
    assert "s3:GetBucketVersioning" in str(refused.value)


@pytest.mark.parametrize(
    "versioned_after_start", [False, True], ids=["plain", "versioned later"]
)
async def test_a_delete_is_confirmed_only_when_no_version_of_the_bytes_is_left(
    versioning_endpoint: str,
    versioned_after_start: bool,
) -> None:
    """The bucket was plain when the store started. Mutant for the plain
    case: every delete is refused."""
    bucket = LATER_VERSIONED if versioned_after_start else PLAIN
    admin = _admin(versioning_endpoint)
    settings = _settings(versioning_endpoint, bucket)
    store = S3ObjectStore(settings)
    try:
        await store.check_ready()
        if versioned_after_start:
            await asyncio.to_thread(
                admin.put_bucket_versioning,
                Bucket=bucket,
                VersioningConfiguration={"Status": "Enabled"},
            )
        key = new_object_key(settings)
        await asyncio.to_thread(
            admin.put_object, Bucket=bucket, Key=key, Body=b"removed bytes"
        )

        try:
            await store.delete_and_confirm(key)
        except (ObjectStoreError, ObjectContentError):
            confirmed = False
        else:
            confirmed = True

        listed = await asyncio.to_thread(
            admin.list_object_versions, Bucket=bucket, Prefix=key
        )
        versions_left = [
            version for version in listed.get("Versions", []) if version["Key"] == key
        ]
        assert not (confirmed and versions_left), versions_left
        if not versioned_after_start:
            assert confirmed
    finally:
        await store.close()
