"""Unit tests for the per-segment transcription header.

The runtime joins multiple audio file transcripts into a single block of
text. When the files were produced by the browser's segmented recorder
they share a session id and carry capture metadata in the filename, and
the join annotates each block with `## Del N — kl HH:MM:SS` so the LLM
(and humans reviewing the audit trail) can reason about long, paused
recordings. Anything that doesn't match the segment naming pattern
falls back to the unlabeled join — this preserves the existing
behaviour for single-shot uploads.
"""

from datetime import datetime, timezone

import pytest

from intric.flows.runtime.transcription import (
    _join_transcription_blocks,
    _parse_segment_filename,
    _parse_segment_iso,
)


def _meta(session: str, index: int, captured_at: datetime):
    return (session, index, captured_at)


def test_join_single_block_returns_text_unchanged() -> None:
    text = "hello world"
    result = _join_transcription_blocks([text], [None])
    assert result == "hello world"


def test_join_single_block_with_metadata_does_not_label_segment() -> None:
    captured_at = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)
    result = _join_transcription_blocks(
        ["lone segment"],
        [_meta("session-a", 0, captured_at)],
    )
    assert "## Del" not in result
    assert result == "lone segment"


def test_join_two_segments_same_session_includes_part_headers() -> None:
    captured_a = datetime(2026, 4, 30, 9, 0, 0, tzinfo=timezone.utc)
    captured_b = datetime(2026, 4, 30, 9, 22, 0, tzinfo=timezone.utc)
    result = _join_transcription_blocks(
        ["alpha", "beta"],
        [_meta("session-a", 0, captured_a), _meta("session-a", 1, captured_b)],
    )
    assert result.startswith("## Del 1 — kl 09:00:00")
    assert "## Del 2 — kl 09:22:00" in result
    assert "alpha" in result
    assert "beta" in result


def test_join_falls_back_when_metadata_missing_for_any_block() -> None:
    captured_a = datetime(2026, 4, 30, 9, 0, 0, tzinfo=timezone.utc)
    result = _join_transcription_blocks(
        ["alpha", "beta"],
        [_meta("session-a", 0, captured_a), None],
    )
    assert "## Del" not in result
    assert result == "alpha\n\nbeta"


def test_join_falls_back_when_segments_belong_to_different_sessions() -> None:
    captured_a = datetime(2026, 4, 30, 9, 0, 0, tzinfo=timezone.utc)
    captured_b = datetime(2026, 4, 30, 9, 22, 0, tzinfo=timezone.utc)
    result = _join_transcription_blocks(
        ["alpha", "beta"],
        [_meta("session-a", 0, captured_a), _meta("session-b", 0, captured_b)],
    )
    assert "## Del" not in result
    assert result == "alpha\n\nbeta"


def test_parse_segment_filename_extracts_session_index_and_time() -> None:
    parsed = _parse_segment_filename(
        "recording-abcdef00-0000-0000-0000-000000000000-seg03-2026-04-30T12-30-15Z.webm"
    )
    assert parsed is not None
    session, index, captured_at = parsed
    assert session == "abcdef00-0000-0000-0000-000000000000"
    assert index == 3
    assert captured_at == datetime(2026, 4, 30, 12, 30, 15, tzinfo=timezone.utc)


def test_parse_segment_filename_returns_none_for_unrelated_filename() -> None:
    assert _parse_segment_filename("just-a-recording.webm") is None
    assert _parse_segment_filename("") is None


@pytest.mark.parametrize(
    "iso, expected",
    [
        (
            "2026-04-30T12-30-15Z",
            datetime(2026, 4, 30, 12, 30, 15, tzinfo=timezone.utc),
        ),
        (
            "2026-04-30T12-30-15-123Z",
            datetime(2026, 4, 30, 12, 30, 15, 123000, tzinfo=timezone.utc),
        ),
    ],
)
def test_parse_segment_iso_handles_recorder_format(
    iso: str, expected: datetime
) -> None:
    parsed = _parse_segment_iso(iso)
    assert parsed == expected


def test_parse_segment_iso_returns_none_for_invalid_input() -> None:
    assert _parse_segment_iso("not-an-iso") is None
    assert _parse_segment_iso("2026-04-30T12-30Z") is None
