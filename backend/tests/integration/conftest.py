"""
Integration test fixtures using testcontainers for PostgreSQL and Redis.
"""
import os

# IMPORTANT: Configure environment variables BEFORE importing testcontainers
# Disable Ryuk (testcontainers cleanup container) in devcontainer environments
# Ryuk can have connection issues in nested Docker setups
os.environ["TESTCONTAINERS_RYUK_DISABLED"] = "true"

# Configure Docker connection if not already set
if not os.getenv("DOCKER_HOST"):
    if os.path.exists("/var/run/docker.sock"):
        os.environ["DOCKER_HOST"] = "unix:///var/run/docker.sock"
    elif os.path.exists("/.dockerenv"):
        os.environ["DOCKER_HOST"] = "tcp://host.docker.internal:2375"

import asyncio
import contextlib
from typing import AsyncGenerator, Generator

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from dependency_injector import providers
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer

from init_db import add_tenant_user
from intric.database.database import sessionmanager
from intric.main.config import Settings, reset_settings, set_settings
from intric.main.container.container import Container
from intric.server.main import get_application

# Detect if we're in a devcontainer environment
# If POSTGRES_HOST is set to 'db', we're likely in the devcontainer
_IN_DEVCONTAINER = os.getenv("POSTGRES_HOST") == "db"
_TEST_NETWORK = "eneo" if _IN_DEVCONTAINER else None


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """
    Start a PostgreSQL container with pgvector extension for the test session.
    """
    # Use postgres:16 with pgvector pre-installed
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="integration_test_user",
        password="integration_test_password",
        dbname="integration_test_db",
    )

    # In devcontainer, use the same network; otherwise use default bridge network
    if _TEST_NETWORK:
        postgres = postgres.with_kwargs(network=_TEST_NETWORK)

    with postgres:
        # Wait for container to be ready
        postgres.get_connection_url()
        yield postgres

@pytest.fixture(scope="session")
def test_settings(
    postgres_container: PostgresContainer,
    # redis_container: RedisContainer,  # Disabled for now - causing hangs
) -> Settings:
    """
    Create test settings using testcontainer connection strings.
    """
    # In devcontainer: use container name and internal port (same network)
    # Outside devcontainer: use host IP and exposed port (bridge network)
    if _IN_DEVCONTAINER:
        pg_host = postgres_container._container.name
        pg_port = 5432
    else:
        pg_host = postgres_container.get_container_host_ip()
        pg_port = int(postgres_container.get_exposed_port(5432))

    # Create test settings
    settings = Settings(
        # PostgreSQL settings
        postgres_user="integration_test_user",
        postgres_host=pg_host,
        postgres_password="integration_test_password",
        postgres_port=pg_port,
        postgres_db="integration_test_db",

        # Redis settings
        redis_host="redis",
        redis_port=6379,

        # File upload limits
        upload_file_to_session_max_size=10_000_000,
        upload_image_to_session_max_size=5_000_000,
        upload_max_file_size=100_000_000,
        transcription_max_file_size=25_000_000,
        max_in_question=1000,

        # API settings
        api_prefix="/api/v1",
        api_key_length=32,
        api_key_header_name="X-API-Key",

        # JWT settings
        jwt_audience="test_audience",
        jwt_issuer="test_issuer",
        jwt_expiry_time=3600,
        jwt_algorithm="HS256",
        jwt_secret="test_secret_key_for_integration_tests",
        jwt_token_prefix="Bearer",

        # Security
        url_signing_key="test_url_signing_key",

        # Feature flags
        using_access_management=False,
        using_iam=False,
        using_image_generation=False,
        using_crawl=False,

        # Note: Set to False for integration tests that need full app functionality
        openapi_only_mode=False,

        # Development
        testing=True,
        dev=True,
    )

    return settings


@pytest.fixture(scope="session", autouse=True)
def override_settings_for_session(test_settings: Settings):
    """
    Override global settings for the entire test session.
    This runs automatically before any tests.
    """
    # Reset any existing settings
    reset_settings()

    # Set test settings
    set_settings(test_settings)

    # Reinitialize auth definitions with new settings
    # This is needed because API_KEY_HEADER and OAUTH2_SCHEME are created at import time
    import intric.server.dependencies.auth_definitions as auth_defs
    auth_defs.OAUTH2_SCHEME = auth_defs._get_oauth2_scheme()
    auth_defs.API_KEY_HEADER = auth_defs._get_api_key_header()

    yield

    # Cleanup after all tests
    reset_settings()


@pytest.fixture(scope="session")
async def setup_database(test_settings: Settings):
    """
    Initialize the database schema and seed test data.
    Runs Alembic migrations and creates a default tenant/user using init_db logic.
    """
    # Run alembic migrations programmatically with test database URL
    alembic_cfg = Config("/workspace/backend/alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", test_settings.sync_database_url)

    try:
        command.upgrade(alembic_cfg, "head")
        print("Alembic migrations ran successfully.")
    except Exception as e:
        print(f"Error running alembic migrations: {e}")
        raise

    # Seed test tenant and user using init_db logic
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )

    add_tenant_user(
        conn,
        tenant_name="test_tenant",
        quota_limit=1000000,
        user_name="test_user",
        user_email="test@example.com",
        user_password="test_password",
    )

    conn.close()

    # Initialize the database session manager with test settings AFTER migrations
    sessionmanager.init(test_settings.database_url)

    # Test that we can connect
    async with sessionmanager.session() as session:
        async with session.begin():
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1

    yield

    # Cleanup
    await sessionmanager.close()


@pytest.fixture(autouse=True)
async def cleanup_database(setup_database, test_settings):  # noqa: ARG001
    """
    Automatically truncate all tables and reseed after each test for full isolation.

    Note: setup_database dependency ensures migrations run before cleanup is registered.
    """
    yield

    # Clean up after each test - truncate everything and reseed
    async with sessionmanager.session() as session:
        async with session.begin():
            # Truncate all tables except alembic_version
            result = await session.execute(text("""
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public' AND tablename != 'alembic_version'
            """))
            tables = result.scalars().all()

            for table in tables:
                await session.execute(text(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE'))

    # Reseed test tenant and user
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )

    add_tenant_user(
        conn,
        tenant_name="test_tenant",
        quota_limit=1000000,
        user_name="test_user",
        user_email="test@example.com",
        user_password="test_password",
    )

    conn.close()
    print("Cleaned up and reseeded test database")


@pytest.fixture
async def app(setup_database):
    """
    Create a FastAPI application instance with test settings.
    Note: sessionmanager is already initialized by setup_database,
    so the app lifespan will use the same connection.
    """
    # The app's lifespan will call sessionmanager.init() again, but since
    # sessionmanager is a singleton, it should use the same instance.
    # We DON'T use lifespan_context because it would close the sessionmanager
    # on exit, which we need for cleanup_database fixture.
    application = get_application()

    # Manually trigger startup only (not shutdown)
    # Import here because it needs to be after settings are configured
    from intric.server.dependencies.lifespan import startup
    await startup()

    yield application

    # Note: We skip shutdown() to keep sessionmanager open for cleanup


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """
    Create an async HTTP client for testing the FastAPI application.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


# Database session fixtures

@pytest.fixture
def db_session(setup_database):
    """
    Provide a context manager for database sessions with active transactions.

    Usage:
        async with db_session() as session:
            # use session here
    """
    @contextlib.asynccontextmanager
    async def _session():
        async with sessionmanager.session() as session, session.begin():
            yield session

    return _session


@pytest.fixture
def db_container(setup_database):
    """
    Provide a context manager for a database container with session.

    This is the preferred way to access services that need database access.
    The container comes pre-configured with a session in an active transaction.

    Usage:
        async with db_container() as container:
            user_repo = container.user_repo()
            user = await user_repo.get_user_by_email("test@example.com")
    """
    @contextlib.asynccontextmanager
    async def _container():
        async with sessionmanager.session() as session, session.begin():
            container = Container(session=providers.Object(session))
            yield container

    return _container


# User and authentication fixtures

@pytest.fixture
async def admin_user(db_container):
    """
    Get the default admin user created during database setup.
    This is the test@example.com user with full tenant access.
    """
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_email("test@example.com")
    return user


@pytest.fixture
async def admin_user_api_key(admin_user, db_container):
    """
    Create an API key for the admin user.
    This fixture creates a fresh API key for each test.
    """
    async with db_container() as container:
        auth_service = container.auth_service()
        api_key = await auth_service.create_user_api_key(
            prefix="test",
            user_id=admin_user.id,
            delete_old=True
        )
    return api_key
