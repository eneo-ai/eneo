import base64
import re
from hashlib import sha256
from io import BytesIO
from typing import TYPE_CHECKING, BinaryIO, cast
from uuid import UUID

import pytest
from botocore.exceptions import FlexibleChecksumError, ReadTimeoutError
from botocore.response import StreamingBody

from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import CapturedContent
from eneo.object_content.s3_object_store import (
    ObjectStoreIntegrityError,
    ObjectStoreUnavailableError,
    S3ObjectStore,
    _FileSlice,
    composite_sha256,
    new_object_key,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


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


def test_object_keys_are_opaque_and_deployment_scoped() -> None:
    first = new_object_key(_settings())
    second = new_object_key(_settings())

    assert first != second
    assert re.fullmatch(r"v1/a2d539affef042aaa7f814376947be2c/[0-9a-f]{32}", first)
    assert "tenant" not in first
    assert "filename" not in first


def test_multipart_sha256_is_composite_and_not_the_canonical_digest() -> None:
    parts = (sha256(b"first").digest(), sha256(b"second").digest())

    composite = composite_sha256(parts)
    canonical = sha256(b"firstsecond").digest()

    assert (
        composite == f"{base64.b64encode(sha256(b''.join(parts)).digest()).decode()}-2"
    )
    assert base64.b64decode(composite.removesuffix("-2")) != canonical


def test_file_slice_bounds_unbounded_reader_requests() -> None:
    source = BytesIO(b"0123456789")
    part = _FileSlice(
        source,
        start=1,
        length=8,
        maximum_read_bytes=3,
    )

    assert part.read() == b"123"
    assert part.read() == b"456"
    assert part.read() == b"78"
    assert part.read() == b""


class _SingleUploadClient:
    def __init__(self, expected_checksum: str) -> None:
        self.expected_checksum = expected_checksum
        self.head_calls = 0

    def put_object(self, **request: object) -> dict[str, str]:
        assert request["ChecksumSHA256"] == self.expected_checksum
        return {"ChecksumSHA256": self.expected_checksum}

    def head_object(self, **request: object) -> dict[str, object]:
        self.head_calls += 1
        return {
            "ContentLength": 7,
            "ContentType": "text/plain",
            "ChecksumSHA256": self.expected_checksum,
            "ChecksumType": "FULL_OBJECT",
        }


class _EscapedInventoryClient:
    def list_objects_v2(self, **_request: object) -> dict[str, object]:
        return {"Contents": [{"Key": "another-deployment/object", "Size": 1}]}


class _MultipartUploadClient:
    def __init__(self, *, size_bytes: int, composite_checksum: str) -> None:
        self._size_bytes = size_bytes
        self._composite_checksum = composite_checksum

    def create_multipart_upload(self, **_request: object) -> dict[str, str]:
        return {"UploadId": "bounded-upload"}

    def upload_part(self, **request: object) -> dict[str, str]:
        body = cast(BinaryIO, request["Body"])
        while body.read(1024 * 1024):
            pass
        return {
            "ChecksumSHA256": cast(str, request["ChecksumSHA256"]),
            "ETag": f'"part-{request["PartNumber"]}"',
        }

    def complete_multipart_upload(self, **_request: object) -> dict[str, str]:
        return {
            "ChecksumSHA256": self._composite_checksum,
            "ChecksumType": "COMPOSITE",
        }

    def head_object(self, **_request: object) -> dict[str, object]:
        return {
            "ContentLength": self._size_bytes,
            "ContentType": "application/octet-stream",
            "ChecksumSHA256": self._composite_checksum,
            "ChecksumType": "COMPOSITE",
        }


class _DownloadClient:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def get_object(self, **_request: object) -> dict[str, object]:
        return {
            "Body": StreamingBody(BytesIO(self._payload), len(self._payload)),
            "ContentLength": len(self._payload),
            "ContentType": "application/octet-stream",
        }


class _MidStreamTimeoutBody:
    def __init__(self) -> None:
        self._reads = 0
        self.closed = False

    def read(self, _size: int) -> bytes:
        self._reads += 1
        if self._reads == 1:
            return b"part"
        raise ReadTimeoutError(
            endpoint_url="https://object-content.example.test",
            error=TimeoutError("injected mid-stream timeout"),
        )

    def close(self) -> None:
        self.closed = True


class _MidStreamTimeoutClient:
    def __init__(self) -> None:
        self.body = _MidStreamTimeoutBody()

    def get_object(self, **_request: object) -> dict[str, object]:
        return {
            "Body": self.body,
            "ContentLength": 8,
            "ContentType": "application/octet-stream",
        }


class _ChecksumFailureBody(_MidStreamTimeoutBody):
    def read(self, _size: int) -> bytes:
        raise FlexibleChecksumError(error_msg="injected checksum mismatch")


class _ChecksumFailureClient:
    def __init__(self) -> None:
        self.body = _ChecksumFailureBody()

    def get_object(self, **_request: object) -> dict[str, object]:
        return {
            "Body": self.body,
            "ContentLength": 8,
            "ContentType": "application/octet-stream",
        }


@pytest.mark.asyncio
async def test_single_upload_verifies_with_one_head_request() -> None:
    payload = b"content"
    digest = sha256(payload).digest()
    checksum = base64.b64encode(digest).decode()
    client = _SingleUploadClient(checksum)
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))
    captured = CapturedContent(
        file=BytesIO(payload),
        sha256=digest,
        size_bytes=len(payload),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        part_sha256=(digest,),
    )

    head = await store.upload(new_object_key(_settings()), captured)

    assert head.size_bytes == len(payload)
    assert client.head_calls == 1


@pytest.mark.asyncio
async def test_remote_inventory_cannot_escape_the_deployment_prefix() -> None:
    client = cast("S3Client", _EscapedInventoryClient())
    store = S3ObjectStore(_settings(), client=client)

    with pytest.raises(ObjectStoreIntegrityError, match="deployment prefix"):
        await store.list_object_page()


@pytest.mark.asyncio
async def test_multipart_upload_emits_bounded_lease_checkpoints() -> None:
    mebibyte = 1024 * 1024
    part_bytes = 5 * mebibyte
    payload = b"a" * part_bytes + b"b"
    part_digests = (
        sha256(payload[:part_bytes]).digest(),
        sha256(payload[part_bytes:]).digest(),
    )
    client = _MultipartUploadClient(
        size_bytes=len(payload),
        composite_checksum=composite_sha256(part_digests),
    )
    settings = ObjectContentSettings(
        _env_file=None,
        endpoint_url="http://object-content:8333",
        region="local",
        bucket="eneo-content",
        access_key_id="test-access",
        secret_access_key="test-secret",
        deployment_id=UUID("a2d539af-fef0-42aa-a7f8-14376947be2c"),
        allow_insecure_http=True,
        multipart_part_bytes=part_bytes,
        multipart_threshold_bytes=part_bytes,
    )
    store = S3ObjectStore(settings, client=cast("S3Client", client))
    captured = CapturedContent(
        file=BytesIO(payload),
        sha256=sha256(payload).digest(),
        size_bytes=len(payload),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        part_sha256=part_digests,
    )
    checkpoints = 0

    async def checkpoint() -> None:
        nonlocal checkpoints
        checkpoints += 1

    await store.upload(
        new_object_key(settings),
        captured,
        upload_checkpoint=checkpoint,
    )

    assert checkpoints == 4  # two parts, completion, and verification HEAD


@pytest.mark.asyncio
async def test_full_rehash_emits_checkpoints_around_each_bounded_read() -> None:
    payload = b"0123456789"
    settings = ObjectContentSettings(
        _env_file=None,
        endpoint_url="http://object-content:8333",
        region="local",
        bucket="eneo-content",
        access_key_id="test-access",
        secret_access_key="test-secret",
        deployment_id=UUID("a2d539af-fef0-42aa-a7f8-14376947be2c"),
        allow_insecure_http=True,
        io_chunk_bytes=4,
        spool_memory_bytes=4,
    )
    store = S3ObjectStore(
        settings,
        client=cast("S3Client", _DownloadClient(payload)),
    )
    checkpoints = 0

    async def checkpoint() -> None:
        nonlocal checkpoints
        checkpoints += 1

    digest = await store.recompute_sha256(
        new_object_key(settings),
        expected_size_bytes=len(payload),
        expected_media_type="application/octet-stream",
        read_checkpoint=checkpoint,
    )

    assert digest == sha256(payload).digest()
    # Before GET, before each of three reads, and before the terminal read.
    assert checkpoints == 5


@pytest.mark.asyncio
async def test_mid_stream_timeout_is_retryable_and_closes_the_body() -> None:
    client = _MidStreamTimeoutClient()
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))

    with pytest.raises(ObjectStoreUnavailableError, match="stream interrupted"):
        async with store.open_read(
            new_object_key(_settings()),
            expected_size_bytes=8,
            expected_media_type="application/octet-stream",
        ) as opened:
            _ = b"".join([chunk async for chunk in opened.chunks])

    assert client.body.closed


@pytest.mark.asyncio
async def test_stream_checksum_failure_remains_an_integrity_error() -> None:
    client = _ChecksumFailureClient()
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))

    with pytest.raises(ObjectStoreIntegrityError, match="checksum failed"):
        async with store.open_read(
            new_object_key(_settings()),
            expected_size_bytes=8,
            expected_media_type="application/octet-stream",
        ) as opened:
            _ = b"".join([chunk async for chunk in opened.chunks])

    assert client.body.closed
