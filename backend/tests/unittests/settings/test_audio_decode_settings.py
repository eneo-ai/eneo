import pytest

from eneo.main.config import Settings, get_settings


@pytest.mark.parametrize(
    "field", ["flow_audio_max_duration_seconds", "flow_audio_max_decoded_bytes"]
)
@pytest.mark.parametrize("value", [0, -1])
def test_audio_decode_limits_must_be_positive(field, value):
    with pytest.raises(SystemExit):
        Settings.model_validate({**get_settings().model_dump(), field: value})


@pytest.mark.parametrize("value", [0, -1])
def test_the_flow_audio_duration_ceiling_must_be_positive(value):
    with pytest.raises(SystemExit):
        Settings.model_validate(
            {
                **get_settings().model_dump(),
                "flow_audio_max_duration_ceiling_seconds": value,
            }
        )


def test_the_flow_audio_duration_ceiling_leaves_room_above_the_default():
    settings = get_settings()
    assert (
        settings.flow_audio_max_duration_ceiling_seconds
        >= settings.flow_audio_max_duration_seconds
    )


def test_the_flow_audio_duration_ceiling_stays_within_a_day():
    with pytest.raises(SystemExit):
        Settings.model_validate(
            {
                **get_settings().model_dump(),
                "flow_audio_max_duration_ceiling_seconds": 24 * 60 * 60 + 1,
            }
        )


def test_the_admin_ceiling_is_what_the_decoded_byte_bound_holds(monkeypatch):
    from eneo.flows.flow_input_limits import audio_duration_ceiling_seconds

    settings = get_settings().model_copy(
        update={
            "flow_audio_max_duration_ceiling_seconds": 28_800,
            # 500 MiB of 16 kHz mono 16-bit audio: 16 384 s.
            "flow_audio_max_decoded_bytes": 500 * 1024 * 1024,
        }
    )
    assert audio_duration_ceiling_seconds(settings) == 16_384


@pytest.mark.parametrize(
    "update",
    [
        {"flow_audio_max_duration_ceiling_seconds": 59},
        # 1 919 999 bytes of decoded audio hold under a minute.
        {"flow_audio_max_decoded_bytes": 1_919_999},
    ],
)
def test_the_flow_audio_ceiling_holds_at_least_a_minute(update):
    with pytest.raises(SystemExit):
        Settings.model_validate({**get_settings().model_dump(), **update})
