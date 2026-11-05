"""Tests for FileProtocol limits from the immutable upload-admission snapshot."""

import asyncio
import gc
import threading
import time
import weakref
from contextvars import ContextVar
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

from eneo.files import file_protocol as file_protocol_module
from eneo.files.file_models import FileContentVariant
from eneo.files.file_protocol import FileProtocol
from eneo.main.exceptions import FileTooLargeException
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot

# ── Fake settings ────────────────────────────────────────────────────────

TEXT_MAX = 25_000_000  # 25 MB
IMAGE_MAX = 20_000_000  # 20 MB
AUDIO_MAX = 200_000_000  # 200 MB

_FAKE_SETTINGS = SimpleNamespace(
    upload_tmp_dir=Path("/tmp"),
    attachment_image_extraction=False,
    attachment_max_extracted_images=10,
)
_UPLOAD_ADMISSION = UploadAdmissionSnapshot(
    policy_revision=7,
    new_write_storage_target=StorageKind.POSTGRES_INLINE,
    session_file_maximum_bytes=TEXT_MAX,
    session_image_maximum_bytes=IMAGE_MAX,
    session_audio_maximum_bytes=AUDIO_MAX,
    knowledge_file_maximum_bytes=30_000_000,
    knowledge_audio_maximum_bytes=220_000_000,
)
_REQUEST: ContextVar[str | None] = ContextVar("request", default=None)
_OBJECT_STORE_ENVELOPE = 10_000_000
_OBJECT_STORE_ADMISSION = replace(
    _UPLOAD_ADMISSION,
    new_write_storage_target=StorageKind.OBJECT_STORE,
    session_file_maximum_bytes=_OBJECT_STORE_ENVELOPE,
    session_image_maximum_bytes=_OBJECT_STORE_ENVELOPE,
    session_audio_maximum_bytes=_OBJECT_STORE_ENVELOPE,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    monkeypatch.setattr(file_protocol_module, "get_settings", lambda: _FAKE_SETTINGS)
    monkeypatch.setattr(
        file_protocol_module,
        "downscale_image",
        lambda blob, mimetype: SimpleNamespace(blob=blob, mimetype=mimetype),
    )


@pytest.fixture
def protocol(tmp_path):
    file_size_service = MagicMock()

    # save_file_to_disk returns a real temp file path
    async def fake_save(file):
        dest = tmp_path / "uploaded"
        dest.write_bytes(b"x")
        return str(dest)

    file_size_service.save_file_to_disk = fake_save
    file_size_service.get_file_checksum.return_value = "fakechecksum"

    text_extractor = MagicMock()
    text_extractor.extract_bounded = AsyncMock(return_value="extracted text")

    image_extractor = MagicMock()
    image_extractor.extract.return_value = b"image-bytes"

    return FileProtocol(
        file_size_service=file_size_service,
        text_extractor=text_extractor,
        image_extractor=image_extractor,
    )


def _make_upload(content_type: str, size: int) -> UploadFile:
    """Create an UploadFile with a file object that reports the given size."""
    data = BytesIO(b"x" * min(size, 1024))  # don't allocate huge buffers
    upload = UploadFile(
        file=data, filename="test_file", headers={"content-type": content_type}
    )
    return upload, size


async def _content_bytes(content) -> bytes:
    return b"".join([chunk async for chunk in content.chunks])


async def _prepare(protocol: FileProtocol, upload: UploadFile):
    async with protocol.prepare_upload(
        upload,
        upload_admission_snapshot=_UPLOAD_ADMISSION,
    ) as prepared:
        return prepared


@pytest.mark.asyncio
async def test_prepare_pdf_preserves_original_and_extracted_text_variants(
    protocol, tmp_path
):
    original = b"%PDF exact source bytes"
    upload = UploadFile(
        file=BytesIO(original),
        filename="report.pdf",
        headers={"content-type": "application/pdf"},
    )
    protocol.file_size_service.get_file_size.return_value = len(original)

    async def save_original(_file):
        path = tmp_path / "report.pdf"
        path.write_bytes(original)
        return str(path)

    protocol.file_size_service.save_file_to_disk = save_original

    async with protocol.prepare_upload(
        upload,
        upload_admission_snapshot=_UPLOAD_ADMISSION,
    ) as prepared:
        by_variant = {content.variant: content for content in prepared.contents}
        assert await _content_bytes(by_variant[FileContentVariant.ORIGINAL]) == original
        assert (
            await _content_bytes(by_variant[FileContentVariant.EXTRACTED_TEXT])
            == b"extracted text"
        )


@pytest.mark.asyncio
async def test_prepare_image_keeps_original_separate_from_model_input(
    protocol, tmp_path, monkeypatch
):
    original = b"exact uploaded image"
    upload = UploadFile(
        file=BytesIO(original),
        filename="photo.png",
        headers={"content-type": "image/png"},
    )
    protocol.file_size_service.get_file_size.return_value = len(original)

    async def save_original(_file):
        path = tmp_path / "photo.png"
        path.write_bytes(original)
        return str(path)

    protocol.file_size_service.save_file_to_disk = save_original
    monkeypatch.setattr(
        file_protocol_module,
        "downscale_image",
        lambda _blob, _mimetype: SimpleNamespace(
            blob=b"bounded model image",
            mimetype="image/jpeg",
        ),
    )

    async with protocol.prepare_upload(
        upload,
        upload_admission_snapshot=_UPLOAD_ADMISSION,
    ) as prepared:
        by_variant = {content.variant: content for content in prepared.contents}
        assert await _content_bytes(by_variant[FileContentVariant.ORIGINAL]) == original
        assert (
            await _content_bytes(by_variant[FileContentVariant.MODEL_INPUT])
            == b"bounded model image"
        )


@pytest.mark.asyncio
async def test_prepare_image_reads_and_downscales_off_the_event_loop(
    protocol, tmp_path, monkeypatch
):
    """Decoding a photo takes about 0.1 s of CPU; on the loop it stalls every
    request and stream the worker serves."""
    original = b"exact uploaded image"
    upload = UploadFile(
        file=BytesIO(original),
        filename="photo.png",
        headers={"content-type": "image/png"},
    )
    protocol.file_size_service.get_file_size.return_value = len(original)

    async def save_original(_file):
        path = tmp_path / "photo.png"
        path.write_bytes(original)
        return str(path)

    protocol.file_size_service.save_file_to_disk = save_original
    loop_thread = threading.get_ident()
    threads: dict[str, int] = {}
    # Log records carry the request's context; the worker must still see it.
    _REQUEST.set("request-1")

    def extract(*_args):
        threads["extract"] = threading.get_ident()
        return b"image-bytes"

    def downscale(blob, mimetype):
        threads["downscale"] = threading.get_ident()
        assert _REQUEST.get() == "request-1"
        return SimpleNamespace(blob=blob, mimetype=mimetype)

    protocol.image_extractor.extract.side_effect = extract
    monkeypatch.setattr(file_protocol_module, "downscale_image", downscale)

    async with protocol.prepare_upload(
        upload,
        upload_admission_snapshot=_UPLOAD_ADMISSION,
    ) as prepared:
        by_variant = {content.variant: content for content in prepared.contents}
        assert (
            await _content_bytes(by_variant[FileContentVariant.MODEL_INPUT])
            == b"image-bytes"
        )

    assert threads.keys() == {"extract", "downscale"}
    assert loop_thread not in threads.values()


@pytest.mark.asyncio
async def test_concurrent_image_uploads_decode_one_at_a_time(protocol):
    """A decoding 12 MP photo holds about 80 MB; photos uploaded together must
    not all hold it at once."""
    active = 0
    most_active = 0
    lock = threading.Lock()

    def extract(*_args):
        nonlocal active, most_active
        with lock:
            active += 1
            most_active = max(most_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return b"image-bytes"

    protocol.image_extractor.extract.side_effect = extract
    protocol.file_size_service.get_file_size.return_value = 3

    async def upload():
        async with protocol.prepare_upload(
            UploadFile(
                file=BytesIO(b"img"),
                filename="photo.png",
                headers={"content-type": "image/png"},
            ),
            upload_admission_snapshot=_UPLOAD_ADMISSION,
        ):
            pass

    await asyncio.gather(*(upload() for _ in range(4)))

    assert most_active == 1


@pytest.mark.asyncio
async def test_cancelled_image_uploads_behind_a_slow_decode_hold_nothing(protocol):
    """Uploads cancelled while a photo decodes must not leave jobs queued
    behind it: each queued job keeps its upload alive until the decoder
    reaches it, so repeated cancellation would grow memory without bound."""
    started = threading.Event()
    release = threading.Event()

    def extract(*_args):
        started.set()
        release.wait(timeout=5)
        return b"image-bytes"

    protocol.image_extractor.extract.side_effect = extract
    protocol.file_size_service.get_file_size.return_value = 3

    def photo() -> UploadFile:
        return UploadFile(
            file=BytesIO(b"img"),
            filename="photo.png",
            headers={"content-type": "image/png"},
        )

    async def upload(file: UploadFile):
        async with protocol.prepare_upload(
            file, upload_admission_snapshot=_UPLOAD_ADMISSION
        ):
            pass

    first = asyncio.create_task(upload(photo()))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        files = [photo() for _ in range(64)]
        alive = [weakref.ref(file) for file in files]
        waiting = [asyncio.create_task(upload(file)) for file in files]
        del files
        await asyncio.sleep(0.05)
        # Every upload is past its size check and waiting for the decoder.
        assert protocol.file_size_service.get_file_size.call_count == 65
        for task in waiting:
            task.cancel()
        await asyncio.wait(waiting)
        del waiting, task
        gc.collect()

        assert not first.done()
        assert sum(ref() is not None for ref in alive) == 0
        decoder = file_protocol_module._IMAGE_DECODER
        assert decoder._executor._work_queue.qsize() == 0
    finally:
        release.set()
        await first
    assert protocol.image_extractor.extract.call_count == 1


@pytest.mark.asyncio
async def test_prepare_audio_preserves_exact_original(protocol, tmp_path):
    original = b"exact audio bytes"
    upload = UploadFile(
        file=BytesIO(original),
        filename="meeting.mp3",
        headers={"content-type": "audio/mpeg"},
    )
    protocol.file_size_service.get_file_size.return_value = len(original)

    async def save_original(_file):
        path = tmp_path / "meeting.mp3"
        path.write_bytes(original)
        return str(path)

    protocol.file_size_service.save_file_to_disk = save_original

    async with protocol.prepare_upload(
        upload,
        upload_admission_snapshot=_UPLOAD_ADMISSION,
    ) as prepared:
        assert len(prepared.contents) == 1
        content = prepared.contents[0]
        assert content.variant is FileContentVariant.ORIGINAL
        assert await _content_bytes(content) == original


# ── Tests: text files use TEXT_MAX ───────────────────────────────────────


@pytest.mark.asyncio
async def test_text_under_limit_accepted(protocol):
    upload, size = _make_upload("text/plain", TEXT_MAX)
    protocol.file_size_service.get_file_size.return_value = size

    result = await _prepare(protocol, upload)

    assert result.file_type.value == "text"


@pytest.mark.asyncio
async def test_text_over_limit_rejected(protocol):
    upload, size = _make_upload("text/plain", TEXT_MAX + 1)
    protocol.file_size_service.get_file_size.return_value = size

    with pytest.raises(FileTooLargeException) as exc_info:
        await _prepare(protocol, upload)

    assert exc_info.value.max_size == TEXT_MAX
    assert exc_info.value.limit_name == "session_file"


@pytest.mark.asyncio
async def test_object_store_envelope_plus_one_rejected_before_disk_spool(protocol):
    upload, size = _make_upload("text/plain", _OBJECT_STORE_ENVELOPE + 1)
    protocol.file_size_service.get_file_size.return_value = size
    protocol.file_size_service.save_file_to_disk = AsyncMock(
        side_effect=AssertionError("oversized upload must not reach disk spooling")
    )

    with pytest.raises(FileTooLargeException) as exc_info:
        async with protocol.prepare_upload(
            upload,
            upload_admission_snapshot=_OBJECT_STORE_ADMISSION,
        ):
            pass

    assert exc_info.value.max_size == _OBJECT_STORE_ENVELOPE
    protocol.file_size_service.save_file_to_disk.assert_not_awaited()


# ── Tests: image files use IMAGE_MAX ─────────────────────────────────────


@pytest.mark.asyncio
async def test_image_under_limit_accepted(protocol):
    upload, size = _make_upload("image/png", IMAGE_MAX)
    protocol.file_size_service.get_file_size.return_value = size

    result = await _prepare(protocol, upload)

    assert result.file_type.value == "image"


@pytest.mark.asyncio
async def test_image_over_limit_rejected(protocol):
    upload, size = _make_upload("image/png", IMAGE_MAX + 1)
    protocol.file_size_service.get_file_size.return_value = size

    with pytest.raises(FileTooLargeException) as exc_info:
        await _prepare(protocol, upload)

    assert exc_info.value.max_size == IMAGE_MAX
    assert exc_info.value.limit_name == "session_image"


# ── Tests: audio files use AUDIO_MAX (the 200 MB fix) ───────────────────


@pytest.mark.asyncio
async def test_audio_under_limit_accepted(protocol):
    """Audio files up to AUDIO_MAX (200 MB) should be accepted — this was the bug."""
    upload, size = _make_upload("audio/mpeg", AUDIO_MAX)
    protocol.file_size_service.get_file_size.return_value = size

    result = await _prepare(protocol, upload)

    assert result.file_type.value == "audio"


@pytest.mark.asyncio
async def test_audio_over_limit_rejected(protocol):
    upload, size = _make_upload("audio/mpeg", AUDIO_MAX + 1)
    protocol.file_size_service.get_file_size.return_value = size

    with pytest.raises(FileTooLargeException) as exc_info:
        await _prepare(protocol, upload)

    assert exc_info.value.max_size == AUDIO_MAX
    assert exc_info.value.limit_name == "session_audio"


@pytest.mark.asyncio
async def test_audio_50mb_accepted(protocol):
    """50 MB audio file — well within 200 MB limit, but would have failed with old 10 MB limit."""
    upload, size = _make_upload("audio/mpeg", 50_000_000)
    protocol.file_size_service.get_file_size.return_value = size

    result = await _prepare(protocol, upload)

    assert result.file_type.value == "audio"


# ── Tests: to_domain dispatches correctly without explicit max_size ──────


@pytest.mark.asyncio
async def test_to_domain_routes_audio_mime_types(protocol):
    """All audio MIME types should route through audio_to_domain."""
    for mime in [
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/ogg",
        "audio/webm",
        "video/webm",
    ]:
        upload, size = _make_upload(mime, 1000)
        protocol.file_size_service.get_file_size.return_value = size

        result = await _prepare(protocol, upload)

        assert result.file_type.value == "audio", f"MIME {mime} should route to audio"


@pytest.mark.asyncio
async def test_to_domain_routes_image_mime_types(protocol):
    """Image MIME types should route through image_to_domain."""
    for mime in ["image/png", "image/jpeg", "image/webp", "image/avif"]:
        upload, size = _make_upload(mime, 1000)
        protocol.file_size_service.get_file_size.return_value = size

        result = await _prepare(protocol, upload)

        assert result.file_type.value == "image", f"MIME {mime} should route to image"
        assert {content.variant for content in result.contents} == {
            FileContentVariant.ORIGINAL,
            FileContentVariant.MODEL_INPUT,
        }


@pytest.mark.asyncio
async def test_to_domain_routes_text_mime_types(protocol):
    """Non-image, non-audio MIME types should route through text_to_domain."""
    for mime in ["text/plain", "application/pdf", "text/csv"]:
        upload, size = _make_upload(mime, 1000)
        protocol.file_size_service.get_file_size.return_value = size

        result = await _prepare(protocol, upload)

        assert result.file_type.value == "text", f"MIME {mime} should route to text"


# ── Test: each type has independent limits ───────────────────────────────


@pytest.mark.asyncio
async def test_audio_limit_is_independent_of_text_limit(protocol):
    """Audio admission uses the persisted transcription policy, not the text policy."""
    upload, size = _make_upload("audio/mpeg", 15_000_000)
    protocol.file_size_service.get_file_size.return_value = size

    result = await _prepare(protocol, upload)

    assert result.file_type.value == "audio"
