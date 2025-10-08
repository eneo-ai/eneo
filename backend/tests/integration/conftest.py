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
from typing import AsyncGenerator, Generator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from intric.database.database import sessionmanager
from intric.main.config import Settings, reset_settings, set_settings
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
def redis_container() -> Generator[RedisContainer, None, None]:
    """
    Start a Redis container for the test session.
    """
    redis = RedisContainer(image="redis:7-alpine")

    # In devcontainer, use the same network; otherwise use default bridge network
    if _TEST_NETWORK:
        redis = redis.with_kwargs(network=_TEST_NETWORK)

    with redis:
        yield redis


@pytest.fixture(scope="session")
def test_settings(
    postgres_container: PostgresContainer,
    # redis_container: RedisContainer,
) -> Settings:
    """
    Create test settings using testcontainer connection strings.
    """
    # In devcontainer: use container name and internal port (same network)
    # Outside devcontainer: use host IP and exposed port (bridge network)
    if _IN_DEVCONTAINER:
        pg_host = postgres_container._container.name
        pg_port = 5432
        # redis_host = redis_container._container.name
        # redis_port = 6379
        redis_host = "localhost"
        redis_port = 6379
    else:
        pg_host = postgres_container.get_container_host_ip()
        pg_port = int(postgres_container.get_exposed_port(5432))
        # redis_host = redis_container.get_container_host_ip()
        # redis_port = int(redis_container.get_exposed_port(6379))
        redis_host = "localhost"
        redis_port = 6379

    # Create test settings
    settings = Settings(
        # PostgreSQL settings
        postgres_user="integration_test_user",
        postgres_host=pg_host,
        postgres_password="integration_test_password",
        postgres_port=pg_port,
        postgres_db="integration_test_db",

        # Redis settings
        redis_host=redis_host,
        redis_port=redis_port,

        # File upload limits
        upload_file_to_session_max_size=10_000_000,
        upload_image_to_session_max_size=5_000_000,
        upload_max_file_size=100_000_000,
        transcription_max_file_size=25_000_000,
        max_in_question=1000,

        # API settings
        api_prefix="/api",
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

        # OpenAPI mode (skip some startup dependencies)
        openapi_only_mode=True,

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

    yield

    # Cleanup after all tests
    reset_settings()


@pytest.fixture(scope="session")
async def setup_database(test_settings: Settings):
    """
    Initialize the database schema.
    For now, this just ensures the database is accessible.
    Later we'll add migrations and seed data.
    """
    # Initialize the database session manager with test settings
    sessionmanager.init(test_settings.database_url)

    # Test that we can connect
    async with sessionmanager.session() as session:
        async with session.begin():
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1

    yield

    # Cleanup
    await sessionmanager.close()


@pytest.fixture
async def app(setup_database):
    """
    Create a FastAPI application instance with test settings.
    """
    application = get_application()
    yield application


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """
    Create an async HTTP client for testing the FastAPI application.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
def anyio_backend():
    """Configure anyio backend for async tests."""
    return "asyncio"
