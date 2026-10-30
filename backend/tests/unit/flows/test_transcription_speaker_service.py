"""A flow's speakers are labelled only by the service its author chose."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from eneo.flows.transcription_config import (
    SpeakerServiceGap,
    parse_transcription_config,
    resolve_speaker_service,
)
from tests.unittests.spaces.test_space_transcription_services import (
    _connection,
    _space,
)


def _config(pick: UUID | None = None, *, labels: bool = True):
    wizard: dict[str, object] = {
        "transcription_enabled": True,
        "transcription_diarization": labels,
    }
    if pick is not None:
        wizard["transcription_speaker_service"] = {"id": str(pick)}
    return parse_transcription_config({"wizard": wizard})


def test_the_chosen_service_labels_the_speakers_whether_or_not_labels_are_on() -> None:
    other, chosen = _connection(3), _connection(3)
    space = _space(None, [other, chosen])

    for labels in (True, False):
        resolution = resolve_speaker_service(_config(chosen.id, labels=labels), space)

        assert (resolution.connection, resolution.gap) == (chosen, None)
        assert resolution.available


@pytest.mark.parametrize(
    "chosen",
    [None, _connection(3, enabled=False)],
    ids=["not_granted", "switched_off"],
)
def test_nothing_stands_in_for_a_chosen_service_the_space_cannot_use(chosen) -> None:
    usable = _connection(3)
    space = _space(None, [usable] if chosen is None else [usable, chosen])

    resolution = resolve_speaker_service(
        _config(uuid4() if chosen is None else chosen.id), space
    )

    assert (resolution.connection, resolution.gap) == (
        None,
        SpeakerServiceGap.PICKED_UNAVAILABLE,
    )
    assert not resolution.available


@pytest.mark.parametrize("usable_services", [0, 1, 3])
def test_nothing_is_chosen_for_a_flow_that_chose_no_service(
    usable_services: int,
) -> None:
    space = _space(None, [_connection(3) for _ in range(usable_services)])

    resolution = resolve_speaker_service(_config(), space)

    assert (resolution.connection, resolution.gap) == (
        None,
        SpeakerServiceGap.NOT_CHOSEN,
    )


def test_a_speaker_service_gap_is_one_of_two_reasons() -> None:
    assert {gap.value for gap in SpeakerServiceGap} == {
        "not_chosen",
        "picked_unavailable",
    }
