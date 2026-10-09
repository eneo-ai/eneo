from __future__ import annotations

from uuid import uuid4

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


def test_a_picked_speaker_service_is_used_only_while_speakers_are_labelled() -> None:
    service_id = uuid4()
    wizard = {
        "transcription_enabled": True,
        "transcription_speaker_service": {"id": str(service_id)},
    }

    assert parse_transcription_config({"wizard": wizard}).speaker_service_in_use == (
        service_id
    )
    for switched_off in (
        {**wizard, "transcription_diarization": False},
        {**wizard, "transcription_enabled": False},
    ):
        config = parse_transcription_config({"wizard": switched_off})
        assert config.speaker_service_id == service_id
        assert config.speaker_service_in_use is None


def test_no_pick_means_the_spaces_only_speaker_service() -> None:
    config = parse_transcription_config({"wizard": {"transcription_enabled": True}})

    assert config.speaker_service_id is None
    assert config.labels_with_the_spaces_service
    assert not parse_transcription_config(
        {"wizard": {"transcription_enabled": True, "transcription_diarization": False}}
    ).labels_with_the_spaces_service


@pytest.mark.parametrize("raw", ["service", {"id": "not-a-uuid"}])
def test_a_malformed_speaker_service_reference_is_refused(raw: object) -> None:
    with pytest.raises(FlowTranscriptionConfigError):
        parse_transcription_config({"wizard": {"transcription_speaker_service": raw}})
