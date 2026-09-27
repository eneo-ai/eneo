"""Tests for FileProtocol limits from the immutable upload-admission snapshot."""

import asyncio
import os
import shutil
import subprocess
import time
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

from eneo.files import audio
from eneo.files import file_protocol as file_protocol_module
from eneo.files.file_models import FileContentVariant
from eneo.files.file_protocol import FileProtocol
from eneo.files.text import (
    PdfExtractionLimitExceeded,
    PdfExtractionLimits,
    TextExtractor,
)
from eneo.main.config import get_settings
from eneo.main.exceptions import FileTooLargeException
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot
from tests.unittests.files.test_pdf_extraction_limits import _hanging_child, _write_pdf

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

    async def fake_save(file):
        dest = tmp_path / "uploaded"
        position = file.tell()
        file.seek(0)
        dest.write_bytes(file.read())
        file.seek(position)
        return str(dest)

    file_size_service.save_file_to_disk = fake_save
    file_size_service.get_file_checksum.return_value = "fakechecksum"

    text_extractor = MagicMock()
    text_extractor.extract.return_value = "extracted text"

    image_extractor = MagicMock()
    image_extractor.extract.return_value = b"image-bytes"

    return FileProtocol(
        file_size_service=file_size_service,
        text_extractor=text_extractor,
        image_extractor=image_extractor,
    )


def _make_upload(content_type: str, size: int) -> tuple[UploadFile, int]:
    """Create an UploadFile with a file object that reports the given size."""
    data = BytesIO(b"x" * min(size, 1024))  # don't allocate huge buffers
    upload = UploadFile(
        file=data, filename="test_file", headers={"content-type": content_type}
    )
    return upload, size


async def _content_bytes(content) -> bytes:
    return b"".join([chunk async for chunk in content.chunks])


async def _prepare(protocol: FileProtocol, upload: UploadFile, *, pdf_limits=None):
    async with protocol.prepare_upload(
        upload,
        upload_admission_snapshot=_UPLOAD_ADMISSION,
        pdf_limits=pdf_limits,
    ) as prepared:
        return prepared


@pytest.mark.asyncio
async def test_non_flow_pdf_upload_ignores_flow_ceilings(
    protocol, tmp_path, monkeypatch
):
    monkeypatch.setattr(get_settings(), "flow_pdf_max_pages", 1)
    monkeypatch.setattr(get_settings(), "flow_pdf_max_extracted_bytes", 1)
    protocol.text_extractor = TextExtractor()
    payload = _write_pdf(tmp_path / "source.pdf", 2).read_bytes()
    upload = UploadFile(
        file=BytesIO(payload),
        filename="source.pdf",
        headers={"content-type": "application/pdf"},
    )
    protocol.file_size_service.get_file_size.return_value = len(payload)

    prepared = await _prepare(protocol, upload)

    assert (
        await _content_bytes(prepared.contents[1])
        == "[PAGE 1]\nå\n\n[PAGE 2]\nå".encode()
    )


@pytest.mark.asyncio
async def test_pdf_wait_keeps_request_loop_responsive(protocol, tmp_path, monkeypatch):
    monkeypatch.setattr(
        TextExtractor, "_extract_pdf_in_child", staticmethod(_hanging_child)
    )
    protocol.text_extractor = TextExtractor()
    pdf = _write_pdf(tmp_path / "source.pdf", 1)
    payload = pdf.read_bytes()
    upload = UploadFile(
        file=BytesIO(payload),
        filename="source.pdf",
        headers={"content-type": "application/pdf"},
    )
    protocol.file_size_service.get_file_size.return_value = len(payload)
    ticks = 0
    finished = asyncio.Event()

    async def heartbeat():
        nonlocal ticks
        while not finished.is_set():
            ticks += 1
            await asyncio.sleep(0.02)

    pulse = asyncio.create_task(heartbeat())
    await asyncio.sleep(0)
    started = time.monotonic()
    try:
        with pytest.raises(PdfExtractionLimitExceeded) as caught:
            await _prepare(
                protocol, upload, pdf_limits=PdfExtractionLimits(10, 1024, 2)
            )
    finally:
        finished.set()
        await pulse

    assert caught.value.limit == "seconds"
    assert caught.value.ceiling == 2
    assert 2 <= time.monotonic() - started < 3.5
    assert ticks >= 20
    assert not (tmp_path / "uploaded").exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "uploaded.pid").read_text()), 0)


@pytest.mark.asyncio
async def test_cancelled_pdf_upload_kills_child_and_cleans_up(
    protocol, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        TextExtractor, "_extract_pdf_in_child", staticmethod(_hanging_child)
    )
    protocol.text_extractor = TextExtractor()
    payload = _write_pdf(tmp_path / "source.pdf", 1).read_bytes()
    upload = UploadFile(
        file=BytesIO(payload),
        filename="source.pdf",
        headers={"content-type": "application/pdf"},
    )
    protocol.file_size_service.get_file_size.return_value = len(payload)
    task = asyncio.create_task(
        _prepare(protocol, upload, pdf_limits=PdfExtractionLimits(10, 1024, 2))
    )
    pid_path = tmp_path / "uploaded.pid"
    try:
        async with asyncio.timeout(3):
            while not pid_path.exists():
                await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert not (tmp_path / "uploaded").exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_path.read_text()), 0)


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


async def _prepare_measured_audio(protocol, tmp_path, monkeypatch, *, decoded):
    upload = UploadFile(
        file=BytesIO(b"audio"),
        filename="meeting.webm",
        headers={"content-type": "audio/webm"},
    )
    protocol.file_size_service.get_file_size.return_value = 5
    path = tmp_path / "meeting.webm"

    async def save_original(_file):
        path.write_bytes(b"audio")
        return str(path)

    protocol.file_size_service.save_file_to_disk = save_original
    decodes: list[audio.AudioDecodeLimits] = []

    async def measure_duration(filepath, *, limits):
        decodes.append(limits)
        if isinstance(decoded, BaseException):
            raise decoded
        if callable(decoded):
            return await decoded()
        return decoded

    monkeypatch.setattr(audio, "measure_duration", measure_duration)
    limits = audio.AudioDecodeLimits(max_duration_seconds=300, max_decoded_bytes=10**12)
    async with protocol.prepare_upload(
        upload, upload_admission_snapshot=_UPLOAD_ADMISSION, audio_limits=limits
    ) as prepared:
        return prepared.audio_seconds, decodes


@pytest.mark.asyncio
async def test_audio_upload_keeps_its_decoded_length(protocol, tmp_path, monkeypatch):
    # Up to the limit itself: the length the run's transcription decodes.
    seconds, decodes = await _prepare_measured_audio(
        protocol, tmp_path, monkeypatch, decoded=300.0
    )

    assert seconds == 300.0
    assert [limits.max_duration_seconds for limits in decodes] == [300]


@pytest.mark.asyncio
async def test_audio_upload_past_the_limit_is_refused_before_it_is_kept(
    protocol, tmp_path, monkeypatch
):
    over = audio.AudioDecodeLimitExceeded(
        limit="duration_seconds", measured=300.02, ceiling=300
    )

    with pytest.raises(audio.AudioDecodeLimitExceeded):
        await _prepare_measured_audio(protocol, tmp_path, monkeypatch, decoded=over)


@pytest.mark.asyncio
async def test_audio_upload_that_does_not_decode_is_refused_as_unreadable(
    protocol, tmp_path, monkeypatch
):
    with pytest.raises(audio.AudioUnreadableError):
        await _prepare_measured_audio(
            protocol,
            tmp_path,
            monkeypatch,
            decoded=ValueError("Audio decoder exited with status 1"),
        )


@pytest.mark.asyncio
async def test_audio_measurement_past_its_deadline_is_refused_as_busy(
    protocol, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        audio, "_measurement_deadline_seconds", lambda: 0.01, raising=False
    )

    async def stall():
        await asyncio.sleep(10)

    with pytest.raises(audio.AudioMeasurementBusy):
        await _prepare_measured_audio(protocol, tmp_path, monkeypatch, decoded=stall)


@pytest.mark.asyncio
async def test_audio_measurements_wait_for_capacity_within_the_deadline(monkeypatch):
    running = 0
    peak = 0

    async def work():
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return 1.0

    monkeypatch.setattr(audio, "_MEASUREMENT_CAPACITY", asyncio.Semaphore(2))
    results = await asyncio.gather(*(audio.bounded_measurement(work) for _ in range(5)))

    assert results == [1.0] * 5
    assert peak == 2


@pytest.mark.asyncio
async def test_audio_whose_timestamps_run_short_is_held_to_its_decoded_length(
    protocol, tmp_path
):
    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg is not installed")
    # 4 s of Opus whose container timestamps say 2 s.
    source, squashed = tmp_path / "source.webm", tmp_path / "squashed.webm"
    for args in (
        ["-f", "lavfi", "-t", "4", "-i", "sine=frequency=300", "-c:a", "libopus"],
        ["-i", str(source), "-c", "copy", "-bsf:a", "setts=ts=TS/2"],
    ):
        target = source if "-f" in args else squashed
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", *args, str(target)], check=True
        )
    payload = squashed.read_bytes()
    upload = UploadFile(
        file=BytesIO(payload),
        filename="squashed.webm",
        headers={"content-type": "audio/webm"},
    )
    protocol.file_size_service.get_file_size.return_value = len(payload)

    async def save_original(_file):
        return str(squashed)

    protocol.file_size_service.save_file_to_disk = save_original

    with pytest.raises(audio.AudioDecodeLimitExceeded):
        async with protocol.prepare_upload(
            upload,
            upload_admission_snapshot=_UPLOAD_ADMISSION,
            audio_limits=audio.AudioDecodeLimits(
                max_duration_seconds=3, max_decoded_bytes=10**12
            ),
        ):
            pytest.fail("audio decoding past the limit is not prepared")


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
async def test_domain_limit_can_make_upload_admission_stricter(protocol):
    domain_maximum = 5_000_000
    upload, size = _make_upload("text/plain", domain_maximum + 1)
    protocol.file_size_service.get_file_size.return_value = size

    with pytest.raises(FileTooLargeException) as exc_info:
        async with protocol.prepare_upload(
            upload,
            upload_admission_snapshot=_UPLOAD_ADMISSION,
            max_size=domain_maximum,
            limit_name="flow_runtime_input",
        ):
            pass

    assert exc_info.value.max_size == domain_maximum
    assert exc_info.value.limit_name == "flow_runtime_input"


@pytest.mark.asyncio
async def test_domain_limit_cannot_relax_upload_admission(protocol):
    upload, size = _make_upload("text/plain", TEXT_MAX + 1)
    protocol.file_size_service.get_file_size.return_value = size

    with pytest.raises(FileTooLargeException) as exc_info:
        async with protocol.prepare_upload(
            upload,
            upload_admission_snapshot=_UPLOAD_ADMISSION,
            max_size=TEXT_MAX * 2,
            limit_name="flow_runtime_input",
        ):
            pass

    assert exc_info.value.max_size == TEXT_MAX
    assert exc_info.value.limit_name == "flow_runtime_input"


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
