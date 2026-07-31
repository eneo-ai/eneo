import asyncio
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, cast
from uuid import UUID


class ContentState(StrEnum):
    PENDING = "pending"
    AVAILABLE = "available"
    RETAINED = "retained"
    FAILED = "failed"
    DELETE_PENDING = "delete_pending"
    TOMBSTONED = "tombstoned"


class StorageKind(StrEnum):
    POSTGRES_INLINE = "postgres_inline"
    OBJECT_STORE = "object_store"


class ContentMoveState(StrEnum):
    PENDING = "pending"
    TARGET_VERIFIED = "target_verified"
    FAILED = "failed"


class ContentMoveFailureCode(StrEnum):
    STORE_UNAVAILABLE = "store_unavailable"
    TARGET_TOO_LARGE = "target_too_large"
    SOURCE_MISSING = "source_missing"
    SOURCE_CORRUPT = "source_corrupt"
    TARGET_CORRUPT = "target_corrupt"
    CONTENT_INELIGIBLE = "content_ineligible"


class ContentAccessClass(StrEnum):
    PRIVATE_RESOURCE = "private_resource"
    PUBLIC_IMMUTABLE = "public_immutable"


class ContentFailureCode(StrEnum):
    OWNER_DETACHED = "owner_detached"
    UPLOAD_RETRYABLE = "upload_retryable"
    UPLOAD_REJECTED = "upload_rejected"
    VERIFICATION_MISMATCH = "verification_mismatch"
    BACKEND_MISSING = "backend_missing"
    BACKEND_CORRUPT = "backend_corrupt"
    REFERENCE_DRIFT = "reference_drift"
    DELETE_RETRYABLE = "delete_retryable"


class ObjectContentError(RuntimeError):
    code = "object_content_error"


class ObjectContentUnavailableError(ObjectContentError):
    code = "object_content_unavailable"


class ObjectContentConfigurationError(ObjectContentUnavailableError):
    code = "object_content_configuration_required"


class ObjectContentIntegrityError(ObjectContentError):
    code = "object_content_integrity_failure"


class ObjectContentIdempotencyConflictError(ObjectContentError):
    code = "object_content_idempotency_conflict"


class ObjectContentStateError(ObjectContentError):
    code = "object_content_state_conflict"


class ObjectContentBusyError(ObjectContentError):
    code = "object_content_busy"


class ContentTooLargeError(ValueError):
    code = "object_content_too_large"

    def __init__(self, maximum_size_bytes: int) -> None:
        super().__init__(f"Content exceeds the {maximum_size_bytes}-byte policy limit")
        self.maximum_size_bytes = maximum_size_bytes


class InvalidContentRangeError(ValueError):
    code = "object_content_range_invalid"


MAXIMUM_UPLOAD_POLICY_BYTES = 9_007_199_254_740_991

# Durable content sizes use PostgreSQL BIGINT, whose decimal width is 19 digits.
_MAX_BYTE_RANGE_DIGITS = 19


def _parse_byte_range_integer(value: str) -> int:
    normalized = value.lstrip("0") or "0"
    if (
        not value.isascii()
        or not value.isdigit()
        or len(normalized) > _MAX_BYTE_RANGE_DIGITS
    ):
        raise InvalidContentRangeError("The byte range is malformed")
    return int(normalized)


@dataclass(frozen=True, slots=True)
class ByteRange:
    start: int
    end: int
    total: int

    @classmethod
    def parse(cls, header: str, *, size_bytes: int) -> "ByteRange":
        if size_bytes <= 0 or not header.startswith("bytes="):
            raise InvalidContentRangeError("A byte range is not satisfiable")

        range_spec = header.removeprefix("bytes=")
        if "," in range_spec or range_spec.count("-") != 1:
            raise InvalidContentRangeError("Exactly one byte range is supported")

        start_text, end_text = range_spec.split("-", maxsplit=1)
        if not start_text:
            suffix_length = _parse_byte_range_integer(end_text)
            if suffix_length <= 0:
                raise InvalidContentRangeError("The suffix length must be positive")
            suffix_length = min(suffix_length, size_bytes)
            return cls(
                start=size_bytes - suffix_length,
                end=size_bytes - 1,
                total=size_bytes,
            )

        start = _parse_byte_range_integer(start_text)
        if start >= size_bytes:
            raise InvalidContentRangeError("The byte range starts after the content")

        end = (
            size_bytes - 1
            if not end_text
            else min(_parse_byte_range_integer(end_text), size_bytes - 1)
        )
        if end < start:
            raise InvalidContentRangeError("The byte range ends before it starts")
        return cls(start=start, end=end, total=size_bytes)

    @property
    def content_length(self) -> int:
        return self.end - self.start + 1

    @property
    def request_header(self) -> str:
        return f"bytes={self.start}-{self.end}"

    @property
    def response_header(self) -> str:
        return f"bytes {self.start}-{self.end}/{self.total}"


@dataclass(frozen=True, slots=True)
class VerificationChunkWindow:
    aligned_range: ByteRange
    first_chunk_index: int
    chunk_count: int


def verification_chunk_window(
    byte_range: ByteRange,
    *,
    chunk_size_bytes: int,
    chunk_count: int,
) -> VerificationChunkWindow:
    """Align one requested range to its persisted verification chunks."""
    if chunk_size_bytes < 1:
        raise ValueError("verification chunk size must be positive")
    expected_chunk_count = max(
        1,
        (byte_range.total + chunk_size_bytes - 1) // chunk_size_bytes,
    )
    if chunk_count != expected_chunk_count:
        raise ValueError("verification chunk count does not match object size")

    first_chunk_index = byte_range.start // chunk_size_bytes
    last_chunk_index = byte_range.end // chunk_size_bytes
    aligned_start = first_chunk_index * chunk_size_bytes
    aligned_end = min(
        byte_range.total - 1,
        ((last_chunk_index + 1) * chunk_size_bytes) - 1,
    )
    return VerificationChunkWindow(
        aligned_range=ByteRange(
            start=aligned_start,
            end=aligned_end,
            total=byte_range.total,
        ),
        first_chunk_index=first_chunk_index,
        chunk_count=last_chunk_index - first_chunk_index + 1,
    )


@dataclass(frozen=True, slots=True)
class CapturedContent:
    file: BinaryIO
    sha256: bytes
    size_bytes: int
    declared_media_type: str
    verified_media_type: str
    part_sha256: tuple[bytes, ...]
    part_size_bytes: int

    def __post_init__(self) -> None:
        if self.part_size_bytes < 1:
            raise ValueError("part_size_bytes must be positive")
        expected_part_count = max(
            1,
            (self.size_bytes + self.part_size_bytes - 1) // self.part_size_bytes,
        )
        if len(self.part_sha256) != expected_part_count:
            raise ValueError("part SHA-256 count does not match captured size")
        if any(len(digest) != 32 for digest in self.part_sha256):
            raise ValueError("part SHA-256 values must be 32-byte digests")


@dataclass(frozen=True, slots=True)
class ContentIntent:
    tenant_id: UUID
    created_by_user_id: UUID | None
    access_class: ContentAccessClass
    idempotency_key: str
    producer_receipt: str
    minimum_retain_until: datetime | None = None

    def __post_init__(self) -> None:
        if not 1 <= len(self.idempotency_key) <= 255:
            raise ValueError("idempotency_key must contain 1 to 255 characters")
        if not 1 <= len(self.producer_receipt) <= 1024:
            raise ValueError("producer_receipt must contain 1 to 1024 characters")
        if (
            self.minimum_retain_until is not None
            and self.minimum_retain_until.utcoffset() is None
        ):
            raise ValueError("minimum_retain_until must include a timezone")


@dataclass(frozen=True, slots=True)
class ContentReadGrant:
    content_id: UUID
    tenant_id: UUID
    access_class: ContentAccessClass


@dataclass(frozen=True, slots=True)
class ContentRead:
    chunks: AsyncIterator[bytes]
    content_length: int
    media_type: str
    content_range: str | None


def content_request_fingerprint(
    intent: ContentIntent,
    content: CapturedContent,
    storage_kind: StorageKind,
) -> bytes:
    """Bind idempotency to owner intent, byte authority, and content facts."""
    fingerprint = sha256()
    if storage_kind is StorageKind.OBJECT_STORE:
        # Object-store rows created before the backend split persist this exact
        # v1 encoding. Their storage_kind column independently fences attempts
        # to replay the same key through the inline backend.
        fingerprint.update(b"eneo-object-content-request-v1\0")
        storage_kind_field: tuple[bytes, ...] = ()
    else:
        fingerprint.update(b"eneo-object-content-request-v2\0")
        storage_kind_field = (storage_kind.value.encode(),)
    created_by = (
        b"" if intent.created_by_user_id is None else intent.created_by_user_id.bytes
    )
    minimum_retain_until = (
        b""
        if intent.minimum_retain_until is None
        else intent.minimum_retain_until.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .encode()
    )
    fields = (
        intent.producer_receipt.encode(),
        created_by,
        intent.access_class.value.encode(),
        *storage_kind_field,
        minimum_retain_until,
        content.sha256,
        content.size_bytes.to_bytes(8, "big", signed=False),
        content.declared_media_type.encode(),
        content.verified_media_type.encode(),
    )
    for field in fields:
        fingerprint.update(len(field).to_bytes(8, "big", signed=False))
        fingerprint.update(field)
    return fingerprint.digest()


@asynccontextmanager
async def capture_content(
    source: AsyncIterable[bytes],
    *,
    declared_media_type: str,
    verified_media_type: str,
    maximum_size_bytes: int,
    spool_memory_bytes: int,
    multipart_part_bytes: int,
) -> AsyncGenerator[CapturedContent]:
    if maximum_size_bytes < 0:
        raise ValueError("maximum_size_bytes must not be negative")
    if spool_memory_bytes < 1:
        raise ValueError("spool_memory_bytes must be positive")
    if multipart_part_bytes < 1:
        raise ValueError("multipart_part_bytes must be positive")
    if not 1 <= len(declared_media_type) <= 255:
        raise ValueError("declared_media_type must contain 1 to 255 characters")
    if not 1 <= len(verified_media_type) <= 255:
        raise ValueError("verified_media_type must contain 1 to 255 characters")

    spool = SpooledTemporaryFile(max_size=spool_memory_bytes, mode="w+b")
    canonical_hasher = sha256()
    current_part_hasher = sha256()
    current_part_size = 0
    part_digests: list[bytes] = []
    size_bytes = 0
    spilled_to_disk = False

    try:
        async for chunk in source:
            if not chunk:
                continue

            next_size = size_bytes + len(chunk)
            if next_size > maximum_size_bytes:
                raise ContentTooLargeError(maximum_size_bytes)

            canonical_hasher.update(chunk)
            if next_size > spool_memory_bytes:
                spilled_to_disk = True
                await asyncio.to_thread(spool.write, chunk)
            else:
                spool.write(chunk)
            size_bytes = next_size

            remaining = memoryview(chunk)
            while remaining:
                bytes_needed = multipart_part_bytes - current_part_size
                part_slice = remaining[:bytes_needed]
                current_part_hasher.update(part_slice)
                current_part_size += len(part_slice)
                remaining = remaining[len(part_slice) :]
                if current_part_size == multipart_part_bytes:
                    part_digests.append(current_part_hasher.digest())
                    current_part_hasher = sha256()
                    current_part_size = 0

        if current_part_size:
            part_digests.append(current_part_hasher.digest())
        elif size_bytes == 0:
            part_digests.append(canonical_hasher.digest())

        if spilled_to_disk:
            await asyncio.to_thread(spool.seek, 0)
        else:
            spool.seek(0)
        yield CapturedContent(
            file=cast(BinaryIO, spool),
            sha256=canonical_hasher.digest(),
            size_bytes=size_bytes,
            declared_media_type=declared_media_type,
            verified_media_type=verified_media_type,
            part_sha256=tuple(part_digests),
            part_size_bytes=multipart_part_bytes,
        )
    finally:
        if spilled_to_disk:
            await asyncio.to_thread(spool.close)
        else:
            spool.close()
