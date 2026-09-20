import pytest

from eneo.main.config import Settings, get_settings


def test_audio_decode_limit_defaults():
    values = get_settings().model_dump()
    values.pop("flow_audio_max_duration_seconds", None)
    values.pop("flow_audio_max_decoded_bytes", None)
    settings = Settings.model_validate(values)

    assert settings.flow_audio_max_duration_seconds == 4 * 60 * 60
    assert settings.flow_audio_max_decoded_bytes == 2 * 1024 * 1024 * 1024


@pytest.mark.parametrize(
    "field", ["flow_audio_max_duration_seconds", "flow_audio_max_decoded_bytes"]
)
@pytest.mark.parametrize("value", [0, -1])
def test_audio_decode_limits_must_be_positive(field, value):
    with pytest.raises(SystemExit):
        Settings.model_validate({**get_settings().model_dump(), field: value})
