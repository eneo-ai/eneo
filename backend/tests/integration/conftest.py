"""Integration test fixtures using testcontainers for PostgreSQL and Redis."""

import contextlib
import os
from pathlib import Path
from typing import AsyncGenerator, Generator

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from dependency_injector import providers
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from init_db import add_tenant_user
from intric.database.database import sessionmanager
from intric.main.config import Settings, reset_settings, set_settings
from intric.main.container.container import Container
from intric.server.main import get_application

# IMPORTANT: Configure environment variables BEFORE importing testcontainers
# Disable Ryuk (testcontainers cleanup container) in devcontainer environments
# Ryuk can have connection issues in nested Docker setups
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

# Configure Docker connection if not already set
if not os.getenv("DOCKER_HOST"):
    if os.path.exists("/var/run/docker.sock"):
        os.environ["DOCKER_HOST"] = "unix:///var/run/docker.sock"
    elif os.path.exists("/.dockerenv"):
        os.environ["DOCKER_HOST"] = "tcp://host.docker.internal:2375"

# Detect if we're in a devcontainer environment
# If POSTGRES_HOST is set to 'db', we're likely in the devcontainer
_IN_DEVCONTAINER = os.getenv("POSTGRES_HOST") == "db"
_TEST_NETWORK = "eneo" if _IN_DEVCONTAINER else None


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """Start a PostgreSQL container with pgvector extension for the test session."""

    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="integration_test_user",
        password="integration_test_password",
        dbname="integration_test_db",
    )

    # In devcontainer, use the same network; otherwise default bridge network
    if _TEST_NETWORK:
        postgres = postgres.with_kwargs(network=_TEST_NETWORK)

    with postgres:
        postgres.get_connection_url()
        yield postgres


@pytest.fixture(scope="session")
def redis_container() -> Generator[RedisContainer | None, None, None]:
    """Start a Redis container for the test session when not in devcontainer."""

    if _IN_DEVCONTAINER:
        yield None
    else:
        redis = RedisContainer(image="redis:7-alpine")
        with redis:
            yield redis


@pytest.fixture(scope="session")
def test_settings(
    postgres_container: PostgresContainer,
    redis_container: RedisContainer | None,
) -> Settings:
    """Create test settings using testcontainer connection strings."""

    if _IN_DEVCONTAINER:
        pg_host = postgres_container._container.name
        pg_port = 5432
        redis_host = "redis"
        redis_port = 6379
    else:
        pg_host = postgres_container.get_container_host_ip()
        pg_port = int(postgres_container.get_exposed_port(5432))
        redis_host = redis_container.get_container_host_ip() if redis_container else "localhost"
        redis_port = int(redis_container.get_exposed_port(6379)) if redis_container else 6379

    settings = Settings(
        postgres_user="integration_test_user",
        postgres_host=pg_host,
        postgres_password="integration_test_password",
        postgres_port=pg_port,
        postgres_db="integration_test_db",
        redis_host=redis_host,
        redis_port=redis_port,
        redis_db=1,
        upload_file_to_session_max_size=10_000_000,
        upload_image_to_session_max_size=5_000_000,
        upload_max_file_size=100_000_000,
        transcription_max_file_size=25_000_000,
        max_in_question=1000,
        api_prefix="/api/v1",
        api_key_length=32,
        api_key_header_name="X-API-Key",
        jwt_audience="test_audience",
        jwt_issuer="test_issuer",
        jwt_expiry_time=3600,
        jwt_algorithm="HS256",
        jwt_secret="test_secret_key_for_integration_tests",
        jwt_token_prefix="Bearer",
        url_signing_key="test_url_signing_key",
        using_access_management=False,
        using_iam=False,
        using_image_generation=False,
        using_crawl=False,
        openapi_only_mode=False,
        testing=True,
        dev=True,
    )

    return settings


@pytest.fixture(scope="session", autouse=True)
def override_settings_for_session(test_settings: Settings):
    """Override global settings for the entire test session."""

    reset_settings()
    set_settings(test_settings)

    import intric.server.dependencies.auth_definitions as auth_defs

    auth_defs.OAUTH2_SCHEME = auth_defs._get_oauth2_scheme()
    auth_defs.API_KEY_HEADER = auth_defs._get_api_key_header()

    yield

    reset_settings()


@pytest.fixture(scope="session")
async def setup_database(test_settings: Settings):
    """Initialize the database schema and seed test data."""

    backend_dir = Path(__file__).parent.parent.parent
    alembic_ini_path = backend_dir / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("sqlalchemy.url", test_settings.sync_database_url)

    testing_flag = os.environ.pop("TESTING", None)
    try:
        command.upgrade(alembic_cfg, "head")
    finally:
        if testing_flag is not None:
            os.environ["TESTING"] = testing_flag

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
        quota_limit=1_000_000,
        user_name="test_user",
        user_email="test@example.com",
        user_password="test_password",
    )
    conn.close()

    sessionmanager.init(test_settings.database_url)

    async with sessionmanager.session() as session:
        async with session.begin():
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    yield

    await sessionmanager.close()


@pytest.fixture(autouse=True)
async def cleanup_database(setup_database, test_settings: Settings):  # noqa: ARG001
    """Truncate all tables and reseed after each test for full isolation."""

    yield

    async with sessionmanager.session() as session:
        async with session.begin():
            result = await session.execute(
                text(
                    """
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = 'public' AND tablename != 'alembic_version'
                    """
                )
            )
            tables = result.scalars().all()
            for table in tables:
                await session.execute(
                    text(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE')
                )

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
        quota_limit=1_000_000,
        user_name="test_user",
        user_email="test@example.com",
        user_password="test_password",
    )
    conn.close()


@pytest.fixture
async def app(setup_database):  # noqa: ARG001
    """Create a FastAPI application instance with test settings."""

    application = get_application()

    from intric.server.dependencies.lifespan import startup

    await startup()

    yield application


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Create an async HTTP client for testing the FastAPI application."""

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client


@pytest.fixture
def db_session(setup_database):  # noqa: ARG001
    """Provide a context manager for database sessions with active transactions."""

    @contextlib.asynccontextmanager
    async def _session():
        async with sessionmanager.session() as session, session.begin():
            yield session

    return _session


@pytest.fixture
def db_container(setup_database):  # noqa: ARG001
    """Provide a container with database session, user, and tenant context."""

    @contextlib.asynccontextmanager
    async def _container(user=None, tenant=None):
        async with sessionmanager.session() as session, session.begin():
            temp_container = Container(session=providers.Object(session))

            if user is None:
                user_repo = temp_container.user_repo()
                user = await user_repo.get_user_by_email("test@example.com")

            if tenant is None:
                tenant_repo = temp_container.tenant_repo()
                tenants = await tenant_repo.get_all_tenants()
                tenant = tenants[0] if tenants else None

            container = Container(
                session=providers.Object(session),
                user=providers.Object(user),
                tenant=providers.Object(tenant),
            )
            yield container

    return _container


@pytest.fixture
async def admin_user(db_container):
    """Return the default admin user created during database setup."""

    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_email("test@example.com")
    return user


@pytest.fixture
async def admin_user_api_key(admin_user, db_container):
    """Create an API key for the admin user on demand."""

    async with db_container(user=admin_user) as container:
        auth_service = container.auth_service()
        api_key = await auth_service.create_user_api_key(
            prefix="test",
            user_id=admin_user.id,
            delete_old=True,
        )
    return api_key
