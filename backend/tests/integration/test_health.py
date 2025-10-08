"""
Basic integration tests to verify the test infrastructure works.
"""
import pytest

from intric.main.config import get_settings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_settings_are_overridden():
    """Verify that test settings are being used."""
    settings = get_settings()

    # Check that we're using test database
    assert settings.postgres_user == "integration_test_user"
    assert settings.postgres_db == "integration_test_db"
    assert settings.testing is True
    assert "integration_test" in settings.database_url.lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_database_connection(setup_database):
    """Verify we can connect to the test database."""
    from intric.database.database import sessionmanager
    from sqlalchemy import text

    async with sessionmanager.session() as session:
        async with session.begin():
            # Test basic query
            result = await session.execute(text("SELECT version()"))
            version = result.scalar()
            assert version is not None
            assert "PostgreSQL" in version

            # Test that pgvector extension can be enabled
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

            # Verify extension is installed
            result = await session.execute(
                text("SELECT * FROM pg_extension WHERE extname = 'vector'")
            )
            extension = result.first()
            assert extension is not None

@pytest.mark.integration
@pytest.mark.asyncio
async def test_app_initialization(app):
    """Test that the FastAPI app initializes correctly with test settings."""
    # Check that the app was created
    assert app is not None

    # Check that routes are registered
    routes = [route.path for route in app.routes]
    print(routes)
    assert "/api/healthz" in routes

    # Verify settings are accessible
    settings = get_settings()
    assert settings.api_prefix == "/api"

