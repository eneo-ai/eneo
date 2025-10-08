"""
Basic integration tests to verify the test infrastructure works.
"""
import pytest
from sqlalchemy import text

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
async def test_database_connection(db_session):
    """Verify we can connect to the test database."""
    async with db_session() as session:
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

    assert "/api/healthz" in routes

    # Verify settings are accessible
    settings = get_settings()
    assert settings.api_prefix == "/api/v1"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_and_users_exist(db_container):
    """Test that tenants and users exist in the database using repository services."""
    async with db_container() as container:
        # Check that at least one tenant exists
        tenant_repo = container.tenant_repo()
        tenants = await tenant_repo.get_all_tenants()
        assert len(tenants) > 0, "No tenants found in database"

        # Check that at least one user exists
        user_repo = container.user_repo()
        users = await user_repo.get_all_users()
        assert len(users) > 0, "No users found in database"

        # Verify user has a tenant relationship
        first_user = users[0]
        assert first_user.tenant_id is not None
        assert first_user.tenant is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticated_user_request(client, admin_user, admin_user_api_key):
    """
    Test that an authenticated user can access /api/users/me endpoint.

    This test demonstrates the use of fixtures:
    - admin_user: The default test user (test@example.com)
    - admin_user_api_key: A fresh API key for the admin user
    """
    # Make authenticated request to /api/users/me
    response = await client.get(
        "/api/v1/users/me/",
        headers={"X-API-Key": admin_user_api_key.key}
    )

    # Verify response
    assert response.status_code == 200
    user_data = response.json()
    assert user_data["email"] == admin_user.email
    assert user_data["username"] == admin_user.username
    assert user_data["id"] == str(admin_user.id)
    assert "predefined_roles" in user_data
    assert len(user_data["predefined_roles"]) > 0

