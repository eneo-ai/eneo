import asyncio
import base64
import re
from collections.abc import Awaitable, Callable
from hashlib import sha256
from io import BytesIO
from threading import Lock
from typing import TYPE_CHECKING, BinaryIO, TypeVar, cast
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError, FlexibleChecksumError, ReadTimeoutError
from botocore.response import StreamingBody

from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import ByteRange, CapturedContent
from eneo.object_content.s3_object_store import (
    ObjectStoreBindingError,
    ObjectStoreIntegrityError,
    ObjectStoreUnavailableError,
    S3ObjectStore,
    _FileSlice,
    composite_sha256,
    new_object_key,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_ResultT = TypeVar("_ResultT")


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
    def __init__(self, expected_checksum: str, events: list[str] | None = None) -> None:
        self.expected_checksum = expected_checksum
        self.events = events
        self.head_calls = 0

    def put_object(self, **request: object) -> dict[str, str]:
        if self.events is not None:
            self.events.append("put")
        assert request["ChecksumSHA256"] == self.expected_checksum
        return {"ChecksumSHA256": self.expected_checksum}

    def head_object(self, **request: object) -> dict[str, object]:
        if self.events is not None:
            self.events.append("head")
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


class _InvalidPaginationClient:
    def __init__(
        self,
        *,
        object_page: dict[str, object] | None = None,
        multipart_page: dict[str, object] | None = None,
    ) -> None:
        self._object_page = object_page
        self._multipart_page = multipart_page

    def list_objects_v2(self, **_request: object) -> dict[str, object]:
        assert self._object_page is not None
        return self._object_page

    def list_multipart_uploads(self, **_request: object) -> dict[str, object]:
        assert self._multipart_page is not None
        return self._multipart_page


class _MultipartUploadClient:
    def __init__(
        self,
        *,
        size_bytes: int,
        composite_checksum: str,
        events: list[str] | None = None,
    ) -> None:
        self._size_bytes = size_bytes
        self._composite_checksum = composite_checksum
        self.events = events

    def create_multipart_upload(self, **_request: object) -> dict[str, str]:
        if self.events is not None:
            self.events.append("create")
        return {"UploadId": "bounded-upload"}

    def upload_part(self, **request: object) -> dict[str, str]:
        if self.events is not None:
            self.events.append(f"part:{request['PartNumber']}")
        body = cast(BinaryIO, request["Body"])
        while body.read(1024 * 1024):
            pass
        return {
            "ChecksumSHA256": cast(str, request["ChecksumSHA256"]),
            "ETag": f'"part-{request["PartNumber"]}"',
        }

    def complete_multipart_upload(self, **_request: object) -> dict[str, str]:
        if self.events is not None:
            self.events.append("complete")
        return {
            "ChecksumSHA256": self._composite_checksum,
            "ChecksumType": "COMPOSITE",
        }

    def head_object(self, **_request: object) -> dict[str, object]:
        if self.events is not None:
            self.events.append("head")
        return {
            "ContentLength": self._size_bytes,
            "ContentType": "application/octet-stream",
            "ChecksumSHA256": self._composite_checksum,
            "ChecksumType": "COMPOSITE",
        }


class _EventuallyDeletedClient:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._head_calls = 0

    def delete_object(self, **_request: object) -> dict[str, object]:
        self._events.append("delete")
        return {}

    def head_object(self, **_request: object) -> dict[str, object]:
        self._events.append("head")
        self._head_calls += 1
        if self._head_calls == 1:
            return {
                "ContentLength": 7,
                "ContentType": "text/plain",
            }
        raise ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
            "HeadObject",
        )


class _AbortClient:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def abort_multipart_upload(self, **_request: object) -> dict[str, object]:
        self._events.append("abort")
        return {}


class _DownloadClient:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.requests: list[dict[str, object]] = []

    def get_object(self, **request: object) -> dict[str, object]:
        self.requests.append(request)
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


class _BindingClient:
    def __init__(self, *, contains_durable_bytes: bool = False) -> None:
        self._payload: bytes | None = None
        self._lock = Lock()
        self._contains_durable_bytes = contains_durable_bytes
        self.put_calls = 0

    def put_object(self, **request: object) -> dict[str, str]:
        assert request["IfNoneMatch"] == "*"
        payload = cast(bytes, request["Body"])
        with self._lock:
            self.put_calls += 1
            if self._payload is not None:
                raise ClientError(
                    {
                        "Error": {
                            "Code": "PreconditionFailed",
                            "Message": "already exists",
                        }
                    },
                    "PutObject",
                )
            self._payload = payload
        return {"ChecksumSHA256": cast(str, request["ChecksumSHA256"])}

    def get_object(self, **_request: object) -> dict[str, object]:
        with self._lock:
            payload = self._payload
        if payload is None:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "GetObject",
            )
        return {
            "Body": StreamingBody(BytesIO(payload), len(payload)),
            "ContentLength": len(payload),
            "ContentType": "application/vnd.eneo.object-content-binding",
        }

    def list_objects_v2(self, **_request: object) -> dict[str, object]:
        return {
            "Contents": (
                [{"Key": new_object_key(_settings()), "Size": 1}]
                if self._contains_durable_bytes
                else []
            )
        }


class _RecordingCheckpoint:
    def __init__(self, record: Callable[[], None]) -> None:
        self._record = record

    async def __call__(self) -> None:
        self._record()

    async def run(
        self,
        operation: Callable[[], Awaitable[_ResultT]],
    ) -> _ResultT:
        await self()
        result = await operation()
        await self()
        return result


@pytest.mark.asyncio
async def test_single_upload_checkpoints_before_each_sdk_request() -> None:
    payload = b"content"
    digest = sha256(payload).digest()
    checksum = base64.b64encode(digest).decode()
    events: list[str] = []
    client = _SingleUploadClient(checksum, events)
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))
    captured = CapturedContent(
        file=BytesIO(payload),
        sha256=digest,
        size_bytes=len(payload),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        part_sha256=(digest,),
    )

    checkpoint = _RecordingCheckpoint(lambda: events.append("checkpoint"))

    head = await store.upload(
        new_object_key(_settings()),
        captured,
        operation_checkpoint=checkpoint,
    )

    assert head.size_bytes == len(payload)
    assert client.head_calls == 1
    assert events == [
        "checkpoint",
        "put",
        "checkpoint",
        "checkpoint",
        "head",
    ]


@pytest.mark.asyncio
async def test_remote_inventory_cannot_escape_the_deployment_prefix() -> None:
    client = cast("S3Client", _EscapedInventoryClient())
    store = S3ObjectStore(_settings(), client=client)

    with pytest.raises(ObjectStoreIntegrityError, match="deployment prefix"):
        await store.list_object_page()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("continuation_token", "page"),
    [
        (None, {"IsTruncated": True, "Contents": []}),
        (
            "same-token",
            {
                "IsTruncated": True,
                "NextContinuationToken": "same-token",
                "Contents": [],
            },
        ),
    ],
    ids=("missing-token", "non-advancing-token"),
)
async def test_object_inventory_rejects_incomplete_pagination(
    continuation_token: str | None,
    page: dict[str, object],
) -> None:
    client = _InvalidPaginationClient(object_page=page)
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))

    with pytest.raises(ObjectStoreIntegrityError, match="pagination"):
        await store.list_object_page(continuation_token=continuation_token)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key_marker", "upload_id_marker", "page"),
    [
        (
            None,
            None,
            {
                "IsTruncated": True,
                "NextKeyMarker": "next-key",
                "Uploads": [],
            },
        ),
        (
            "same-key",
            "same-upload",
            {
                "IsTruncated": True,
                "NextKeyMarker": "same-key",
                "NextUploadIdMarker": "same-upload",
                "Uploads": [],
            },
        ),
    ],
    ids=("incomplete-marker-pair", "non-advancing-marker-pair"),
)
async def test_multipart_inventory_rejects_incomplete_pagination(
    key_marker: str | None,
    upload_id_marker: str | None,
    page: dict[str, object],
) -> None:
    client = _InvalidPaginationClient(multipart_page=page)
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))

    with pytest.raises(ObjectStoreIntegrityError, match="pagination"):
        await store.list_multipart_page(
            key_marker=key_marker,
            upload_id_marker=upload_id_marker,
        )


@pytest.mark.asyncio
async def test_multipart_upload_emits_bounded_lease_checkpoints() -> None:
    mebibyte = 1024 * 1024
    part_bytes = 5 * mebibyte
    payload = b"a" * part_bytes + b"b"
    part_digests = (
        sha256(payload[:part_bytes]).digest(),
        sha256(payload[part_bytes:]).digest(),
    )
    events: list[str] = []
    client = _MultipartUploadClient(
        size_bytes=len(payload),
        composite_checksum=composite_sha256(part_digests),
        events=events,
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

    checkpoint = _RecordingCheckpoint(lambda: events.append("checkpoint"))

    await store.upload(
        new_object_key(settings),
        captured,
        operation_checkpoint=checkpoint,
    )

    assert events == [
        "checkpoint",
        "create",
        "checkpoint",
        "checkpoint",
        "part:1",
        "checkpoint",
        "checkpoint",
        "part:2",
        "checkpoint",
        "checkpoint",
        "complete",
        "checkpoint",
        "checkpoint",
        "head",
    ]


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

    async def record_checkpoint() -> None:
        nonlocal checkpoints
        checkpoints += 1

    class _CountingCheckpoint(_RecordingCheckpoint):
        async def __call__(self) -> None:
            await record_checkpoint()

    checkpoint = _CountingCheckpoint(lambda: None)

    digest = await store.recompute_sha256(
        new_object_key(settings),
        expected_size_bytes=len(payload),
        expected_media_type="application/octet-stream",
        operation_checkpoint=checkpoint,
    )

    assert digest == sha256(payload).digest()
    # Before GET, before each of three reads, and before the terminal read.
    assert checkpoints == 5


@pytest.mark.asyncio
async def test_delete_checkpoints_before_delete_and_each_visibility_head() -> None:
    events: list[str] = []
    client = _EventuallyDeletedClient(events)
    settings = _settings().model_copy(
        update={
            "delete_poll_interval_seconds": 0.001,
            "delete_visibility_timeout_seconds": 1,
        }
    )
    store = S3ObjectStore(settings, client=cast("S3Client", client))

    checkpoint = _RecordingCheckpoint(lambda: events.append("checkpoint"))

    await store.delete_and_confirm(
        new_object_key(settings),
        operation_checkpoint=checkpoint,
    )

    assert events == [
        "checkpoint",
        "delete",
        "checkpoint",
        "checkpoint",
        "head",
        "checkpoint",
        "head",
    ]


@pytest.mark.asyncio
async def test_multipart_abort_checkpoints_before_the_sdk_request() -> None:
    events: list[str] = []
    settings = _settings()
    store = S3ObjectStore(
        settings,
        client=cast("S3Client", _AbortClient(events)),
    )

    checkpoint = _RecordingCheckpoint(lambda: events.append("checkpoint"))

    await store.abort_multipart(
        new_object_key(settings),
        "upload-id",
        operation_checkpoint=checkpoint,
    )

    assert events == ["checkpoint", "abort", "checkpoint"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "byte_range",
    [
        None,
        ByteRange(start=2, end=5, total=10),
    ],
    ids=("full", "range"),
)
async def test_verified_read_rejects_replacement_before_yielding_full_or_range(
    byte_range: ByteRange | None,
) -> None:
    original = b"abcdefghij"
    replacement = b"0123456789"
    client = _DownloadClient(replacement)
    store = S3ObjectStore(
        _settings(),
        client=cast("S3Client", client),
    )
    emitted = bytearray()

    with pytest.raises(ObjectStoreIntegrityError, match="canonical SHA-256"):
        async with store.open_verified_read(
            new_object_key(_settings()),
            expected_sha256=sha256(original).digest(),
            expected_size_bytes=len(original),
            expected_media_type="application/octet-stream",
            byte_range=byte_range,
        ) as opened:
            async for chunk in opened.chunks:
                emitted.extend(chunk)

    assert emitted == b""
    assert all("Range" not in request for request in client.requests)


@pytest.mark.asyncio
async def test_binding_create_is_atomic_and_idempotent_across_replicas() -> None:
    client = _BindingClient()
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))
    binding_id = uuid4()

    await asyncio.gather(
        store.ensure_binding(binding_id, allow_create=True),
        store.ensure_binding(binding_id, allow_create=True),
    )
    await store.ensure_binding(binding_id, allow_create=False)

    assert client.put_calls == 2


@pytest.mark.asyncio
async def test_binding_never_overwrites_a_foreign_database_identity() -> None:
    client = _BindingClient()
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))
    first_binding = uuid4()

    await store.ensure_binding(first_binding, allow_create=True)

    with pytest.raises(ObjectStoreBindingError, match="another database"):
        await store.ensure_binding(uuid4(), allow_create=True)


@pytest.mark.asyncio
async def test_confirmed_binding_is_not_recreated_when_marker_is_missing() -> None:
    client = _BindingClient()
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))

    with pytest.raises(ObjectStoreBindingError, match="missing"):
        await store.ensure_binding(uuid4(), allow_create=False)

    assert client.put_calls == 0


@pytest.mark.asyncio
async def test_unpaired_nonempty_namespace_is_never_adopted() -> None:
    client = _BindingClient(contains_durable_bytes=True)
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))

    with pytest.raises(ObjectStoreBindingError, match="already contains"):
        await store.ensure_binding(uuid4(), allow_create=True)

    assert client.put_calls == 0


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
