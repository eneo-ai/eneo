from __future__ import annotations

import pytest

from eneo.flows.transcription_config import (
    FlowTranscriptionConfigError,
    parse_transcription_config,
)


def test_diarization_defaults_on_when_absent() -> None:
    config = parse_transcription_config({"wizard": {"transcription_enabled": True}})

    assert config.diarization is True


def test_diarization_can_be_switched_off() -> None:
    config = parse_transcription_config(
        {"wizard": {"transcription_enabled": True, "transcription_diarization": False}}
    )

    assert config.diarization is False


@pytest.mark.parametrize("raw", ["false", 0, None])
def test_diarization_must_be_a_boolean(raw: object) -> None:
    with pytest.raises(FlowTranscriptionConfigError):
        parse_transcription_config({"wizard": {"transcription_diarization": raw}})
