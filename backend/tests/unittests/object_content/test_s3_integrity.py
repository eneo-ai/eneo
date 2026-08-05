import asyncio
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
from eneo.object_content.content import (
    ByteRange,
    CapturedContent,
    verification_chunk_window,
)
from eneo.object_content.s3_object_store import (
    ObjectStoreBindingError,
    ObjectStoreIntegrityError,
    ObjectStoreUnavailableError,
    S3ObjectStore,
    _create_client,
    _FileSlice,
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


def test_s3_client_uses_only_explicitly_requested_checksums() -> None:
    client = _create_client(
        _settings(),
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        max_attempts=1,
    )
    try:
        config = client.meta.config
        assert config.request_checksum_calculation == "when_required"
        assert config.response_checksum_validation == "when_required"
    finally:
        client.close()


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
    def __init__(
        self,
        *,
        readback_payload: bytes | None = None,
        missing_on_readback: bool = False,
        events: list[str] | None = None,
    ) -> None:
        self._payload: bytes | None = None
        self._readback_payload = readback_payload
        self._missing_on_readback = missing_on_readback
        self.events = events
        self.head_calls = 0
        self.get_calls = 0

    def put_object(self, **request: object) -> dict[str, object]:
        if self.events is not None:
            self.events.append("put")
        assert not any(key.startswith("Checksum") for key in request)
        body = cast(BinaryIO, request["Body"])
        self._payload = body.read()
        return {}

    def head_object(self, **request: object) -> dict[str, object]:
        if self.events is not None:
            self.events.append("head")
        self.head_calls += 1
        assert "ChecksumMode" not in request
        assert self._payload is not None
        return {
            "ContentLength": len(self._payload),
            "ContentType": "text/plain",
        }

    def get_object(self, **request: object) -> dict[str, object]:
        if self.events is not None:
            self.events.append("get")
        assert self._payload is not None
        self.get_calls += 1
        assert "ChecksumMode" not in request
        if self._missing_on_readback:
            raise ClientError(
                {
                    "Error": {"Code": "NoSuchKey"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "GetObject",
            )
        payload = (
            self._readback_payload
            if self._readback_payload is not None
            else self._payload
        )
        return {
            "Body": StreamingBody(BytesIO(payload), len(payload)),
            "ContentLength": len(payload),
            "ContentType": "text/plain",
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
        payload: bytes,
        readback_payload: bytes | None = None,
        events: list[str] | None = None,
    ) -> None:
        self._payload = payload
        self._readback_payload = readback_payload
        self.events = events
        self.get_calls = 0

    def create_multipart_upload(self, **request: object) -> dict[str, str]:
        if self.events is not None:
            self.events.append("create")
        assert not any(key.startswith("Checksum") for key in request)
        return {"UploadId": "bounded-upload"}

    def upload_part(self, **request: object) -> dict[str, str]:
        if self.events is not None:
            self.events.append(f"part:{request['PartNumber']}")
        assert not any(key.startswith("Checksum") for key in request)
        body = cast(BinaryIO, request["Body"])
        while body.read(1024 * 1024):
            pass
        part_number = cast(int, request["PartNumber"])
        return {"ETag": f'"part-{part_number}"'}

    def complete_multipart_upload(self, **request: object) -> dict[str, str]:
        if self.events is not None:
            self.events.append("complete")
        assert not any(key.startswith("Checksum") for key in request)
        manifest = cast(dict[str, object], request["MultipartUpload"])
        parts = cast(list[dict[str, object]], manifest["Parts"])
        assert all(set(part) == {"ETag", "PartNumber"} for part in parts)
        return {}

    def head_object(self, **request: object) -> dict[str, object]:
        if self.events is not None:
            self.events.append("head")
        assert "ChecksumMode" not in request
        return {
            "ContentLength": len(self._payload),
            "ContentType": "application/octet-stream",
        }

    def get_object(self, **request: object) -> dict[str, object]:
        if self.events is not None:
            self.events.append("get")
        self.get_calls += 1
        assert "ChecksumMode" not in request
        payload = (
            self._readback_payload
            if self._readback_payload is not None
            else self._payload
        )
        return {
            "Body": StreamingBody(BytesIO(payload), len(payload)),
            "ContentLength": len(payload),
            "ContentType": "application/octet-stream",
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
        range_header = request.get("Range")
        if isinstance(range_header, str):
            match = re.fullmatch(r"bytes=(\d+)-(\d+)", range_header)
            assert match is not None
            start, end = (int(value) for value in match.groups())
            payload = self._payload[start : end + 1]
            return {
                "Body": StreamingBody(BytesIO(payload), len(payload)),
                "ContentLength": len(payload),
                "ContentRange": f"bytes {start}-{end}/{len(self._payload)}",
                "ContentType": "application/octet-stream",
            }
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
        self.put_keys: list[str] = []
        self.delete_keys: list[str] = []

    def put_object(self, **request: object) -> dict[str, str]:
        assert request["IfNoneMatch"] == "*"
        assert "ChecksumSHA256" not in request
        payload = cast(bytes, request["Body"])
        key = cast(str, request["Key"])
        with self._lock:
            self.put_calls += 1
            self.put_keys.append(key)
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
        return {}

    def delete_object(self, **request: object) -> dict[str, object]:
        key = cast(str, request["Key"])
        with self._lock:
            self.delete_keys.append(key)
            self._payload = None
        return {}

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
async def test_single_upload_verifies_stored_bytes() -> None:
    payload = b"portable s3 content"
    digest = sha256(payload).digest()
    client = _SingleUploadClient()
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))
    captured = CapturedContent(
        file=BytesIO(payload),
        sha256=digest,
        size_bytes=len(payload),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        part_sha256=(digest,),
        part_size_bytes=len(payload),
    )

    head = await store.upload(new_object_key(_settings()), captured)

    assert head.size_bytes == len(payload)
    assert client.get_calls == 1


@pytest.mark.asyncio
async def test_single_upload_rejects_corrupted_readback() -> None:
    payload = b"portable s3 content"
    replacement = b"corrupted s3 bytes!"
    assert len(replacement) == len(payload)
    digest = sha256(payload).digest()
    client = _SingleUploadClient(readback_payload=replacement)
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))
    captured = CapturedContent(
        file=BytesIO(payload),
        sha256=digest,
        size_bytes=len(payload),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        part_sha256=(digest,),
        part_size_bytes=len(payload),
    )

    with pytest.raises(ObjectStoreIntegrityError, match="Stored object bytes"):
        await store.upload(new_object_key(_settings()), captured)

    assert client.get_calls == 1


@pytest.mark.asyncio
async def test_single_upload_retries_when_object_disappears_before_readback() -> None:
    payload = b"portable s3 content"
    digest = sha256(payload).digest()
    client = _SingleUploadClient(missing_on_readback=True)
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))
    captured = CapturedContent(
        file=BytesIO(payload),
        sha256=digest,
        size_bytes=len(payload),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        part_sha256=(digest,),
        part_size_bytes=len(payload),
    )

    with pytest.raises(ObjectStoreUnavailableError, match="disappeared"):
        await store.upload(new_object_key(_settings()), captured)

    assert client.get_calls == 1


@pytest.mark.asyncio
async def test_single_upload_checkpoints_before_each_sdk_request() -> None:
    payload = b"content"
    digest = sha256(payload).digest()
    events: list[str] = []
    client = _SingleUploadClient(events=events)
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))
    captured = CapturedContent(
        file=BytesIO(payload),
        sha256=digest,
        size_bytes=len(payload),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        part_sha256=(digest,),
        part_size_bytes=len(payload),
    )

    checkpoint = _RecordingCheckpoint(lambda: events.append("checkpoint"))

    head = await store.upload(
        new_object_key(_settings()),
        captured,
        operation_checkpoint=checkpoint,
    )

    assert head.size_bytes == len(payload)
    assert client.head_calls == 1
    sdk_events = {"put", "head", "get"}
    assert [event for event in events if event in sdk_events] == [
        "put",
        "head",
        "get",
    ]
    assert all(
        index > 0 and events[index - 1] == "checkpoint"
        for index, event in enumerate(events)
        if event in sdk_events
    )


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
        payload=payload,
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
        part_size_bytes=part_bytes,
    )

    checkpoint = _RecordingCheckpoint(lambda: events.append("checkpoint"))

    await store.upload(
        new_object_key(settings),
        captured,
        operation_checkpoint=checkpoint,
    )

    sdk_events = {"create", "part:1", "part:2", "complete", "head", "get"}
    assert [event for event in events if event in sdk_events] == [
        "create",
        "part:1",
        "part:2",
        "complete",
        "head",
        "get",
    ]
    assert all(
        index > 0 and events[index - 1] == "checkpoint"
        for index, event in enumerate(events)
        if event in sdk_events
    )
    assert client.get_calls == 1


@pytest.mark.asyncio
async def test_multipart_upload_rejects_corrupted_readback() -> None:
    mebibyte = 1024 * 1024
    part_bytes = 5 * mebibyte
    payload = b"a" * part_bytes + b"b"
    replacement = b"x" * len(payload)
    part_digests = (
        sha256(payload[:part_bytes]).digest(),
        sha256(payload[part_bytes:]).digest(),
    )
    settings = _settings().model_copy(
        update={
            "multipart_part_bytes": part_bytes,
            "multipart_threshold_bytes": part_bytes,
        }
    )
    client = _MultipartUploadClient(
        payload=payload,
        readback_payload=replacement,
    )
    store = S3ObjectStore(settings, client=cast("S3Client", client))
    captured = CapturedContent(
        file=BytesIO(payload),
        sha256=sha256(payload).digest(),
        size_bytes=len(payload),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        part_sha256=part_digests,
        part_size_bytes=part_bytes,
    )

    with pytest.raises(ObjectStoreIntegrityError, match="Stored object bytes"):
        await store.upload(new_object_key(settings), captured)

    assert client.get_calls == 1


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
async def test_verified_full_read_rejects_replacement_before_yielding() -> None:
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
        ) as opened:
            async for chunk in opened.chunks:
                emitted.extend(chunk)

    assert emitted == b""
    assert all("Range" not in request for request in client.requests)


def test_verification_chunk_window_rejects_inconsistent_manifest() -> None:
    with pytest.raises(ValueError, match="chunk count"):
        verification_chunk_window(
            ByteRange(start=2, end=4, total=11),
            chunk_size_bytes=4,
            chunk_count=2,
        )


@pytest.mark.asyncio
async def test_verified_range_fetches_and_spools_only_covering_chunks() -> None:
    payload = b"abcdefghijklmnopq"
    chunk_size = 4
    digests = tuple(
        sha256(payload[offset : offset + chunk_size]).digest()
        for offset in range(0, len(payload), chunk_size)
    )
    requested = ByteRange(start=5, end=10, total=len(payload))
    client = _DownloadClient(payload)
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))

    async with store.open_verified_read(
        new_object_key(_settings()),
        expected_sha256=sha256(payload).digest(),
        expected_size_bytes=len(payload),
        expected_media_type="application/octet-stream",
        byte_range=requested,
        verification_chunk_size_bytes=chunk_size,
        verification_chunk_count=len(digests),
        verification_chunk_sha256=digests[1:3],
    ) as opened:
        body = b"".join([chunk async for chunk in opened.chunks])

    assert body == payload[5:11]
    assert opened.content_range == requested.response_header
    assert [request["Range"] for request in client.requests] == ["bytes=4-11"]


@pytest.mark.asyncio
async def test_verified_range_rejects_covering_corruption_before_yielding() -> None:
    original = b"abcdefghijklmnopq"
    replacement = original[:7] + b"X" + original[8:]
    chunk_size = 4
    digests = tuple(
        sha256(original[offset : offset + chunk_size]).digest()
        for offset in range(0, len(original), chunk_size)
    )
    requested = ByteRange(start=5, end=6, total=len(original))
    store = S3ObjectStore(
        _settings(),
        client=cast("S3Client", _DownloadClient(replacement)),
    )
    emitted = bytearray()

    with pytest.raises(ObjectStoreIntegrityError, match="verification chunk"):
        async with store.open_verified_read(
            new_object_key(_settings()),
            expected_sha256=sha256(original).digest(),
            expected_size_bytes=len(original),
            expected_media_type="application/octet-stream",
            byte_range=requested,
            verification_chunk_size_bytes=chunk_size,
            verification_chunk_count=len(digests),
            verification_chunk_sha256=digests[1:2],
        ) as opened:
            async for chunk in opened.chunks:
                emitted.extend(chunk)

    assert emitted == b""


@pytest.mark.asyncio
async def test_verified_range_does_not_read_corruption_outside_covering_chunks() -> (
    None
):
    original = b"abcdefghijklmnopq"
    replacement = b"X" + original[1:]
    chunk_size = 4
    digests = tuple(
        sha256(original[offset : offset + chunk_size]).digest()
        for offset in range(0, len(original), chunk_size)
    )
    requested = ByteRange(start=9, end=10, total=len(original))
    store = S3ObjectStore(
        _settings(),
        client=cast("S3Client", _DownloadClient(replacement)),
    )

    async with store.open_verified_read(
        new_object_key(_settings()),
        expected_sha256=sha256(original).digest(),
        expected_size_bytes=len(original),
        expected_media_type="application/octet-stream",
        byte_range=requested,
        verification_chunk_size_bytes=chunk_size,
        verification_chunk_count=len(digests),
        verification_chunk_sha256=digests[2:3],
    ) as opened:
        body = b"".join([chunk async for chunk in opened.chunks])

    assert body == original[9:11]


@pytest.mark.asyncio
async def test_binding_create_is_atomic_and_idempotent_across_replicas() -> None:
    client = _BindingClient()
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))
    binding_id = uuid4()

    first = await store.prepare_binding_creation(binding_id)
    second = await store.prepare_binding_creation(binding_id)
    assert first is not None
    assert second is not None

    await asyncio.gather(store.create_binding(first), store.create_binding(second))
    assert await store.verify_binding(binding_id)

    assert client.put_calls == 2


@pytest.mark.asyncio
async def test_binding_probe_uses_and_removes_candidate_deployment_key() -> None:
    client = _BindingClient()
    settings = _settings()
    store = S3ObjectStore(settings, client=cast("S3Client", client))

    await store.probe_binding_creation()

    binding_key = f"v1/.eneo-bindings/{settings.deployment_id.hex}"
    assert client.put_keys == [binding_key]
    assert client.delete_keys == [binding_key]


@pytest.mark.asyncio
async def test_binding_never_overwrites_a_foreign_database_identity() -> None:
    client = _BindingClient()
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))
    first_binding = uuid4()

    creation = await store.prepare_binding_creation(first_binding)
    assert creation is not None
    await store.create_binding(creation)

    with pytest.raises(ObjectStoreBindingError, match="another database"):
        await store.prepare_binding_creation(uuid4())


@pytest.mark.asyncio
async def test_missing_binding_is_reported_without_creating_a_marker() -> None:
    client = _BindingClient()
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))

    assert not await store.verify_binding(uuid4())

    assert client.put_calls == 0


@pytest.mark.asyncio
async def test_unpaired_nonempty_namespace_is_never_adopted() -> None:
    client = _BindingClient(contains_durable_bytes=True)
    store = S3ObjectStore(_settings(), client=cast("S3Client", client))

    with pytest.raises(ObjectStoreBindingError, match="already contains"):
        await store.prepare_binding_creation(uuid4())

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
