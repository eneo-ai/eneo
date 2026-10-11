"""Which speaker identification service labels a flow's speakers in its space."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from eneo.flows.transcription_config import (
    SpeakerServiceGap,
    parse_transcription_config,
    resolve_speaker_service,
)
from tests.unittests.spaces.test_space_transcription_services import (
    _classification,
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


def test_without_a_choice_the_flow_uses_the_first_service_the_space_was_given() -> None:
    first, second = _connection(3), _connection(3)

    resolution = resolve_speaker_service(_config(), _space(None, [first, second]))

    assert (resolution.connection, resolution.gap) == (first, None)
    assert resolution.available


@pytest.mark.parametrize(
    "first",
    [_connection(3, enabled=False), _connection(1)],
    ids=["switched_off", "below_classification"],
)
def test_the_next_service_takes_over_while_the_first_is_not_usable(first) -> None:
    second = _connection(3)
    space = _space(_classification(3), [first, second])

    assert resolve_speaker_service(_config(), space).connection == second


@pytest.mark.parametrize(
    ("granted", "gap"),
    [
        ([], SpeakerServiceGap.NO_SERVICE),
        ([_connection(3, enabled=False)], SpeakerServiceGap.NONE_USABLE),
        ([_connection(1)], SpeakerServiceGap.NONE_USABLE),
    ],
    ids=["nothing_granted", "switched_off", "below_classification"],
)
def test_without_a_usable_service_the_gap_says_whether_the_space_has_any(
    granted, gap: SpeakerServiceGap
) -> None:
    space = _space(_classification(3), granted)

    resolution = resolve_speaker_service(_config(), space)

    assert (resolution.connection, resolution.gap) == (None, gap)


def test_the_standard_labels_speakers_even_when_the_flows_labels_are_off() -> None:
    only = _connection(3)

    resolution = resolve_speaker_service(_config(labels=False), _space(None, [only]))

    assert resolution.connection == only


def test_a_choice_wins_over_the_standard_and_nothing_stands_in_for_it() -> None:
    standard, chosen = _connection(3), _connection(3)

    used = resolve_speaker_service(_config(chosen.id), _space(None, [standard, chosen]))
    revoked = resolve_speaker_service(_config(uuid4()), _space(None, [standard]))

    assert used.connection == chosen
    assert (revoked.connection, revoked.gap) == (
        None,
        SpeakerServiceGap.PICKED_UNAVAILABLE,
    )
