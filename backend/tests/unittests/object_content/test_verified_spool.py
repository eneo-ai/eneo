import asyncio
from io import BufferedRandom, FileIO
from pathlib import Path

import pytest

from eneo.object_content import verified_spool
from eneo.object_content.content import ObjectContentUnavailableError
from eneo.object_content.verified_spool import VerifiedSpool


@pytest.fixture
def buffered_spool(monkeypatch, tmp_path):
    class FailingWrites(FileIO):
        write_attempts = 0

        def write(self, data):
            self.write_attempts += 1
            raise OSError("Buffered flush failed")

    path = tmp_path / "verified-content"
    raw = FailingWrites(path, "w+")
    file = BufferedRandom(raw)
    monkeypatch.setattr(verified_spool, "NamedTemporaryFile", lambda **kwargs: file)
    return file, raw, path


async def test_buffered_flush_failure_keeps_unavailable_during_close(buffered_spool):
    file, raw, path = buffered_spool
    primary = None

    with pytest.raises(ObjectContentUnavailableError, match="seek failed") as caught:
        async with VerifiedSpool.open(io_chunk_bytes=256) as spool:
            await spool.write(b"buffered")
            assert raw.write_attempts == 0
            try:
                async with spool.read(media_type="text/plain"):
                    pytest.fail("A failed flush must not expose readable content")
            except ObjectContentUnavailableError as error:
                primary = error
                raise

    assert caught.value is primary
    assert raw.write_attempts == 2
    assert file.closed
    assert not path.exists()


async def test_cancellation_with_buffered_bytes_survives_close_failure(buffered_spool):
    file, raw, path = buffered_spool
    buffered = asyncio.Event()

    async def read():
        async with VerifiedSpool.open(io_chunk_bytes=256) as spool:
            await spool.write(b"buffered")
            buffered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(read())
    try:
        await asyncio.wait_for(buffered.wait(), timeout=5)
        assert raw.write_attempts == 0
        task.cancel("Read cancelled")
        with pytest.raises(asyncio.CancelledError, match="Read cancelled"):
            await task
        assert task.cancelled()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert raw.write_attempts == 1
    assert file.closed
    assert not path.exists()


async def test_standalone_close_failure_is_unavailable(buffered_spool):
    file, raw, path = buffered_spool

    with pytest.raises(ObjectContentUnavailableError) as caught:
        async with VerifiedSpool.open(io_chunk_bytes=256) as spool:
            await spool.write(b"buffered")
            assert raw.write_attempts == 0

    assert isinstance(caught.value.__cause__, OSError)
    assert raw.write_attempts == 1
    assert file.closed
    assert not path.exists()


@pytest.mark.parametrize(
    "primary",
    [
        None,
        ObjectContentUnavailableError("Original unavailable error"),
        asyncio.CancelledError("Original cancellation"),
    ],
    ids=["standalone", "unavailable", "cancelled"],
)
async def test_unlink_failure_preserves_primary_or_is_unavailable(
    buffered_spool, monkeypatch, primary
):
    file, _, path = buffered_spool
    unlink_error = OSError("Unlink failed")
    unlink_attempts = []
    original_unlink = Path.unlink

    def fail_unlink(target, *, missing_ok=False):
        if target == path:
            unlink_attempts.append(target)
            raise unlink_error
        return original_unlink(target, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    expected = ObjectContentUnavailableError if primary is None else type(primary)
    try:
        with pytest.raises(expected) as caught:
            async with VerifiedSpool.open(io_chunk_bytes=256):
                if primary is not None:
                    raise primary

        if primary is None:
            assert caught.value.__cause__ is unlink_error
        else:
            assert caught.value is primary
        assert file.closed
        assert unlink_attempts == [path]
        assert path.exists()
    finally:
        original_unlink(path, missing_ok=True)
