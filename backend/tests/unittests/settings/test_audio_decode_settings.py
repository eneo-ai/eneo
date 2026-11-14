import pytest

from eneo.main.config import Settings, get_settings


@pytest.mark.parametrize(
    "field", ["flow_audio_max_duration_seconds", "flow_audio_max_decoded_bytes"]
)
@pytest.mark.parametrize("value", [0, -1])
def test_audio_decode_limits_must_be_positive(field, value):
    with pytest.raises(SystemExit):
        Settings.model_validate({**get_settings().model_dump(), field: value})


def test_no_environment_ceiling_stands_between_the_admin_and_the_decoder():
    assert "flow_audio_max_duration_ceiling_seconds" not in Settings.model_fields


@pytest.mark.parametrize(
    ("decoded_bytes", "ceiling"),
    [
        # The default 2 GiB of 16 kHz mono 16-bit audio: 18 h 38 min.
        (2 * 1024**3, 67_108),
        # 500 MiB: 16 384 s.
        (500 * 1024 * 1024, 16_384),
        # 3 GiB holds more than a day: 26 h fits.
        (3 * 1024**3, 100_663),
        # 8 GiB is more than one WAV file holds: its 32-bit size field caps
        # the decoded audio at 134 217 s.
        (8 * 1024**3, 134_217),
    ],
)
def test_the_admin_ceiling_is_what_the_decoder_holds(decoded_bytes, ceiling):
    from eneo.flows.flow_input_limits import audio_duration_ceiling_seconds

    settings = get_settings().model_copy(
        update={"flow_audio_max_decoded_bytes": decoded_bytes}
    )
    assert audio_duration_ceiling_seconds(settings) == ceiling


def test_the_default_ceiling_leaves_room_above_the_default_recording():
    from eneo.flows.flow_input_limits import audio_duration_ceiling_seconds

    settings = get_settings()
    assert (
        audio_duration_ceiling_seconds(settings)
        >= settings.flow_audio_max_duration_seconds
    )


def test_the_decoded_byte_bound_holds_at_least_a_minute():
    # 1 919 999 bytes of decoded audio hold under a minute.
    with pytest.raises(SystemExit):
        Settings.model_validate(
            {**get_settings().model_dump(), "flow_audio_max_decoded_bytes": 1_919_999}
        )
