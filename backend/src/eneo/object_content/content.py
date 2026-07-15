import asyncio
from collections.abc import AsyncGenerator, AsyncIterable
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


class ContentAccessClass(StrEnum):
    PRIVATE_RESOURCE = "private_resource"
    PUBLIC_IMMUTABLE = "public_immutable"


class ContentFailureCode(StrEnum):
    OWNER_DETACHED = "owner_detached"
    UPLOAD_RETRYABLE = "upload_retryable"
    UPLOAD_REJECTED = "upload_rejected"
    VERIFICATION_MISMATCH = "verification_mismatch"
    REMOTE_MISSING = "remote_missing"
    REMOTE_CORRUPT = "remote_corrupt"
    REFERENCE_DRIFT = "reference_drift"
    DELETE_RETRYABLE = "delete_retryable"


class ObjectContentError(RuntimeError):
    code = "object_content_error"


class ObjectContentUnavailableError(ObjectContentError):
    code = "object_content_unavailable"


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
            if not end_text.isdigit() or int(end_text) <= 0:
                raise InvalidContentRangeError("The suffix length must be positive")
            suffix_length = min(int(end_text), size_bytes)
            return cls(
                start=size_bytes - suffix_length,
                end=size_bytes - 1,
                total=size_bytes,
            )

        if not start_text.isdigit() or (end_text and not end_text.isdigit()):
            raise InvalidContentRangeError("The byte range is malformed")

        start = int(start_text)
        if start >= size_bytes:
            raise InvalidContentRangeError("The byte range starts after the content")

        end = size_bytes - 1 if not end_text else min(int(end_text), size_bytes - 1)
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
class CapturedContent:
    file: BinaryIO
    sha256: bytes
    size_bytes: int
    declared_media_type: str
    verified_media_type: str
    part_sha256: tuple[bytes, ...]


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


def content_request_fingerprint(
    intent: ContentIntent,
    content: CapturedContent,
) -> bytes:
    """Bind an idempotency key to owner intent and canonical content facts."""
    fingerprint = sha256()
    fingerprint.update(b"eneo-object-content-request-v1\0")
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
        )
    finally:
        if spilled_to_disk:
            await asyncio.to_thread(spool.close)
        else:
            spool.close()
