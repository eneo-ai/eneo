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
    assert settings.api_prefix == "/api/v1"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_and_users_exist(setup_database):
    """Test that tenants and users exist in the database."""
    from intric.database.database import sessionmanager
    from intric.database.tables.tenant_table import Tenants
    from intric.database.tables.users_table import Users
    from sqlalchemy import select

    async with sessionmanager.session() as session:
        async with session.begin():
            # Check that at least one tenant exists
            result = await session.execute(select(Tenants))
            tenants = result.scalars().all()
            assert len(tenants) > 0, "No tenants found in database"

            # Check that at least one user exists
            result = await session.execute(select(Users))
            users = result.scalars().all()
            assert len(users) > 0, "No users found in database"

            # Verify user has a tenant relationship
            first_user = users[0]
            assert first_user.tenant_id is not None
            assert first_user.tenant is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticated_user_request(client, setup_database):
    """Test that an authenticated user can access /api/users/me endpoint."""
    from dependency_injector import providers
    from intric.database.database import sessionmanager
    from intric.database.tables.users_table import Users
    from intric.main.container.container import Container
    from sqlalchemy import select

    # We know the test user email from the seed data
    test_user_email = "test@example.com"

    # Create API key for the test user using the container
    async with sessionmanager.session() as session:
        async with session.begin():
            # Get test user id
            result = await session.execute(
                select(Users.id).where(Users.email == test_user_email)
            )
            test_user_id = result.scalar_one()

            # Create container with session
            container = Container(session=providers.Object(session))

            # Use auth service from container to create API key
            auth_service = container.auth_service()
            api_key_created = await auth_service.create_user_api_key(
                prefix="test",
                user_id=test_user_id,
                delete_old=True
            )

            # Commit the transaction explicitly before making the HTTP request
            await session.commit()

    # Make authenticated request to /api/users/me
    response = await client.get(
        "/api/v1/users/me/",
        headers={"X-API-Key": api_key_created.key}
    )

    # Verify response
    assert response.status_code == 200
    user_data = response.json()
    assert user_data["email"] == "test@example.com"
    assert user_data["username"] == "test_user"
    assert user_data["id"] is not None
    assert "predefined_roles" in user_data
    assert len(user_data["predefined_roles"]) > 0

