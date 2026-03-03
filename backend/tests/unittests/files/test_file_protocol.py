"""Tests for FileProtocol type-specific size limits.

Verifies that each file type handler (text, image, audio) uses its own
configured max_size from settings when no explicit override is passed —
which is the normal path from FileService.save_file().
"""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile

from intric.files import file_protocol as file_protocol_module
from intric.files.file_protocol import FileProtocol
from intric.main.exceptions import FileTooLargeException

# ── Fake settings ────────────────────────────────────────────────────────

TEXT_MAX = 25_000_000  # 25 MB
IMAGE_MAX = 20_000_000  # 20 MB
AUDIO_MAX = 200_000_000  # 200 MB

_FAKE_SETTINGS = SimpleNamespace(
    upload_file_to_session_max_size=TEXT_MAX,
    upload_image_to_session_max_size=IMAGE_MAX,
    transcription_max_file_size=AUDIO_MAX,
    upload_tmp_dir=Path("/tmp"),
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    monkeypatch.setattr(file_protocol_module, "get_settings", lambda: _FAKE_SETTINGS)


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
    text_extractor.extract.return_value = "extracted text"

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
    upload = UploadFile(file=data, filename="test_file", headers={"content-type": content_type})
    return upload, size


# ── Tests: text files use TEXT_MAX ───────────────────────────────────────


@pytest.mark.asyncio
async def test_text_under_limit_accepted(protocol):
    upload, size = _make_upload("text/plain", TEXT_MAX - 1)
    protocol.file_size_service.get_file_size.return_value = size

    result = await protocol.to_domain(upload)

    assert result.file_type.value == "text"


@pytest.mark.asyncio
async def test_text_over_limit_rejected(protocol):
    upload, size = _make_upload("text/plain", TEXT_MAX + 1)
    protocol.file_size_service.get_file_size.return_value = size

    with pytest.raises(FileTooLargeException) as exc_info:
        await protocol.to_domain(upload)

    assert exc_info.value.max_size == TEXT_MAX
    assert exc_info.value.setting_name == "UPLOAD_FILE_TO_SESSION_MAX_SIZE"


# ── Tests: image files use IMAGE_MAX ─────────────────────────────────────


@pytest.mark.asyncio
async def test_image_under_limit_accepted(protocol):
    upload, size = _make_upload("image/png", IMAGE_MAX - 1)
    protocol.file_size_service.get_file_size.return_value = size

    result = await protocol.to_domain(upload)

    assert result.file_type.value == "image"


@pytest.mark.asyncio
async def test_image_over_limit_rejected(protocol):
    upload, size = _make_upload("image/png", IMAGE_MAX + 1)
    protocol.file_size_service.get_file_size.return_value = size

    with pytest.raises(FileTooLargeException) as exc_info:
        await protocol.to_domain(upload)

    assert exc_info.value.max_size == IMAGE_MAX
    assert exc_info.value.setting_name == "UPLOAD_IMAGE_TO_SESSION_MAX_SIZE"


# ── Tests: audio files use AUDIO_MAX (the 200 MB fix) ───────────────────


@pytest.mark.asyncio
async def test_audio_under_limit_accepted(protocol):
    """Audio files up to AUDIO_MAX (200 MB) should be accepted — this was the bug."""
    upload, size = _make_upload("audio/mpeg", AUDIO_MAX - 1)
    protocol.file_size_service.get_file_size.return_value = size

    result = await protocol.to_domain(upload)

    assert result.file_type.value == "audio"


@pytest.mark.asyncio
async def test_audio_over_limit_rejected(protocol):
    upload, size = _make_upload("audio/mpeg", AUDIO_MAX + 1)
    protocol.file_size_service.get_file_size.return_value = size

    with pytest.raises(FileTooLargeException) as exc_info:
        await protocol.to_domain(upload)

    assert exc_info.value.max_size == AUDIO_MAX
    assert exc_info.value.setting_name == "TRANSCRIPTION_MAX_FILE_SIZE"


@pytest.mark.asyncio
async def test_audio_50mb_accepted(protocol):
    """50 MB audio file — well within 200 MB limit, but would have failed with old 10 MB limit."""
    upload, size = _make_upload("audio/mpeg", 50_000_000)
    protocol.file_size_service.get_file_size.return_value = size

    result = await protocol.to_domain(upload)

    assert result.file_type.value == "audio"


# ── Tests: to_domain dispatches correctly without explicit max_size ──────


@pytest.mark.asyncio
async def test_to_domain_routes_audio_mime_types(protocol):
    """All audio MIME types should route through audio_to_domain."""
    for mime in ["audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg", "audio/webm", "video/webm"]:
        upload, size = _make_upload(mime, 1000)
        protocol.file_size_service.get_file_size.return_value = size

        result = await protocol.to_domain(upload)

        assert result.file_type.value == "audio", f"MIME {mime} should route to audio"


@pytest.mark.asyncio
async def test_to_domain_routes_image_mime_types(protocol):
    """Image MIME types should route through image_to_domain."""
    for mime in ["image/png", "image/jpeg"]:
        upload, size = _make_upload(mime, 1000)
        protocol.file_size_service.get_file_size.return_value = size

        result = await protocol.to_domain(upload)

        assert result.file_type.value == "image", f"MIME {mime} should route to image"


@pytest.mark.asyncio
async def test_to_domain_routes_text_mime_types(protocol):
    """Non-image, non-audio MIME types should route through text_to_domain."""
    for mime in ["text/plain", "application/pdf", "text/csv"]:
        upload, size = _make_upload(mime, 1000)
        protocol.file_size_service.get_file_size.return_value = size

        result = await protocol.to_domain(upload)

        assert result.file_type.value == "text", f"MIME {mime} should route to text"


# ── Test: each type has independent limits ───────────────────────────────


@pytest.mark.asyncio
async def test_audio_limit_is_independent_of_text_limit(protocol):
    """
    Regression test for the original bug: audio was limited by UPLOAD_MAX_FILE_SIZE (10 MB)
    instead of TRANSCRIPTION_MAX_FILE_SIZE (200 MB). A 15 MB audio file should succeed
    even though TEXT_MAX is 25 MB — the point is it uses AUDIO_MAX, not the old global limit.
    """
    upload, size = _make_upload("audio/mpeg", 15_000_000)
    protocol.file_size_service.get_file_size.return_value = size

    result = await protocol.to_domain(upload)

    assert result.file_type.value == "audio"
