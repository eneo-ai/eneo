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


def test_a_chosen_service_is_in_use_whenever_the_flow_transcribes() -> None:
    # It times the words of every transcript, and labels speakers when asked.
    service_id = uuid4()
    wizard = {
        "transcription_enabled": True,
        "transcription_speaker_service": {"id": str(service_id)},
    }

    for labels in (True, False):
        config = parse_transcription_config(
            {"wizard": {**wizard, "transcription_diarization": labels}}
        )
        assert config.service_in_use == service_id
    config = parse_transcription_config(
        {"wizard": {**wizard, "transcription_enabled": False}}
    )
    assert config.speaker_service_id == service_id
    assert config.service_in_use is None


@pytest.mark.parametrize("raw", [None, {"id": None}, {"id": " "}])
def test_a_choice_of_no_service_names_none(raw: object) -> None:
    config = parse_transcription_config(
        {
            "wizard": {
                "transcription_enabled": True,
                "transcription_speaker_service": raw,
            }
        }
    )

    assert (config.speaker_service_id, config.service_in_use) == (None, None)


@pytest.mark.parametrize("raw", ["service", {"id": "not-a-uuid"}])
def test_a_malformed_speaker_service_reference_is_refused(raw: object) -> None:
    with pytest.raises(FlowTranscriptionConfigError):
        parse_transcription_config({"wizard": {"transcription_speaker_service": raw}})


def test_the_flow_may_set_a_speaker_bound_or_leave_it_automatic() -> None:
    def parse(raw: object):
        wizard: dict[str, object] = {"transcription_enabled": True}
        if raw is not None:
            wizard["transcription_max_speakers"] = raw
        return parse_transcription_config({"wizard": wizard})

    assert parse(4).max_speakers == 4
    assert parse(None).max_speakers is None


@pytest.mark.parametrize("raw", [0, -2, True, "3", 2.5])
def test_a_speaker_bound_must_be_a_whole_number_of_at_least_one(raw: object) -> None:
    with pytest.raises(FlowTranscriptionConfigError):
        parse_transcription_config({"wizard": {"transcription_max_speakers": raw}})
