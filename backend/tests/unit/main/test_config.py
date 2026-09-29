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
