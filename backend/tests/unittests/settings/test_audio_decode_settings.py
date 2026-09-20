import pytest

from eneo.main.config import Settings, get_settings


@pytest.mark.parametrize(
    "field", ["flow_audio_max_duration_seconds", "flow_audio_max_decoded_bytes"]
)
@pytest.mark.parametrize("value", [0, -1])
def test_audio_decode_limits_must_be_positive(field, value):
    with pytest.raises(SystemExit):
        Settings.model_validate({**get_settings().model_dump(), field: value})
