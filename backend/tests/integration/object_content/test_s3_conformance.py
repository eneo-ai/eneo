import asyncio
import base64
from collections.abc import AsyncIterator
from hashlib import sha256
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from botocore.session import get_session

from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import ByteRange, capture_content
from eneo.object_content.s3_object_store import (
    ObjectStoreBindingError,
    ObjectStoreNotFoundError,
    ObjectStoreUnavailableError,
    S3ObjectStore,
    new_object_key,
)
from tests.integration.object_content.conftest import RealObjectStore

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_MEBIBYTE = 1024 * 1024


async def _chunks(payload: bytes, size: int = 37_777) -> AsyncIterator[bytes]:
    for offset in range(0, len(payload), size):
        yield payload[offset : offset + size]


async def _read_all(
    store: S3ObjectStore,
    key: str,
    *,
    size_bytes: int,
) -> bytes:
    received = bytearray()
    async with store.open_read(
        key,
        expected_size_bytes=size_bytes,
        expected_media_type="application/octet-stream",
    ) as opened:
        async for chunk in opened.chunks:
            received.extend(chunk)
    return bytes(received)


def _raw_client(
    real_store: RealObjectStore,
    *,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
) -> "S3Client":
    settings = real_store.settings
    return cast(
        "S3Client",
        get_session().create_client(
            "s3",
            endpoint_url=settings.endpoint_url,
            region_name=settings.region,
            aws_access_key_id=(
                access_key_id or settings.access_key_id.get_secret_value()
            ),
            aws_secret_access_key=(
                secret_access_key or settings.secret_access_key.get_secret_value()
            ),
            verify=(
                str(settings.ca_bundle) if settings.ca_bundle is not None else True
            ),
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": settings.addressing_style},
            ),
        ),
    )


async def _read_raw_range(
    real_store: RealObjectStore,
    key: str,
    *,
    byte_range: ByteRange,
) -> bytes:
    client = _raw_client(real_store)
    try:
        result = await asyncio.to_thread(
            client.get_object,
            Bucket=real_store.settings.bucket,
            Key=key,
            Range=byte_range.request_header,
        )
        body = result["Body"]
        try:
            payload = await asyncio.to_thread(
                body.read,
                byte_range.content_length + 1,
            )
        finally:
            await asyncio.to_thread(body.close)
    finally:
        client.close()

    assert result["ContentLength"] == byte_range.content_length
    assert result["ContentRange"] == byte_range.response_header
    assert result["ContentType"] == "application/octet-stream"
    assert len(payload) == byte_range.content_length
    return payload


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
async def test_real_store_single_multipart_range_list_and_delete(
    real_object_store: RealObjectStore,
) -> None:
    store = real_object_store.store
    settings = real_object_store.settings
    single_payload = bytes(range(251)) * 127
    single_key = new_object_key(settings)
    async with capture_content(
        _chunks(single_payload),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        maximum_size_bytes=len(single_payload),
        spool_memory_bytes=settings.spool_memory_bytes,
        multipart_part_bytes=settings.multipart_part_bytes,
    ) as captured:
        head = await store.upload(single_key, captured)
        assert head.size_bytes == len(single_payload)
        assert (
            await store.recompute_sha256(
                single_key,
                expected_size_bytes=len(single_payload),
                expected_media_type="application/octet-stream",
            )
            == sha256(single_payload).digest()
        )

    byte_range = ByteRange.parse("bytes=113-1087", size_bytes=len(single_payload))
    assert (
        await _read_raw_range(
            real_object_store,
            single_key,
            byte_range=byte_range,
        )
        == single_payload[113:1088]
    )

    multipart_payload = b"m" * (6 * _MEBIBYTE + 19)
    multipart_key = new_object_key(settings)
    async with capture_content(
        _chunks(multipart_payload),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        maximum_size_bytes=len(multipart_payload),
        spool_memory_bytes=settings.spool_memory_bytes,
        multipart_part_bytes=settings.multipart_part_bytes,
    ) as captured:
        head = await store.upload(multipart_key, captured)
        assert head.size_bytes == len(multipart_payload)
        assert head.checksum_type == "COMPOSITE"
        assert (
            await _read_all(
                store,
                multipart_key,
                size_bytes=len(multipart_payload),
            )
            == multipart_payload
        )

    page = await store.list_object_page()
    listed = {item.key for item in page.objects}
    assert {single_key, multipart_key} <= listed

    await store.delete_and_confirm(single_key)
    await store.delete_and_confirm(multipart_key)
    with pytest.raises(ObjectStoreNotFoundError):
        await store.head(single_key)


@pytest.mark.asyncio
async def test_real_store_rejects_wrong_checksum_and_bucket_escape(
    real_object_store: RealObjectStore,
) -> None:
    client = _raw_client(real_object_store)
    settings = real_object_store.settings
    wrong_credentials = _raw_client(
        real_object_store,
        access_key_id="wrong-object-content-key",
        secret_access_key="wrong-object-content-secret",
    )
    try:
        with pytest.raises(ClientError) as checksum_error:
            client.put_object(
                Bucket=settings.bucket,
                Key=new_object_key(settings),
                Body=b"trusted bytes",
                ContentLength=13,
                ContentType="application/octet-stream",
                ChecksumSHA256=base64.b64encode(bytes(32)).decode(),
            )
        assert checksum_error.value.response["Error"]["Code"] in {
            "BadDigest",
            "InvalidRequest",
        }

        with pytest.raises(ClientError) as bucket_error:
            client.list_objects_v2(Bucket="outside-object-content-test")
        assert bucket_error.value.response["Error"]["Code"] in {
            "AccessDenied",
            "NoSuchBucket",
        }
        with pytest.raises(ClientError) as credential_error:
            wrong_credentials.list_objects_v2(Bucket=settings.bucket)
        assert credential_error.value.response["ResponseMetadata"][
            "HTTPStatusCode"
        ] in {
            401,
            403,
        }
    finally:
        client.close()
        wrong_credentials.close()


@pytest.mark.asyncio
async def test_real_store_lists_and_aborts_multipart_and_rejects_part_reordering(
    real_object_store: RealObjectStore,
) -> None:
    client = _raw_client(real_object_store)
    settings = real_object_store.settings
    key = new_object_key(settings)
    upload_id: str | None = None
    try:
        created = client.create_multipart_upload(
            Bucket=settings.bucket,
            Key=key,
            ContentType="application/octet-stream",
            ChecksumAlgorithm="SHA256",
            ChecksumType="COMPOSITE",
        )
        upload_id = created["UploadId"]
        first = b"a" * (5 * _MEBIBYTE)
        second = b"b" * _MEBIBYTE
        uploaded_parts: list[dict[str, object]] = []
        for number, payload in enumerate((first, second), start=1):
            checksum = base64.b64encode(sha256(payload).digest()).decode()
            result = client.upload_part(
                Bucket=settings.bucket,
                Key=key,
                UploadId=upload_id,
                PartNumber=number,
                Body=payload,
                ContentLength=len(payload),
                ChecksumSHA256=checksum,
            )
            uploaded_parts.append(
                {
                    "ETag": result["ETag"],
                    "ChecksumSHA256": checksum,
                    "PartNumber": number,
                }
            )

        listed_parts = client.list_parts(
            Bucket=settings.bucket,
            Key=key,
            UploadId=upload_id,
        )["Parts"]
        assert [part["PartNumber"] for part in listed_parts] == [1, 2]
        assert [part["Size"] for part in listed_parts] == [len(first), len(second)]

        page = await real_object_store.store.list_multipart_page()
        assert any(
            item.key == key and item.upload_id == upload_id for item in page.uploads
        )
        with pytest.raises(ClientError) as order_error:
            client.complete_multipart_upload(
                Bucket=settings.bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": list(reversed(uploaded_parts))},
                ChecksumType="COMPOSITE",
            )
        assert order_error.value.response["Error"]["Code"] in {
            "InvalidPartOrder",
            "InvalidPart",
        }
        await real_object_store.store.abort_multipart(key, upload_id)
        upload_id = None
        page = await real_object_store.store.list_multipart_page()
        assert all(item.key != key for item in page.uploads)
    finally:
        if upload_id is not None:
            await real_object_store.store.abort_multipart(key, upload_id)
        client.close()


@pytest.mark.asyncio
async def test_store_process_restart_preserves_bytes_and_readiness_recovers(
    real_object_store: RealObjectStore,
) -> None:
    store = real_object_store.store
    settings = real_object_store.settings
    payload = b"restart-durable-object-content"
    key = new_object_key(settings)
    async with capture_content(
        _chunks(payload),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        maximum_size_bytes=len(payload),
        spool_memory_bytes=settings.spool_memory_bytes,
        multipart_part_bytes=settings.multipart_part_bytes,
    ) as captured:
        await store.upload(key, captured)

    real_object_store.stop_process()
    with pytest.raises(ObjectStoreUnavailableError):
        await store.check_ready()

    real_object_store.start_process()
    for _attempt in range(120):
        try:
            await store.check_ready()
        except ObjectStoreUnavailableError:
            await asyncio.sleep(0.25)
        else:
            break
    else:
        pytest.fail("SeaweedFS did not become ready after process restart")

    assert await _read_all(store, key, size_bytes=len(payload)) == payload
    await store.delete_and_confirm(key)


@pytest.mark.asyncio
async def test_real_store_binding_create_is_atomic_and_never_overwrites(
    real_object_store: RealObjectStore,
) -> None:
    settings = real_object_store.settings
    marker_key = f"v1/.eneo-bindings/{settings.deployment_id.hex}"
    client = _raw_client(real_object_store)
    binding_id = uuid4()
    try:
        await _clear_deployment_namespace(real_object_store, client)

        await asyncio.gather(
            real_object_store.store.ensure_binding(binding_id, allow_create=True),
            real_object_store.store.ensure_binding(binding_id, allow_create=True),
        )
        await real_object_store.store.ensure_binding(
            binding_id,
            allow_create=False,
        )

        with pytest.raises(ObjectStoreBindingError, match="another database"):
            await real_object_store.store.ensure_binding(
                uuid4(),
                allow_create=True,
            )
    finally:
        client.delete_object(Bucket=settings.bucket, Key=marker_key)
        client.close()


@pytest.mark.asyncio
async def test_real_store_tls_requires_and_accepts_custom_ca(
    real_tls_object_store: RealObjectStore,
) -> None:
    trusted = real_tls_object_store.store
    settings = real_tls_object_store.settings
    untrusted_settings = ObjectContentSettings(
        _env_file=None,
        endpoint_url=settings.endpoint_url,
        region=settings.region,
        bucket=settings.bucket,
        access_key_id=settings.access_key_id,
        secret_access_key=settings.secret_access_key,
        deployment_id=settings.deployment_id,
    )
    untrusted = S3ObjectStore(untrusted_settings)
    try:
        with pytest.raises(ObjectStoreUnavailableError):
            await untrusted.check_ready()
    finally:
        await untrusted.close()

    payload = b"private-ca-object-content"
    key = new_object_key(settings)
    async with capture_content(
        _chunks(payload),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        maximum_size_bytes=len(payload),
        spool_memory_bytes=settings.spool_memory_bytes,
        multipart_part_bytes=settings.multipart_part_bytes,
    ) as captured:
        await trusted.upload(key, captured)

    byte_range = ByteRange.parse("bytes=8-15", size_bytes=len(payload))
    assert (
        await _read_raw_range(
            real_tls_object_store,
            key,
            byte_range=byte_range,
        )
        == payload[8:16]
    )
    await trusted.delete_and_confirm(key)
