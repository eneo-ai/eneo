"""
Test to validate that settings can be properly mocked and overridden for integration tests.
"""

import logging

import pytest

from intric.main.config import Settings, get_settings, reset_settings, set_settings


def test_settings_lazy_initialization():
    """Test that settings are lazily initialized."""
    # Reset to start fresh
    reset_settings()

    # First call should create settings
    settings1 = get_settings()
    assert settings1 is not None

    # Second call should return the same instance
    settings2 = get_settings()
    assert settings1 is settings2


def test_settings_can_be_overridden():
    """Test that settings can be overridden for testing."""
    # Reset to start fresh
    reset_settings()

    # Create custom test settings with specific values
    test_settings = Settings(
        postgres_user="test_user",
        postgres_host="test_host",
        postgres_password="test_password",
        postgres_port=5432,
        postgres_db="test_db",
        redis_host="test_redis",
        redis_port=6379,
        upload_file_to_session_max_size=1000,
        upload_image_to_session_max_size=500,
        upload_max_file_size=2000,
        transcription_max_file_size=1500,
        api_prefix="/api",
        api_key_length=32,
        api_key_header_name="X-API-Key",
        jwt_audience="test_audience",
        jwt_issuer="test_issuer",
        jwt_expiry_time=3600,
        jwt_algorithm="HS256",
        jwt_secret="test_secret",
        jwt_token_prefix="Bearer",
        url_signing_key="test_signing_key",
    )

    # Override with test settings
    set_settings(test_settings)

    # Verify the override worked
    current_settings = get_settings()
    assert current_settings is test_settings
    assert current_settings.postgres_host == "test_host"
    assert current_settings.postgres_user == "test_user"
    assert current_settings.redis_host == "test_redis"

    # Verify computed fields work
    assert "test_user" in current_settings.database_url
    assert "test_host" in current_settings.database_url
    assert "test_db" in current_settings.database_url


def test_settings_reset():
    """Test that settings can be reset."""
    # Set custom settings
    test_settings = Settings(
        postgres_user="test",
        postgres_host="test",
        postgres_password="test",
        postgres_port=5432,
        postgres_db="test",
        redis_host="test",
        redis_port=6379,
        upload_file_to_session_max_size=1000,
        upload_image_to_session_max_size=500,
        upload_max_file_size=2000,
        transcription_max_file_size=1500,
        api_prefix="/api",
        api_key_length=32,
        api_key_header_name="X-API-Key",
        jwt_audience="test",
        jwt_issuer="test",
        jwt_expiry_time=3600,
        jwt_algorithm="HS256",
        jwt_secret="test",
        jwt_token_prefix="Bearer",
        url_signing_key="test",
    )
    set_settings(test_settings)

    # Verify it's set
    assert get_settings() is test_settings

    # Reset
    reset_settings()

    # Next call should create a new instance from environment
    new_settings = get_settings()
    assert new_settings is not test_settings


def test_settings_database_url_construction():
    """Test that database URL is properly constructed from parts."""
    reset_settings()

    test_settings = Settings(
        postgres_user="myuser",
        postgres_host="myhost",
        postgres_password="mypassword",
        postgres_port=5433,
        postgres_db="mydb",
        redis_host="redis",
        redis_port=6379,
        upload_file_to_session_max_size=1000,
        upload_image_to_session_max_size=500,
        upload_max_file_size=2000,
        transcription_max_file_size=1500,
        api_prefix="/api",
        api_key_length=32,
        api_key_header_name="X-API-Key",
        jwt_audience="test",
        jwt_issuer="test",
        jwt_expiry_time=3600,
        jwt_algorithm="HS256",
        jwt_secret="test",
        jwt_token_prefix="Bearer",
        url_signing_key="test",
    )
    set_settings(test_settings)

    settings = get_settings()

    # Test async database URL
    assert (
        settings.database_url
        == "postgresql+asyncpg://myuser:mypassword@myhost:5433/mydb"
    )

    # Test sync database URL
    assert (
        settings.sync_database_url == "postgresql://myuser:mypassword@myhost:5433/mydb"
    )


def _set_minimal_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "POSTGRES_USER": "test",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PASSWORD": "test",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "test",
        "REDIS_HOST": "localhost",
        "REDIS_PORT": "6379",
        "UPLOAD_FILE_TO_SESSION_MAX_SIZE": "1000",
        "UPLOAD_IMAGE_TO_SESSION_MAX_SIZE": "500",
        "UPLOAD_MAX_FILE_SIZE": "2000",
        "TRANSCRIPTION_MAX_FILE_SIZE": "1500",
        "MAX_IN_QUESTION": "100",
        "API_PREFIX": "/api",
        "API_KEY_LENGTH": "32",
        "API_KEY_HEADER_NAME": "X-API-Key",
        "JWT_AUDIENCE": "test",
        "JWT_ISSUER": "test",
        "JWT_EXPIRY_TIME": "3600",
        "JWT_ALGORITHM": "HS256",
        "JWT_SECRET": "test-secret",
        "JWT_TOKEN_PREFIX": "Bearer",
        "URL_SIGNING_KEY": "test-signing-key",
        "ENCRYPTION_KEY": "yPIAaWTENh5knUuz75NYHblR3672X-7lH-W6AD4F1hs=",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_federation_enabled_env_takes_precedence(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    _set_minimal_settings_env(monkeypatch)
    monkeypatch.setenv("FEDERATION_ENABLED", "false")
    monkeypatch.setenv("FEDERATION_PER_TENANT_ENABLED", "true")

    with caplog.at_level(logging.WARNING):
        settings = Settings(_env_file=None)

    assert settings.federation_enabled is False
    assert settings.federation_per_tenant_enabled is True
    assert "Using FEDERATION_ENABLED" in caplog.text


def test_deprecated_federation_flag_falls_back_when_primary_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    _set_minimal_settings_env(monkeypatch)
    monkeypatch.delenv("FEDERATION_ENABLED", raising=False)
    monkeypatch.setenv("FEDERATION_PER_TENANT_ENABLED", "true")

    with caplog.at_level(logging.WARNING):
        settings = Settings(_env_file=None)

    assert settings.federation_enabled is True
    assert "deprecated" in caplog.text


def test_matching_federation_flags_do_not_override_primary(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    _set_minimal_settings_env(monkeypatch)
    monkeypatch.setenv("FEDERATION_ENABLED", "true")
    monkeypatch.setenv("FEDERATION_PER_TENANT_ENABLED", "true")

    with caplog.at_level(logging.WARNING):
        settings = Settings(_env_file=None)

    assert settings.federation_enabled is True
    assert "different values" not in caplog.text
    assert "deprecated" in caplog.text


def test_primary_federation_flag_works_without_deprecated_alias(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    _set_minimal_settings_env(monkeypatch)
    monkeypatch.setenv("FEDERATION_ENABLED", "true")
    monkeypatch.delenv("FEDERATION_PER_TENANT_ENABLED", raising=False)

    with caplog.at_level(logging.WARNING):
        settings = Settings(_env_file=None)

    assert settings.federation_enabled is True
    assert "FEDERATION_PER_TENANT_ENABLED is deprecated" not in caplog.text


@pytest.fixture(autouse=True)
def cleanup_settings():
    """Automatically reset settings after each test."""
    yield
    reset_settings()
