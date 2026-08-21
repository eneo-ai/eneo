import pytest
from pydantic import ValidationError

from eneo.main.config import Settings

REQUIRED_SETTINGS = {
    "postgres_user": "user",
    "postgres_host": "localhost",
    "postgres_password": "password",
    "postgres_port": 5432,
    "postgres_db": "db",
    "redis_host": "localhost",
    "redis_port": 6379,
    "api_prefix": "/api/v1",
    "api_key_length": 32,
    "api_key_header_name": "X-API-Key",
    "jwt_audience": "test-audience",
    "jwt_issuer": "test-issuer",
    "jwt_expiry_time": 60,
    "jwt_algorithm": "HS256",
    "jwt_secret": "test-secret",
    "jwt_token_prefix": "Bearer",
    "url_signing_key": "test-key",
}

MODULE_AUTH_LIFETIME_SETTINGS = [
    "module_auth_ticket_ttl_seconds",
    "module_auth_token_expiry_minutes",
    "module_auth_max_session_hours",
]


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **REQUIRED_SETTINGS, **overrides)


class TestModuleAuthLifetimeSettings:
    """A lifetime typo must fail startup, not every module login at runtime."""

    @pytest.mark.parametrize("name", MODULE_AUTH_LIFETIME_SETTINGS)
    @pytest.mark.parametrize("value", [0, -1])
    def test_non_positive_lifetime_is_rejected_at_construction(self, name, value):
        with pytest.raises(ValidationError, match=name):
            make_settings(**{name: value})

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("module_auth_ticket_ttl_seconds", 60),
            ("module_auth_token_expiry_minutes", 30),
            ("module_auth_max_session_hours", 12),
        ],
    )
    def test_positive_override_stays_supported(self, name, value):
        assert getattr(make_settings(**{name: value}), name) == value
