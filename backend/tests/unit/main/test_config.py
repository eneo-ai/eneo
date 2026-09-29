import pytest
from pydantic import ValidationError

from eneo.main.config import Settings, get_settings


@pytest.mark.parametrize("minutes", [1, 60, 1440])
def test_jwt_expiry_time_accepts_positive_minutes(minutes: int) -> None:
    settings = Settings.model_validate(
        {**get_settings().model_dump(), "jwt_expiry_time": minutes}
    )

    assert settings.jwt_expiry_time == minutes


@pytest.mark.parametrize("minutes", [0, -1])
def test_jwt_expiry_time_rejects_nonpositive_values(minutes: int) -> None:
    with pytest.raises(ValidationError, match="JWT_EXPIRY_TIME"):
        Settings.model_validate(
            {**get_settings().model_dump(), "jwt_expiry_time": minutes}
        )


@pytest.mark.parametrize("key", ["", "   ", "short-key", "x" * 31])
def test_url_signing_key_rejects_blank_or_short_keys(key: str) -> None:
    with pytest.raises(ValidationError, match="URL_SIGNING_KEY") as exc_info:
        Settings.model_validate({**get_settings().model_dump(), "url_signing_key": key})

    if key.strip():
        assert key not in str(exc_info.value)


def test_url_signing_key_accepts_thirty_two_bytes() -> None:
    settings = Settings.model_validate(
        {**get_settings().model_dump(), "url_signing_key": "k" * 32}
    )

    assert settings.url_signing_key == "k" * 32


def test_settings_validation_errors_never_echo_values() -> None:
    secret = "a-secret-that-must-not-be-printed-anywhere"
    with pytest.raises(ValidationError) as exc_info:
        Settings.model_validate(
            {
                **get_settings().model_dump(),
                "jwt_secret": secret,
                "url_signing_key": "x",
            }
        )

    assert secret not in str(exc_info.value)
