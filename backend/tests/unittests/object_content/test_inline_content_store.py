from hashlib import sha256
from io import BytesIO

import pytest

from eneo.object_content.content import (
    ByteRange,
    CapturedContent,
    ContentTooLargeError,
    ObjectContentIntegrityError,
)
from eneo.object_content.inline_content_store import InlineContentStore


def _captured(payload: bytes) -> CapturedContent:
    return CapturedContent(
        file=BytesIO(payload),
        sha256=sha256(payload).digest(),
        size_bytes=len(payload),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        part_sha256=(sha256(payload).digest(),),
    )


@pytest.mark.asyncio
async def test_inline_materialization_accepts_exact_deployment_ceiling() -> None:
    store = InlineContentStore(maximum_size_bytes=8, io_chunk_bytes=3)
    content = _captured(b"12345678")

    assert await store.materialize(content) == b"12345678"


@pytest.mark.asyncio
async def test_inline_materialization_rejects_maximum_plus_one_without_reading() -> (
    None
):
    store = InlineContentStore(maximum_size_bytes=8, io_chunk_bytes=3)
    content = _captured(b"123456789")
    content.file.close()

    with pytest.raises(ContentTooLargeError) as captured:
        await store.materialize(content)

    assert captured.value.maximum_size_bytes == 8


@pytest.mark.asyncio
async def test_inline_read_verifies_full_content_before_serving_single_range() -> None:
    payload = b"0123456789"
    store = InlineContentStore(maximum_size_bytes=len(payload), io_chunk_bytes=2)

    async with store.open_verified_read(
        payload,
        expected_sha256=sha256(payload).digest(),
        expected_size_bytes=len(payload),
        expected_media_type="text/plain",
        byte_range=ByteRange.parse("bytes=3-7", size_bytes=len(payload)),
    ) as opened:
        chunks = [chunk async for chunk in opened.chunks]

    assert chunks == [b"34", b"56", b"7"]
    assert opened.content_length == 5
    assert opened.content_range == "bytes 3-7/10"
    assert opened.media_type == "text/plain"


@pytest.mark.asyncio
async def test_inline_read_rejects_same_size_corruption_before_yielding() -> None:
    canonical = b"canonical"
    store = InlineContentStore(maximum_size_bytes=32, io_chunk_bytes=4)

    with pytest.raises(ObjectContentIntegrityError, match="SHA-256"):
        async with store.open_verified_read(
            b"corrupted",
            expected_sha256=sha256(canonical).digest(),
            expected_size_bytes=len(canonical),
            expected_media_type="text/plain",
        ):
            pytest.fail("Corrupt inline bytes must not be exposed")
