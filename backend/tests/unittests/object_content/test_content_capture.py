import hashlib
import os
import stat

import pytest

from eneo.object_content import content as content_module
from eneo.object_content.content import ContentTooLargeError, capture_content


@pytest.mark.asyncio
async def test_capture_content_hashes_exact_stream_and_spools_owner_only() -> None:
    chunks = (b"abc", b"defgh", b"ijkl")

    async def source():
        for chunk in chunks:
            yield chunk

    async with capture_content(
        source(),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        maximum_size_bytes=12,
        spool_memory_bytes=4,
        multipart_part_bytes=5,
    ) as captured:
        expected = b"".join(chunks)
        assert captured.size_bytes == len(expected)
        assert captured.sha256 == hashlib.sha256(expected).digest()
        assert captured.part_sha256 == (
            hashlib.sha256(expected[:5]).digest(),
            hashlib.sha256(expected[5:10]).digest(),
            hashlib.sha256(expected[10:]).digest(),
        )
        assert captured.declared_media_type == "text/plain"
        assert captured.verified_media_type == "text/plain"

        spool_mode = stat.S_IMODE(os.fstat(captured.file.fileno()).st_mode)
        assert spool_mode == 0o600


@pytest.mark.asyncio
async def test_capture_content_rejects_maximum_plus_one_without_reading_ahead() -> None:
    consumed: list[bytes] = []

    async def source():
        for chunk in (b"1234", b"5", b"must-not-be-read"):
            consumed.append(chunk)
            yield chunk

    with pytest.raises(ContentTooLargeError) as error:
        async with capture_content(
            source(),
            declared_media_type="application/octet-stream",
            verified_media_type="application/octet-stream",
            maximum_size_bytes=4,
            spool_memory_bytes=2,
            multipart_part_bytes=2,
        ):
            pytest.fail("oversized content must not be yielded")

    assert error.value.maximum_size_bytes == 4
    assert consumed == [b"1234", b"5"]


@pytest.mark.asyncio
async def test_capture_offloads_spilled_file_io_from_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    offloaded: list[str] = []
    original_to_thread = content_module.asyncio.to_thread

    async def recording_to_thread(function, /, *args, **kwargs):
        offloaded.append(function.__name__)
        return await original_to_thread(function, *args, **kwargs)

    monkeypatch.setattr(content_module.asyncio, "to_thread", recording_to_thread)

    async def source():
        yield b"spilled-content"

    async with capture_content(
        source(),
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        maximum_size_bytes=15,
        spool_memory_bytes=4,
        multipart_part_bytes=5,
    ) as captured:
        assert captured.file.read() == b"spilled-content"

    assert {"write", "seek", "close"} <= set(offloaded)
