import pytest
from pydantic import ValidationError

from eneo.main.config import (
    JWT_EXPIRY_TIME_MAXIMUM_MINUTES,
    Settings,
    get_settings,
)


@pytest.mark.parametrize("minutes", [1, 60, 1440, JWT_EXPIRY_TIME_MAXIMUM_MINUTES])
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


@pytest.mark.parametrize("minutes", [JWT_EXPIRY_TIME_MAXIMUM_MINUTES + 1, 86400])
def test_jwt_expiry_time_rejects_values_beyond_thirty_days(minutes: int) -> None:
    # 86400 is the value earlier templates shipped when the unit was mislabelled
    # as seconds; it means 60 days and must be corrected, not reinterpreted.
    with pytest.raises(ValidationError, match="30 days"):
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


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_redis_credentials_mean_no_authentication(blank: str) -> None:
    settings = Settings.model_validate(
        {
            **get_settings().model_dump(),
            "redis_username": blank,
            "redis_password": blank,
        }
    )

    assert settings.redis_username is None
    assert settings.redis_password is None


def test_redis_username_requires_a_password() -> None:
    with pytest.raises(ValidationError, match="REDIS_USERNAME"):
        Settings.model_validate(
            {
                **get_settings().model_dump(),
                "redis_username": "eneo",
                "redis_password": None,
            }
        )


def test_get_settings_exits_with_a_readable_message(monkeypatch, caplog) -> None:
    from eneo.main import config

    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setenv("JWT_EXPIRY_TIME", "86400")

    with pytest.raises(SystemExit) as exc_info:
        with caplog.at_level("ERROR"):
            config.get_settings()

    assert exc_info.value.code == 1
    message = caplog.text
    assert "Eneo cannot start until its configuration is corrected" in message
    assert "  JWT_EXPIRY_TIME is the session lifetime in minutes" in message
    assert "86400" not in message
    assert "Traceback" not in message
