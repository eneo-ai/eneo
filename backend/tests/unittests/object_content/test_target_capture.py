from collections.abc import AsyncGenerator
from typing import cast

import pytest

from eneo.object_content.configuration import (
    ObjectContentCoreSettings,
    ObjectContentSettings,
)
from eneo.object_content.content import (
    ContentTooLargeError,
    StorageKind,
)
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.s3_object_store import S3ObjectStore


async def _source(payload: bytes) -> AsyncGenerator[bytes]:
    yield payload


def _service(
    *,
    inline_maximum_bytes: int = 6,
    multipart_part_bytes: int = 5,
) -> ObjectContentService:
    core = ObjectContentCoreSettings(
        _env_file=None,
        inline_maximum_bytes=inline_maximum_bytes,
        inline_io_chunk_bytes=2,
    )
    remote = ObjectContentSettings.model_construct(
        inline_maximum_bytes=inline_maximum_bytes,
        inline_io_chunk_bytes=2,
        spool_memory_bytes=3,
        multipart_part_bytes=multipart_part_bytes,
    )
    return ObjectContentService(
        core,
        object_store_settings=remote,
        object_store=cast(S3ObjectStore, object()),
    )


@pytest.mark.asyncio
async def test_inline_target_accepts_operator_maximum_and_rejects_maximum_plus_one() -> (
    None
):
    service = _service(inline_maximum_bytes=6)
    async with service.capture_for_target(
        _source(b"123456"),
        storage_kind=StorageKind.POSTGRES_INLINE,
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        business_maximum_bytes=20,
    ) as captured:
        assert captured.size_bytes == 6
        assert len(captured.part_sha256) == 3

    with pytest.raises(ContentTooLargeError) as error:
        async with service.capture_for_target(
            _source(b"1234567"),
            storage_kind=StorageKind.POSTGRES_INLINE,
            declared_media_type="text/plain",
            verified_media_type="text/plain",
            business_maximum_bytes=20,
        ):
            pytest.fail("operator maximum + 1 must not be captured")
    assert error.value.maximum_size_bytes == 6


@pytest.mark.asyncio
async def test_object_store_target_uses_configured_multipart_part_size() -> None:
    service = _service(multipart_part_bytes=5)
    async with service.capture_for_target(
        _source(b"12345678901"),
        storage_kind=StorageKind.OBJECT_STORE,
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        business_maximum_bytes=11,
    ) as captured:
        assert captured.size_bytes == 11
        assert len(captured.part_sha256) == 3


@pytest.mark.asyncio
async def test_object_store_target_rejects_portable_multipart_maximum_plus_one() -> (
    None
):
    service = _service(multipart_part_bytes=1)
    portable_maximum = 10_000

    async with service.capture_for_target(
        _source(b"x" * portable_maximum),
        storage_kind=StorageKind.OBJECT_STORE,
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        business_maximum_bytes=portable_maximum + 1,
    ) as captured:
        assert captured.size_bytes == portable_maximum

    with pytest.raises(ContentTooLargeError) as error:
        async with service.capture_for_target(
            _source(b"x" * (portable_maximum + 1)),
            storage_kind=StorageKind.OBJECT_STORE,
            declared_media_type="application/octet-stream",
            verified_media_type="application/octet-stream",
            business_maximum_bytes=portable_maximum + 1,
        ):
            pytest.fail("portable multipart maximum + 1 must not be captured")

    assert error.value.maximum_size_bytes == portable_maximum


@pytest.mark.asyncio
async def test_object_store_generated_content_uses_operator_ceiling_without_business_limit() -> (
    None
):
    service = _service(multipart_part_bytes=1)
    portable_maximum = 10_000

    async with service.capture_for_target(
        _source(b"x" * portable_maximum),
        storage_kind=StorageKind.OBJECT_STORE,
        declared_media_type="text/plain",
        verified_media_type="text/plain",
    ) as captured:
        assert captured.size_bytes == portable_maximum

    with pytest.raises(ContentTooLargeError) as error:
        async with service.capture_for_target(
            _source(b"x" * (portable_maximum + 1)),
            storage_kind=StorageKind.OBJECT_STORE,
            declared_media_type="text/plain",
            verified_media_type="text/plain",
        ):
            pytest.fail("operator maximum + 1 must not be captured")

    assert error.value.maximum_size_bytes == portable_maximum


@pytest.mark.asyncio
async def test_inline_generated_content_uses_operator_ceiling_without_business_limit() -> (
    None
):
    service = _service(inline_maximum_bytes=6)
    async with service.capture_for_target(
        _source(b"123456"),
        storage_kind=StorageKind.POSTGRES_INLINE,
        declared_media_type="image/jpeg",
        verified_media_type="image/jpeg",
    ) as captured:
        assert captured.size_bytes == 6
