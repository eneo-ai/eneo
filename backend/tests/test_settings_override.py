"""
Test to validate that settings can be properly mocked and overridden for integration tests.
"""
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
        max_in_question=100,
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
        max_in_question=100,
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
        max_in_question=100,
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
    assert settings.database_url == "postgresql+asyncpg://myuser:mypassword@myhost:5433/mydb"

    # Test sync database URL
    assert settings.sync_database_url == "postgresql://myuser:mypassword@myhost:5433/mydb"


@pytest.fixture(autouse=True)
def cleanup_settings():
    """Automatically reset settings after each test."""
    yield
    reset_settings()
