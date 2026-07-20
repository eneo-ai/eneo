from __future__ import annotations

import asyncio
import base64
import io
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from secrets import token_hex
from tempfile import SpooledTemporaryFile
from time import monotonic
from typing import TYPE_CHECKING, BinaryIO, Final, Mapping, cast
from uuid import UUID

from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ChecksumError,
    ClientError,
    FlexibleChecksumError,
)
from botocore.response import StreamingBody
from botocore.session import get_session

from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import ByteRange, CapturedContent

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.type_defs import (
        CompletedPartTypeDef,
        ListMultipartUploadsRequestTypeDef,
        ListObjectsV2RequestTypeDef,
    )

_SHA256_BYTES: Final = 32
_BINDING_MEDIA_TYPE: Final = "application/vnd.eneo.object-content-binding"
_BINDING_PREAMBLE: Final = b"eneo-object-content-binding-v1\n"


class ObjectStoreError(RuntimeError):
    """Base exception for the private object-content boundary."""


class ObjectStoreUnavailableError(ObjectStoreError):
    pass


class ObjectStoreNotFoundError(ObjectStoreError):
    pass


class ObjectStoreIntegrityError(ObjectStoreError):
    pass


class ObjectStoreBindingError(ObjectStoreError):
    pass


@dataclass(frozen=True, slots=True)
class ObjectHead:
    size_bytes: int
    media_type: str
    checksum_sha256: str | None
    checksum_type: str | None


@dataclass(frozen=True, slots=True)
class ObjectRead:
    chunks: AsyncIterator[bytes]
    content_length: int
    media_type: str
    content_range: str | None


@dataclass(frozen=True, slots=True)
class RemoteObject:
    key: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class RemoteObjectPage:
    objects: tuple[RemoteObject, ...]
    next_token: str | None


@dataclass(frozen=True, slots=True)
class MultipartUpload:
    key: str
    upload_id: str
    initiated_at: datetime | None


@dataclass(frozen=True, slots=True)
class MultipartUploadPage:
    uploads: tuple[MultipartUpload, ...]
    next_key_marker: str | None
    next_upload_id_marker: str | None


MultipartStarted = Callable[[str], Awaitable[None]]
UploadCheckpoint = Callable[[], Awaitable[None]]
ReadCheckpoint = Callable[[], Awaitable[None]]


class _FileSlice(io.RawIOBase):
    """Expose one seekable file interval without copying it into memory."""

    def __init__(
        self,
        source: BinaryIO,
        *,
        start: int,
        length: int,
        maximum_read_bytes: int,
    ) -> None:
        super().__init__()
        if maximum_read_bytes < 1:
            raise ValueError("maximum_read_bytes must be positive")
        self._source = source
        self._start = start
        self._length = length
        self._maximum_read_bytes = maximum_read_bytes
        self._position = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            position = offset
        elif whence == io.SEEK_CUR:
            position = self._position + offset
        elif whence == io.SEEK_END:
            position = self._length + offset
        else:
            raise ValueError("Unsupported seek mode")
        if not 0 <= position <= self._length:
            raise ValueError("Seek is outside the multipart interval")
        self._position = position
        return position

    def read(self, size: int = -1) -> bytes:
        if self.closed:
            raise ValueError("I/O operation on closed multipart interval")
        remaining = self._length - self._position
        if remaining == 0:
            return b""
        requested = remaining if size < 0 else min(size, remaining)
        read_size = min(requested, self._maximum_read_bytes)
        self._source.seek(self._start + self._position)
        chunk = self._source.read(read_size)
        self._position += len(chunk)
        return chunk


def new_object_key(settings: ObjectContentSettings) -> str:
    """Create an opaque key with only a deployment namespace and random token."""
    return f"{settings.object_key_prefix}{token_hex(16)}"


def composite_sha256(part_sha256: Sequence[bytes]) -> str:
    """Return the S3 SHA-256 composite checksum; never a content digest."""
    if not part_sha256 or any(len(digest) != _SHA256_BYTES for digest in part_sha256):
        raise ValueError("part SHA-256 values must be non-empty 32-byte digests")
    digest = sha256(b"".join(part_sha256)).digest()
    return f"{base64.b64encode(digest).decode()}-{len(part_sha256)}"


def _base64_sha256(digest: bytes) -> str:
    if len(digest) != _SHA256_BYTES:
        raise ValueError("canonical SHA-256 must be a 32-byte digest")
    return base64.b64encode(digest).decode()


def _client_error_code(error: ClientError) -> str:
    response = cast(Mapping[str, object], error.response)
    detail = response.get("Error")
    if not isinstance(detail, Mapping):
        return "unknown"
    typed_detail = cast(Mapping[str, object], detail)
    code = typed_detail.get("Code")
    return str(code) if code is not None else "unknown"


def _create_client(
    settings: ObjectContentSettings,
    *,
    connect_timeout_seconds: float,
    read_timeout_seconds: float,
    max_attempts: int,
) -> S3Client:
    return cast(
        "S3Client",
        get_session().create_client(
            "s3",
            endpoint_url=settings.endpoint_url,
            region_name=settings.region,
            aws_access_key_id=settings.access_key_id.get_secret_value(),
            aws_secret_access_key=settings.secret_access_key.get_secret_value(),
            verify=str(settings.ca_bundle) if settings.ca_bundle is not None else True,
            config=Config(
                signature_version="s3v4",
                connect_timeout=connect_timeout_seconds,
                read_timeout=read_timeout_seconds,
                retries={
                    "mode": "standard",
                    "total_max_attempts": max_attempts,
                },
                s3={"addressing_style": settings.addressing_style},
            ),
        ),
    )


class S3ObjectStore:
    """The sole vendor-neutral S3-compatible byte adapter."""

    def __init__(
        self,
        settings: ObjectContentSettings,
        client: S3Client | None = None,
    ) -> None:
        self._settings = settings
        if client is not None:
            self._client = client
            self._readiness_client = client
        else:
            self._client = _create_client(
                settings,
                connect_timeout_seconds=settings.connect_timeout_seconds,
                read_timeout_seconds=settings.read_timeout_seconds,
                max_attempts=settings.sdk_max_attempts,
            )
            self._readiness_client = _create_client(
                settings,
                connect_timeout_seconds=settings.readiness_timeout_seconds,
                read_timeout_seconds=settings.readiness_timeout_seconds,
                max_attempts=settings.readiness_max_attempts,
            )

    async def close(self) -> None:
        await asyncio.to_thread(self._client.close)
        if self._readiness_client is not self._client:
            await asyncio.to_thread(self._readiness_client.close)

    async def check_ready(self) -> None:
        try:
            await asyncio.to_thread(
                self._readiness_client.list_objects_v2,
                Bucket=self._settings.bucket,
                Prefix=self._settings.object_key_prefix,
                MaxKeys=1,
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStoreUnavailableError(
                "Object content storage is not ready"
            ) from error

    async def ensure_binding(
        self,
        binding_id: UUID,
        *,
        allow_create: bool,
    ) -> None:
        """Verify this database's immutable marker or create it once."""
        expected = _BINDING_PREAMBLE + binding_id.bytes
        observed = await self._read_binding()
        if observed is not None:
            if observed != expected:
                raise ObjectStoreBindingError(
                    "Object content storage is paired with another database"
                )
            return
        if not allow_create:
            raise ObjectStoreBindingError(
                "The confirmed object-content storage binding is missing"
            )

        await self._require_empty_content_namespace()
        checksum = base64.b64encode(sha256(expected).digest()).decode()
        try:
            await asyncio.to_thread(
                self._readiness_client.put_object,
                Bucket=self._settings.bucket,
                Key=self._binding_key,
                Body=expected,
                ContentLength=len(expected),
                ContentType=_BINDING_MEDIA_TYPE,
                ChecksumSHA256=checksum,
                IfNoneMatch="*",
            )
        except ClientError as error:
            if _client_error_code(error) not in {"412", "PreconditionFailed"}:
                raise ObjectStoreUnavailableError(
                    "Object content storage binding failed"
                ) from error
        except BotoCoreError as error:
            raise ObjectStoreUnavailableError(
                "Object content storage binding failed"
            ) from error

        observed = await self._read_binding()
        if observed != expected:
            raise ObjectStoreBindingError(
                "Object content storage is paired with another database"
            )

    async def upload(
        self,
        key: str,
        content: CapturedContent,
        *,
        multipart_started: MultipartStarted | None = None,
        upload_checkpoint: UploadCheckpoint | None = None,
    ) -> ObjectHead:
        self._require_owned_key(key)
        if content.size_bytes >= self._settings.multipart_threshold_bytes:
            head = await self._upload_multipart(
                key,
                content,
                multipart_started=multipart_started,
                upload_checkpoint=upload_checkpoint,
            )
        else:
            head = await self._upload_single(key, content)
        if head.size_bytes != content.size_bytes:
            raise ObjectStoreIntegrityError(
                "Stored object length does not match intent"
            )
        if head.media_type != content.verified_media_type:
            raise ObjectStoreIntegrityError(
                "Stored object media type does not match intent"
            )
        return head

    async def _upload_single(
        self,
        key: str,
        content: CapturedContent,
    ) -> ObjectHead:
        expected_checksum = _base64_sha256(content.sha256)
        content.file.seek(0)
        try:
            result = await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._settings.bucket,
                Key=key,
                Body=content.file,
                ContentLength=content.size_bytes,
                ContentType=content.verified_media_type,
                ChecksumSHA256=expected_checksum,
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStoreUnavailableError("Object upload failed") from error

        if result.get("ChecksumSHA256") != expected_checksum:
            raise ObjectStoreIntegrityError(
                "Object store did not confirm the full-object SHA-256"
            )

        head = await self.head(key)
        if head.checksum_sha256 != expected_checksum:
            raise ObjectStoreIntegrityError(
                "Object store HEAD checksum does not match the upload"
            )
        if head.checksum_type not in {None, "FULL_OBJECT"}:
            raise ObjectStoreIntegrityError(
                "Unexpected checksum type for single upload"
            )
        return head

    async def _upload_multipart(
        self,
        key: str,
        content: CapturedContent,
        *,
        multipart_started: MultipartStarted | None,
        upload_checkpoint: UploadCheckpoint | None,
    ) -> ObjectHead:
        if content.size_bytes > self._settings.maximum_multipart_bytes:
            raise ObjectStoreIntegrityError(
                "Content exceeds the configured S3 multipart protocol envelope"
            )

        try:
            created = await asyncio.to_thread(
                self._client.create_multipart_upload,
                Bucket=self._settings.bucket,
                Key=key,
                ContentType=content.verified_media_type,
                ChecksumAlgorithm="SHA256",
                ChecksumType="COMPOSITE",
            )
            upload_id = created.get("UploadId")
            if not upload_id:
                raise ObjectStoreIntegrityError(
                    "Object store did not return a multipart upload identifier"
                )
            if multipart_started is not None:
                await multipart_started(upload_id)

            completed_parts = await self._upload_parts(
                key,
                upload_id,
                content,
                upload_checkpoint=upload_checkpoint,
            )
            expected_composite = composite_sha256(content.part_sha256)
            if upload_checkpoint is not None:
                await upload_checkpoint()
            completed = await asyncio.to_thread(
                self._client.complete_multipart_upload,
                Bucket=self._settings.bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": completed_parts},
                ChecksumType="COMPOSITE",
            )
        except ObjectStoreError:
            raise
        except (BotoCoreError, ClientError) as error:
            raise ObjectStoreUnavailableError(
                "Multipart object upload failed"
            ) from error

        if (
            "ChecksumSHA256" in completed
            and completed["ChecksumSHA256"] != expected_composite
        ):
            raise ObjectStoreIntegrityError(
                "Object store returned the wrong multipart composite SHA-256"
            )
        if completed.get("ChecksumType") not in {None, "COMPOSITE"}:
            raise ObjectStoreIntegrityError("Unexpected multipart checksum type")

        if upload_checkpoint is not None:
            await upload_checkpoint()
        head = await self.head(key)
        if head.checksum_sha256 != expected_composite:
            raise ObjectStoreIntegrityError(
                "Object store HEAD composite checksum does not match the parts"
            )
        if head.checksum_type not in {None, "COMPOSITE"}:
            raise ObjectStoreIntegrityError("Unexpected multipart HEAD checksum type")
        return head

    async def _upload_parts(
        self,
        key: str,
        upload_id: str,
        content: CapturedContent,
        *,
        upload_checkpoint: UploadCheckpoint | None,
    ) -> list[CompletedPartTypeDef]:
        completed_parts: list[CompletedPartTypeDef] = []
        transferred = 0
        expected_part_count = (
            content.size_bytes + self._settings.multipart_part_bytes - 1
        ) // self._settings.multipart_part_bytes
        if len(content.part_sha256) != expected_part_count:
            raise ObjectStoreIntegrityError(
                "Multipart part inventory has the wrong part count"
            )

        for index, part_digest in enumerate(content.part_sha256, start=1):
            part_length = min(
                self._settings.multipart_part_bytes,
                content.size_bytes - transferred,
            )
            if part_length <= 0:
                raise ObjectStoreIntegrityError("Multipart intent has an extra part")
            expected_checksum = _base64_sha256(part_digest)
            part = _FileSlice(
                content.file,
                start=transferred,
                length=part_length,
                maximum_read_bytes=self._settings.io_chunk_bytes,
            )

            if upload_checkpoint is not None:
                await upload_checkpoint()
            result = await asyncio.to_thread(
                self._client.upload_part,
                Bucket=self._settings.bucket,
                Key=key,
                UploadId=upload_id,
                PartNumber=index,
                Body=part,
                ContentLength=part_length,
                ChecksumSHA256=expected_checksum,
            )
            if result.get("ChecksumSHA256") != expected_checksum:
                raise ObjectStoreIntegrityError(
                    "Object store did not confirm a part SHA-256"
                )
            etag = result.get("ETag")
            if not etag:
                raise ObjectStoreIntegrityError(
                    "Object store did not return a part ETag"
                )
            completed_parts.append(
                {
                    "ETag": etag,
                    "ChecksumSHA256": expected_checksum,
                    "PartNumber": index,
                }
            )
            transferred += part_length

        if transferred != content.size_bytes:
            raise ObjectStoreIntegrityError(
                "Multipart part inventory has the wrong length"
            )
        return completed_parts

    async def head(self, key: str) -> ObjectHead:
        self._require_owned_key(key)
        try:
            result = await asyncio.to_thread(
                self._client.head_object,
                Bucket=self._settings.bucket,
                Key=key,
                ChecksumMode="ENABLED",
            )
        except ClientError as error:
            if _client_error_code(error) in {"404", "NoSuchKey", "NotFound"}:
                raise ObjectStoreNotFoundError(
                    "Object content does not exist"
                ) from error
            raise ObjectStoreUnavailableError("Object HEAD failed") from error
        except BotoCoreError as error:
            raise ObjectStoreUnavailableError("Object HEAD failed") from error

        return ObjectHead(
            size_bytes=result.get("ContentLength", -1),
            media_type=result.get("ContentType", ""),
            checksum_sha256=result.get("ChecksumSHA256"),
            checksum_type=result.get("ChecksumType"),
        )

    @asynccontextmanager
    async def open_read(
        self,
        key: str,
        *,
        expected_size_bytes: int,
        expected_media_type: str,
    ) -> AsyncGenerator[ObjectRead, None]:
        self._require_owned_key(key)
        try:
            result = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self._settings.bucket,
                Key=key,
                ChecksumMode="ENABLED",
            )
        except ClientError as error:
            if _client_error_code(error) in {"404", "NoSuchKey", "NotFound"}:
                raise ObjectStoreNotFoundError(
                    "Object content does not exist"
                ) from error
            raise ObjectStoreUnavailableError("Object read failed") from error
        except BotoCoreError as error:
            raise ObjectStoreUnavailableError("Object read failed") from error

        if result.get("ContentLength") != expected_size_bytes:
            result["Body"].close()
            raise ObjectStoreIntegrityError("Object read length does not match intent")
        if result.get("ContentType") != expected_media_type:
            result["Body"].close()
            raise ObjectStoreIntegrityError(
                "Object read media type does not match intent"
            )

        body = result["Body"]
        chunks = self._stream_body(body, expected_length=expected_size_bytes)
        try:
            yield ObjectRead(
                chunks=chunks,
                content_length=expected_size_bytes,
                media_type=expected_media_type,
                content_range=None,
            )
        finally:
            await chunks.aclose()

    @asynccontextmanager
    async def open_verified_read(
        self,
        key: str,
        *,
        expected_sha256: bytes,
        expected_size_bytes: int,
        expected_media_type: str,
        byte_range: ByteRange | None = None,
    ) -> AsyncGenerator[ObjectRead, None]:
        """Verify canonical bytes before exposing a full or ranged response."""
        if len(expected_sha256) != _SHA256_BYTES:
            raise ObjectStoreIntegrityError("Canonical SHA-256 has an invalid length")
        if byte_range is not None and byte_range.total != expected_size_bytes:
            raise ObjectStoreIntegrityError(
                "Requested byte range does not match the canonical object size"
            )

        spool = SpooledTemporaryFile(
            max_size=self._settings.spool_memory_bytes,
            mode="w+b",
        )
        digest = sha256()
        try:
            async with self.open_read(
                key,
                expected_size_bytes=expected_size_bytes,
                expected_media_type=expected_media_type,
            ) as remote:
                async for chunk in remote.chunks:
                    digest.update(chunk)
                    written = await asyncio.to_thread(spool.write, chunk)
                    if written != len(chunk):
                        raise ObjectStoreIntegrityError(
                            "Verified object spool accepted a partial write"
                        )

            if digest.digest() != expected_sha256:
                raise ObjectStoreIntegrityError(
                    "Object bytes do not match the canonical SHA-256"
                )

            start = 0 if byte_range is None else byte_range.start
            content_length = (
                expected_size_bytes if byte_range is None else byte_range.content_length
            )
            await asyncio.to_thread(spool.seek, start)
            chunks = self._stream_file(spool, expected_length=content_length)
            try:
                yield ObjectRead(
                    chunks=chunks,
                    content_length=content_length,
                    media_type=expected_media_type,
                    content_range=(
                        None if byte_range is None else byte_range.response_header
                    ),
                )
            finally:
                await chunks.aclose()
        finally:
            await asyncio.to_thread(spool.close)

    async def recompute_sha256(
        self,
        key: str,
        *,
        expected_size_bytes: int,
        expected_media_type: str,
        read_checkpoint: ReadCheckpoint | None = None,
    ) -> bytes:
        digest = sha256()
        if read_checkpoint is not None:
            await read_checkpoint()
        async with self.open_read(
            key,
            expected_size_bytes=expected_size_bytes,
            expected_media_type=expected_media_type,
        ) as content:
            chunks = aiter(content.chunks)
            while True:
                if read_checkpoint is not None:
                    await read_checkpoint()
                try:
                    chunk = await anext(chunks)
                except StopAsyncIteration:
                    break
                digest.update(chunk)
        return digest.digest()

    async def _stream_body(
        self,
        body: StreamingBody,
        *,
        expected_length: int,
    ) -> AsyncGenerator[bytes, None]:
        transferred = 0
        try:
            while True:
                chunk = await asyncio.to_thread(
                    body.read, self._settings.io_chunk_bytes
                )
                if not chunk:
                    break
                transferred += len(chunk)
                if transferred > expected_length:
                    raise ObjectStoreIntegrityError("Object stream exceeded its length")
                yield chunk
            if transferred != expected_length:
                raise ObjectStoreIntegrityError("Object stream ended before its length")
        except (ChecksumError, FlexibleChecksumError) as error:
            raise ObjectStoreIntegrityError("Object stream checksum failed") from error
        except BotoCoreError as error:
            raise ObjectStoreUnavailableError("Object stream interrupted") from error
        finally:
            await asyncio.to_thread(body.close)

    async def _stream_file(
        self,
        source: SpooledTemporaryFile[bytes],
        *,
        expected_length: int,
    ) -> AsyncGenerator[bytes, None]:
        transferred = 0
        while transferred < expected_length:
            chunk = await asyncio.to_thread(
                source.read,
                min(self._settings.io_chunk_bytes, expected_length - transferred),
            )
            if not chunk:
                raise ObjectStoreIntegrityError(
                    "Verified object spool ended before its length"
                )
            transferred += len(chunk)
            yield chunk

    @property
    def _binding_key(self) -> str:
        return f"v1/.eneo-bindings/{self._settings.deployment_id.hex}"

    async def _read_binding(self) -> bytes | None:
        try:
            result = await asyncio.to_thread(
                self._readiness_client.get_object,
                Bucket=self._settings.bucket,
                Key=self._binding_key,
            )
        except ClientError as error:
            if _client_error_code(error) in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise ObjectStoreUnavailableError(
                "Object content storage binding read failed"
            ) from error
        except BotoCoreError as error:
            raise ObjectStoreUnavailableError(
                "Object content storage binding read failed"
            ) from error

        body = result["Body"]
        expected_length = len(_BINDING_PREAMBLE) + 16
        try:
            if (
                result.get("ContentLength") != expected_length
                or result.get("ContentType") != _BINDING_MEDIA_TYPE
            ):
                raise ObjectStoreBindingError(
                    "Object content storage has an invalid binding marker"
                )
            observed = await asyncio.to_thread(body.read, expected_length + 1)
            if len(observed) != expected_length:
                raise ObjectStoreBindingError(
                    "Object content storage has an invalid binding marker"
                )
            return observed
        except BotoCoreError as error:
            raise ObjectStoreUnavailableError(
                "Object content storage binding read failed"
            ) from error
        finally:
            await asyncio.to_thread(body.close)

    async def _require_empty_content_namespace(self) -> None:
        try:
            result = await asyncio.to_thread(
                self._readiness_client.list_objects_v2,
                Bucket=self._settings.bucket,
                Prefix=self._settings.object_key_prefix,
                MaxKeys=1,
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStoreUnavailableError(
                "Object content storage inventory failed"
            ) from error
        if result.get("Contents"):
            raise ObjectStoreBindingError(
                "Unpaired object content storage already contains durable bytes"
            )

    async def delete_and_confirm(self, key: str) -> None:
        self._require_owned_key(key)
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=self._settings.bucket,
                Key=key,
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStoreUnavailableError("Object delete failed") from error

        deadline = monotonic() + self._settings.delete_visibility_timeout_seconds
        while True:
            try:
                await self.head(key)
            except ObjectStoreNotFoundError:
                return
            if monotonic() >= deadline:
                raise ObjectStoreUnavailableError(
                    "Object deletion was not visible before the configured deadline"
                )
            await asyncio.sleep(self._settings.delete_poll_interval_seconds)

    async def list_object_page(
        self,
        *,
        continuation_token: str | None = None,
    ) -> RemoteObjectPage:
        request: ListObjectsV2RequestTypeDef = {
            "Bucket": self._settings.bucket,
            "Prefix": self._settings.object_key_prefix,
            "MaxKeys": self._settings.reconciliation_batch_size,
        }
        if continuation_token is not None:
            request["ContinuationToken"] = continuation_token
        try:
            result = await asyncio.to_thread(self._client.list_objects_v2, **request)
        except (BotoCoreError, ClientError) as error:
            raise ObjectStoreUnavailableError("Object inventory failed") from error

        objects = tuple(
            RemoteObject(key=item.get("Key", ""), size_bytes=item.get("Size", -1))
            for item in result.get("Contents", ())
        )
        if any(not item.key or item.size_bytes < 0 for item in objects):
            raise ObjectStoreIntegrityError("Object inventory contained an invalid row")
        for item in objects:
            try:
                self._require_owned_key(item.key)
            except ValueError as error:
                raise ObjectStoreIntegrityError(
                    "Object inventory escaped the configured deployment prefix"
                ) from error
        return RemoteObjectPage(
            objects=objects,
            next_token=result.get("NextContinuationToken"),
        )

    async def list_multipart_page(
        self,
        *,
        key_marker: str | None = None,
        upload_id_marker: str | None = None,
    ) -> MultipartUploadPage:
        request: ListMultipartUploadsRequestTypeDef = {
            "Bucket": self._settings.bucket,
            "Prefix": self._settings.object_key_prefix,
            "MaxUploads": self._settings.reconciliation_batch_size,
        }
        if key_marker is not None:
            request["KeyMarker"] = key_marker
        if upload_id_marker is not None:
            request["UploadIdMarker"] = upload_id_marker
        try:
            result = await asyncio.to_thread(
                self._client.list_multipart_uploads, **request
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStoreUnavailableError("Multipart inventory failed") from error

        uploads_list: list[MultipartUpload] = []
        for item in result.get("Uploads", ()):
            raw_item = cast(Mapping[str, object], item)
            key_value = raw_item.get("Key")
            upload_id_value = raw_item.get("UploadId")
            initiated_value = raw_item.get("Initiated")
            if (
                not isinstance(key_value, str)
                or not key_value
                or not isinstance(upload_id_value, str)
                or not upload_id_value
            ):
                raise ObjectStoreIntegrityError(
                    "Multipart inventory contained an invalid row"
                )
            if initiated_value is not None and (
                not isinstance(initiated_value, datetime)
                or initiated_value.utcoffset() is None
            ):
                raise ObjectStoreIntegrityError(
                    "Multipart inventory contained an invalid initiation time"
                )
            try:
                self._require_owned_key(key_value)
            except ValueError as error:
                raise ObjectStoreIntegrityError(
                    "Multipart inventory escaped the configured deployment prefix"
                ) from error
            uploads_list.append(
                MultipartUpload(
                    key=key_value,
                    upload_id=upload_id_value,
                    initiated_at=(
                        initiated_value
                        if isinstance(initiated_value, datetime)
                        else None
                    ),
                )
            )
        uploads = tuple(uploads_list)
        return MultipartUploadPage(
            uploads=uploads,
            next_key_marker=result.get("NextKeyMarker"),
            next_upload_id_marker=result.get("NextUploadIdMarker"),
        )

    async def abort_multipart(self, key: str, upload_id: str) -> None:
        self._require_owned_key(key)
        try:
            await asyncio.to_thread(
                self._client.abort_multipart_upload,
                Bucket=self._settings.bucket,
                Key=key,
                UploadId=upload_id,
            )
        except ClientError as error:
            if _client_error_code(error) in {"404", "NoSuchUpload", "NotFound"}:
                return
            raise ObjectStoreUnavailableError("Multipart abort failed") from error
        except BotoCoreError as error:
            raise ObjectStoreUnavailableError("Multipart abort failed") from error

    def _require_owned_key(self, key: str) -> None:
        prefix = self._settings.object_key_prefix
        token = key.removeprefix(prefix)
        if not key.startswith(prefix) or len(token) != 32:
            raise ValueError("Object key is outside the configured deployment prefix")
        try:
            bytes.fromhex(token)
        except ValueError as error:
            raise ValueError("Object key token is not opaque hexadecimal") from error
