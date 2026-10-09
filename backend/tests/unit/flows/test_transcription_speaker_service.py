from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.flows.transcription_config import (
    SpeakerServiceGap,
    parse_transcription_config,
    resolve_speaker_service,
)


def _space(*connections: SimpleNamespace) -> SimpleNamespace:
    by_id = {connection.id: connection for connection in connections}
    return SimpleNamespace(
        usable_transcription_service=by_id.get,
        usable_transcription_services=list(connections),
    )


def _config(pick: object = None, *, labels: bool = True):
    wizard: dict[str, object] = {
        "transcription_enabled": True,
        "transcription_diarization": labels,
    }
    if pick is not None:
        wizard["transcription_speaker_service"] = {"id": str(pick)}
    return parse_transcription_config({"wizard": wizard})


@pytest.mark.parametrize(
    ("count", "gap"),
    [(0, SpeakerServiceGap.NO_SERVICE), (2, SpeakerServiceGap.CHOICE_REQUIRED)],
)
def test_without_a_pick_the_space_needs_exactly_one_service(
    count: int, gap: SpeakerServiceGap
) -> None:
    space = _space(*(SimpleNamespace(id=uuid4()) for _ in range(count)))

    resolution = resolve_speaker_service(_config(), space)  # pyright: ignore[reportArgumentType]

    assert (resolution.connection, resolution.gap) == (None, gap)


def test_the_spaces_only_service_labels_speakers_even_when_labels_are_off() -> None:
    only = SimpleNamespace(id=uuid4())

    resolution = resolve_speaker_service(_config(labels=False), _space(only))  # pyright: ignore[reportArgumentType]

    assert resolution.connection is only
    assert resolution.available


def test_a_pick_wins_over_the_spaces_services_and_must_be_usable() -> None:
    picked, other = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())

    chosen = resolve_speaker_service(_config(picked.id), _space(picked, other))  # pyright: ignore[reportArgumentType]
    revoked = resolve_speaker_service(_config(picked.id), _space(other))  # pyright: ignore[reportArgumentType]

    assert chosen.connection is picked
    assert (revoked.connection, revoked.gap) == (
        None,
        SpeakerServiceGap.PICKED_UNAVAILABLE,
    )
