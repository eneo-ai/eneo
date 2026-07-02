from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.flows.runtime.transcription import transcribe_audio_input


def _frontend_segment_filename(
    session_id: str,
    segment_index: int,
    captured_at: datetime,
) -> str:
    iso = (
        captured_at.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
        .replace(":", "-")
        .replace(".", "-")
    )
    return f"recording-{session_id}-seg{segment_index:02d}-{iso}.webm"


def _audio_file(name: str, file_id: UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=file_id or uuid4(),
        name=name,
        mimetype="audio/webm",
        transcription=None,
    )


async def _transcribe(files: list[SimpleNamespace], blocks: list[str]):
    transcriber = SimpleNamespace(transcribe=AsyncMock(side_effect=blocks))
    model = SimpleNamespace(id=uuid4(), name="whisper-1", model_name="whisper-1")
    return await transcribe_audio_input(
        files=files,
        transcriber=transcriber,
        transcription_model=model,
        language="sv",
        step_order=1,
        max_files=10,
        max_inline_text_bytes=10_000,
    )


@pytest.mark.asyncio
async def test_segmented_recorder_files_get_part_headers() -> None:
    session_id = "abcdef00-0000-0000-0000-000000000000"
    files = [
        _audio_file(
            _frontend_segment_filename(
                session_id,
                0,
                datetime(2026, 4, 30, 9, 0, 0, tzinfo=timezone.utc),
            )
        ),
        _audio_file(
            _frontend_segment_filename(
                session_id,
                1,
                datetime(2026, 4, 30, 9, 22, 0, tzinfo=timezone.utc),
            )
        ),
    ]

    result = await _transcribe(files, ["alpha", "beta"])

    assert result.text == (
        "## Del 1 — kl 09:00:00\n\nalpha\n\n## Del 2 — kl 09:22:00\n\nbeta"
    )
    assert result.transcript_bytes == len(result.text.encode("utf-8"))


@pytest.mark.asyncio
async def test_single_segment_upload_stays_unlabelled() -> None:
    session_id = "abcdef00-0000-0000-0000-000000000000"
    files = [
        _audio_file(
            _frontend_segment_filename(
                session_id,
                0,
                datetime(2026, 4, 30, 9, 0, 0, tzinfo=timezone.utc),
            )
        )
    ]

    result = await _transcribe(files, ["alpha"])

    assert result.text == "alpha"


@pytest.mark.asyncio
async def test_mixed_or_unrelated_audio_files_fall_back_to_plain_join() -> None:
    files = [
        _audio_file(
            "recording-abcdef00-0000-0000-0000-000000000000-seg00-2026-04-30T09-00-00-000Z.webm"
        ),
        _audio_file("meeting-upload.webm"),
    ]

    result = await _transcribe(files, ["alpha", "beta"])

    assert result.text == "alpha\n\nbeta"


@pytest.mark.asyncio
async def test_different_segment_sessions_fall_back_to_plain_join() -> None:
    files = [
        _audio_file(
            "recording-abcdef00-0000-0000-0000-000000000000-seg00-2026-04-30T09-00-00-000Z.webm"
        ),
        _audio_file(
            "recording-bcdefa00-0000-0000-0000-000000000000-seg01-2026-04-30T09-22-00-000Z.webm"
        ),
    ]

    result = await _transcribe(files, ["alpha", "beta"])

    assert result.text == "alpha\n\nbeta"


@pytest.mark.asyncio
async def test_malformed_segment_timestamp_falls_back_to_plain_join() -> None:
    files = [
        _audio_file(
            "recording-abcdef00-0000-0000-0000-000000000000-seg00-2026-04-30T09-00-00-123-456Z.webm"
        ),
        _audio_file(
            "recording-abcdef00-0000-0000-0000-000000000000-seg01-2026-04-30T09-22-00-000Z.webm"
        ),
    ]

    result = await _transcribe(files, ["alpha", "beta"])

    assert result.text == "alpha\n\nbeta"
