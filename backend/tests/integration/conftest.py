"""
Integration test fixtures using testcontainers for PostgreSQL and Redis.
"""
import json
import os
from collections.abc import Callable
from pathlib import Path


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

# CRITICAL: Set placeholder environment variables for init_db.py Settings instantiation
# init_db.py instantiates Settings() at module import time, so these must be set first
# These placeholders will be overridden by test_settings fixture
# Values copied from .github/workflows/pr_build_test.yml
if not os.getenv("POSTGRES_USER"):
    os.environ["POSTGRES_USER"] = "placeholder"
if not os.getenv("POSTGRES_HOST"):
    os.environ["POSTGRES_HOST"] = "placeholder"
if not os.getenv("POSTGRES_PASSWORD"):
    os.environ["POSTGRES_PASSWORD"] = "placeholder"
if not os.getenv("POSTGRES_PORT"):
    os.environ["POSTGRES_PORT"] = "5432"
if not os.getenv("POSTGRES_DB"):
    os.environ["POSTGRES_DB"] = "placeholder"
if not os.getenv("REDIS_HOST"):
    os.environ["REDIS_HOST"] = "placeholder"
if not os.getenv("REDIS_PORT"):
    os.environ["REDIS_PORT"] = "6379"
if not os.getenv("UPLOAD_FILE_TO_SESSION_MAX_SIZE"):
    os.environ["UPLOAD_FILE_TO_SESSION_MAX_SIZE"] = "10485760"
if not os.getenv("UPLOAD_IMAGE_TO_SESSION_MAX_SIZE"):
    os.environ["UPLOAD_IMAGE_TO_SESSION_MAX_SIZE"] = "10485760"
if not os.getenv("UPLOAD_MAX_FILE_SIZE"):
    os.environ["UPLOAD_MAX_FILE_SIZE"] = "10485760"
if not os.getenv("TRANSCRIPTION_MAX_FILE_SIZE"):
    os.environ["TRANSCRIPTION_MAX_FILE_SIZE"] = "10485760"
if not os.getenv("MAX_IN_QUESTION"):
    os.environ["MAX_IN_QUESTION"] = "1"
if not os.getenv("API_PREFIX"):
    os.environ["API_PREFIX"] = "/api/v1"
if not os.getenv("API_KEY_LENGTH"):
    os.environ["API_KEY_LENGTH"] = "64"
if not os.getenv("API_KEY_HEADER_NAME"):
    os.environ["API_KEY_HEADER_NAME"] = "X-API-Key"
if not os.getenv("JWT_AUDIENCE"):
    os.environ["JWT_AUDIENCE"] = "test"
if not os.getenv("JWT_ISSUER"):
    os.environ["JWT_ISSUER"] = "test"
if not os.getenv("JWT_EXPIRY_TIME"):
    os.environ["JWT_EXPIRY_TIME"] = "3600"
if not os.getenv("JWT_ALGORITHM"):
    os.environ["JWT_ALGORITHM"] = "HS256"
if not os.getenv("JWT_SECRET"):
    os.environ["JWT_SECRET"] = "test_secret"
if not os.getenv("JWT_TOKEN_PREFIX"):
    os.environ["JWT_TOKEN_PREFIX"] = "Bearer"
if not os.getenv("URL_SIGNING_KEY"):
    os.environ["URL_SIGNING_KEY"] = "test_key"
if not os.getenv("ENCRYPTION_KEY"):
    os.environ["ENCRYPTION_KEY"] = "yPIAaWTENh5knUuz75NYHblR3672X-7lH-W6AD4F1hs="

# Crawler settings - ensure TTL > max_length to pass validation
# These must be set BEFORE importing any module that calls get_settings()
if not os.getenv("CRAWL_MAX_LENGTH"):
    os.environ["CRAWL_MAX_LENGTH"] = "1800"  # 30 minutes
if not os.getenv("TENANT_WORKER_SEMAPHORE_TTL_SECONDS"):
    os.environ["TENANT_WORKER_SEMAPHORE_TTL_SECONDS"] = "3600"  # 1 hour (must be > CRAWL_MAX_LENGTH)

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
from testcontainers.redis import RedisContainer

from cryptography.fernet import Fernet

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
def redis_container() -> Generator[RedisContainer | None, None, None]:
    """
    Start a Redis container for the test session (only when not in devcontainer).
    In devcontainer, we use the existing Redis service.
    """
    if _IN_DEVCONTAINER:
        # Don't create a container, use existing Redis service
        yield None
    else:
        # Create Redis container for local testing
        redis = RedisContainer(image="redis:7-alpine")
        with redis:
            yield redis


@pytest.fixture(scope="session")
def test_settings(
    postgres_container: PostgresContainer,
    redis_container: RedisContainer | None,
) -> Settings:
    """
    Create test settings using testcontainer connection strings.
    """
    # In devcontainer: use container name and internal port (same network)
    # Outside devcontainer: use host IP and exposed port (bridge network)
    if _IN_DEVCONTAINER:
        pg_host = postgres_container._container.name
        pg_port = 5432
        redis_host = "redis"  # Use existing Redis service in devcontainer
        redis_port = 6379
    else:
        pg_host = postgres_container.get_container_host_ip()
        pg_port = int(postgres_container.get_exposed_port(5432))
        redis_host = redis_container.get_container_host_ip()
        redis_port = int(redis_container.get_exposed_port(6379))

    encryption_key = Fernet.generate_key().decode()

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
        redis_db=1,  # Use database 1 for tests to avoid collisions with dev data

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
        intric_super_api_key="test-super-admin-key-for-integration-tests",

        # LLM API Keys - CRITICAL: Set to None to prevent reading from environment
        # Integration tests should NEVER use real API keys
        openai_api_key=None,
        anthropic_api_key=None,
        azure_api_key=None,
        berget_api_key=None,
        mistral_api_key=None,
        ovhcloud_api_key=None,
        vllm_api_key=None,

        # Feature flags
        using_access_management=False,
        using_iam=False,
        using_image_generation=False,
        using_crawl=False,
        tenant_credentials_enabled=False,  # Disable for integration tests (tests can override if needed)
        federation_per_tenant_enabled=True,

        # Note: Set to False for integration tests that need full app functionality
        openapi_only_mode=False,

        # Development
        testing=False,  # Integration tests have full isolation via testcontainers
        dev=True,

        # Encryption
        encryption_key=encryption_key,
    )

    return settings


@pytest.fixture
async def redis_client(test_settings: Settings):
    """Provide Redis client for integration tests."""
    import redis.asyncio as aioredis

    redis = aioredis.from_url(
        f"redis://{test_settings.redis_host}:{test_settings.redis_port}/{test_settings.redis_db}",
        encoding="utf-8",
        decode_responses=False,
    )

    try:
        yield redis
    finally:
        try:
            # Explicitly close client and connection pool
            await redis.aclose(close_connection_pool=True)
        except Exception:
            # Don't fail tests during cleanup
            pass


@pytest.fixture(autouse=True)
async def _force_gc_before_loop_closes():
    """Force garbage collection while event loop is alive.

    This prevents "Event loop is closed" errors from Redis connections
    that get garbage collected after the event loop shuts down.

    The Container creates singleton Redis clients via DI that outlive individual tests.
    By forcing GC before the loop closes, we ensure __del__ methods run while
    the loop can still process connection cleanup.

    This is a pragmatic solution that doesn't interfere with test behavior or DI lifecycle.
    """
    yield

    import asyncio
    import gc

    # Give pending callbacks a chance to run
    await asyncio.sleep(0)

    # Force garbage collection while loop is alive
    gc.collect()


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

    # Verify settings are correct
    print("\n=== Integration Test Setup Verification ===")
    print("✓ Test settings configured")
    print(f"  - Database: {test_settings.postgres_db}")
    print(f"  - User: {test_settings.postgres_user}")
    print(f"  - Testing mode: {test_settings.testing}")
    print(f"  - API prefix: {test_settings.api_prefix}")

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
    backend_dir = Path(__file__).parent.parent.parent
    alembic_ini_path = backend_dir / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
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

    # Verify database connection
    print("\n=== Database Verification ===")
    async with sessionmanager.session() as session:
        async with session.begin():
            # Test basic query
            result = await session.execute(text("SELECT version()"))
            version = result.scalar()
            assert version is not None
            assert "PostgreSQL" in version
            print(f"✓ Database connected: {version.split(',')[0]}")

            # Test pgvector extension
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            result = await session.execute(
                text("SELECT * FROM pg_extension WHERE extname = 'vector'")
            )
            extension = result.first()
            assert extension is not None
            print("✓ pgvector extension available")

            # Verify tenant and users exist
            from intric.main.container.container import Container
            container = Container(session=providers.Object(session))

            tenant_repo = container.tenant_repo()
            tenants = await tenant_repo.get_all_tenants()
            assert len(tenants) > 0
            print(f"✓ Test tenant created: {tenants[0].name}")

            user_repo = container.user_repo()
            users = await user_repo.get_all_users()
            assert len(users) > 0
            assert users[0].tenant_id is not None
            print(f"✓ Test user created: {users[0].email}")

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

    # Recreate using_templates feature flag (required for template tests)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO global_feature_flags (id, name, description, enabled, created_at, updated_at)
        VALUES (gen_random_uuid(), 'using_templates',
            'Enable tenant-scoped template management for Assistants and Apps',
            false, now(), now())
        ON CONFLICT (name) DO NOTHING
    """)
    conn.commit()
    cursor.close()

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

    # Verify app initialization
    print("\n=== Application Verification ===")
    print("✓ FastAPI app initialized")
    routes = [route.path for route in application.routes]
    assert "/api/healthz" in routes
    print(f"✓ Routes registered: {len(routes)} routes")
    print("✓ Ready for testing\n")

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
    The container comes pre-configured with a session, user, and tenant
    in an active transaction.

    Usage:
        # Default: uses admin user (test@example.com)
        async with db_container() as container:
            user_repo = container.user_repo()
            users = await user_repo.get_all_users()

        # With custom user:
        async with db_container(user=custom_user) as container:
            # Services now use custom_user instead of admin user
            service = container.some_service()

        # With custom user and tenant:
        async with db_container(user=custom_user, tenant=custom_tenant) as container:
            service = container.some_service()
    """
    @contextlib.asynccontextmanager
    async def _container(user=None, tenant=None):
        async with sessionmanager.session() as session, session.begin():
            # Create container with session first to fetch user and tenant if not provided
            temp_container = Container(session=providers.Object(session))

            # Fetch default user if not provided
            if user is None:
                user_repo = temp_container.user_repo()
                user = await user_repo.get_user_by_email("test@example.com")

            # Fetch default tenant if not provided
            if tenant is None:
                tenant_repo = temp_container.tenant_repo()
                tenants = await tenant_repo.get_all_tenants()
                tenant = tenants[0] if tenants else None

            # Create container with all dependencies
            container = Container(
                session=providers.Object(session),
                user=providers.Object(user),
                tenant=providers.Object(tenant),
            )
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


# Additional fixtures for tenant credentials E2E tests

@pytest.fixture
async def async_session(setup_database):
    """
    Provide async database session for tests.
    """
    async with sessionmanager.session() as session:
        async with session.begin():
            yield session


@pytest.fixture(autouse=True)
def clear_api_keys_for_all_tests(request, monkeypatch):
    """Auto-use fixture to ensure API keys are cleared for integration tests ONLY.

    CRITICAL: This ensures integration tests NEVER use real API keys from the environment.
    Only runs for tests marked with @pytest.mark.integration to avoid affecting unit tests.
    """
    # Skip if not an integration test
    if "integration" not in request.keywords:
        return

    for key in [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AZURE_API_KEY",
        "BERGET_API_KEY",
        "MISTRAL_API_KEY",
        "OVHCLOUD_API_KEY",
        "VLLM_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
async def test_tenant(db_container):
    """
    Get the default test tenant.
    """
    async with db_container() as container:
        tenant_repo = container.tenant_repo()
        tenants = await tenant_repo.get_all_tenants()
        if not tenants:
            raise ValueError("No test tenant found in database")
        return tenants[0]


@pytest.fixture
async def super_admin_token(test_settings):
    """
    Get the super admin API key for sysadmin endpoints.

    Sysadmin endpoints use authenticate_super_api_key which checks against
    settings.intric_super_api_key.
    """
    return test_settings.intric_super_api_key


@pytest.fixture
def legacy_credentials_mode(test_settings):
    """Temporarily disable strict tenant credentials mode for backward compatibility tests.

    This fixture allows specific tests to verify that tenants without custom credentials
    can fall back to global environment variables (legacy behavior).

    Unlike the broken approach of reloading modules (which breaks DI and auth),
    this uses the proper set_settings() API to override the global settings singleton.

    When applied to a test, it:
    1. Creates a copy of test_settings with tenant_credentials_enabled=False
    2. Overrides global settings using set_settings()
    3. Rebuilds encryption service to match new settings
    4. Automatically restores original settings and encryption service after the test

    Usage:
        def test_backward_compatibility(legacy_credentials_mode, ...):
            # Test runs with strict mode disabled
            pass
    """
    from intric.main.config import set_settings, get_settings
    from intric.main.container.container import Container
    from intric.settings.encryption_service import EncryptionService
    from dependency_injector import providers

    # Save original settings
    original_settings = get_settings()

    # Create modified settings with strict mode disabled
    legacy_settings = test_settings.model_copy(
        update={"tenant_credentials_enabled": False}
    )

    # Override global settings (this is what the app uses)
    set_settings(legacy_settings)

    # Reset and rebuild encryption service to match new settings
    # (Container's encryption service uses get_settings() which now returns legacy_settings)
    Container.encryption_service.reset_last_overriding()
    service = EncryptionService(legacy_settings.encryption_key)
    Container.encryption_service.override(providers.Object(service))

    yield

    # Restore original settings
    set_settings(original_settings)

    # Restore original encryption service
    Container.encryption_service.reset_last_overriding()
    original_service = EncryptionService(original_settings.encryption_key)
    Container.encryption_service.override(providers.Object(original_service))


@pytest.fixture(autouse=True)
def encryption_service(test_settings):
    """Provide EncryptionService configured with the test encryption key.

    Auto-used for all integration tests to ensure encryption is enabled,
    overriding the Container's default behavior of disabling encryption in testing mode.
    """
    from intric.main.container.container import Container
    from intric.settings.encryption_service import EncryptionService

    service = EncryptionService(test_settings.encryption_key)
    Container.encryption_service.override(providers.Object(service))
    try:
        yield service
    finally:
        Container.encryption_service.reset_last_overriding()


@pytest.fixture
def patch_auth_service_jwt(monkeypatch, test_settings):
    """Ensure AuthService uses the runtime test settings for JWT operations."""
    from datetime import datetime, timedelta, timezone

    import jwt as jwt_lib

    from intric.authentication.auth_models import JWTCreds, JWTMeta, JWTPayload
    from intric.authentication.auth_service import AuthService
    from intric.users.user import UserInDB

    original_get_jwt_payload = AuthService.get_jwt_payload

    def patched_create_token(
        self,
        user: UserInDB,
        secret_key: str | None = None,
        audience: str | None = None,
        expires_in: int | None = None,
    ) -> str:
        secret = secret_key or test_settings.jwt_secret
        aud = audience or test_settings.jwt_audience
        expiry_minutes = expires_in or test_settings.jwt_expiry_time

        jwt_meta = JWTMeta(
            iss=test_settings.jwt_issuer,
            aud=aud,
            iat=datetime.timestamp(datetime.now(timezone.utc) - timedelta(seconds=2)),
            exp=datetime.timestamp(
                datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)
            ),
        )
        jwt_creds = JWTCreds(sub=user.email, username=user.username)
        payload = JWTPayload(**jwt_meta.model_dump(), **jwt_creds.model_dump())

        return jwt_lib.encode(
            payload.model_dump(), secret, algorithm=test_settings.jwt_algorithm
        )

    def patched_get_jwt_payload(
        self,
        token: str,
        key: str,
        aud: str | None = None,
        algs: list[str] | None = None,
    ):
        return original_get_jwt_payload(
            self,
            token,
            key,
            aud=aud or test_settings.jwt_audience,
            algs=algs or [test_settings.jwt_algorithm],
        )

    monkeypatch.setattr(AuthService, "create_access_token_for_user", patched_create_token)
    monkeypatch.setattr(AuthService, "get_jwt_payload", patched_get_jwt_payload)


@pytest.fixture
def jwks_mock(monkeypatch):
    """Stub out PyJWKClient so tests never fetch real JWKS documents.

    Patches both jwt.PyJWKClient and the federation_router's JWKClient alias
    to ensure the mock is used even though the module has already imported and bound the name.
    """
    import jwt as jwt_lib

    def _configure(signing_keys: dict[str, str] | None = None, default_key: str = "test-signing-key"):
        keys = signing_keys or {}

        class _Key:
            def __init__(self, key: str):
                self.key = key

        class _FakePyJWKClient:
            def __init__(self, jwks_uri: str):  # noqa: D401 - signature matches real class
                self.jwks_uri = jwks_uri

            def get_signing_key_from_jwt(self, token: str):
                return _Key(keys.get(token, default_key))

        # Patch the jwt module's PyJWKClient
        monkeypatch.setattr(jwt_lib, "PyJWKClient", _FakePyJWKClient)

        # CRITICAL: Also patch the federation_router's module-level JWKClient alias
        # The router does: from jwt import PyJWKClient as _PyJWKClient; JWKClient = _PyJWKClient
        # Since it's already bound at import time, we must patch the alias directly
        monkeypatch.setattr(
            "intric.authentication.federation_router.JWKClient",
            _FakePyJWKClient,
        )

        return _FakePyJWKClient

    return _configure


@pytest.fixture
def oidc_mock(monkeypatch):
    """Provide a configurable fake aiohttp client for OIDC discovery/token calls."""

    def _install(
        *,
        discovery: dict[str, tuple[dict, int] | dict] | None = None,
        tokens: dict[tuple[str, str | None], tuple[dict, int] | dict] | None = None,
    ) -> Callable[[], dict[str, list[tuple[str, str]]]]:
        discovery_map: dict[str, tuple[dict, int]] = {}
        for url, payload in (discovery or {}).items():
            if isinstance(payload, tuple):
                discovery_map[url] = payload
            else:
                discovery_map[url] = (payload, 200)

        token_map: dict[tuple[str, str | None], tuple[dict, int]] = {}
        for key, payload in (tokens or {}).items():
            if isinstance(payload, tuple):
                token_map[key] = payload
            else:
                token_map[key] = (payload, 200)
        request_log: list[tuple[str, str]] = []

        class _FakeResponse:
            def __init__(self, payload: dict, status: int = 200):
                self._payload = payload
                self.status = status

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def json(self):
                return self._payload

            async def text(self):
                return json.dumps(self._payload)

        class _FakeClient:
            def get(self, url: str, **kwargs):
                """Accept headers, params, timeout, and other kwargs for compatibility."""
                request_log.append(("GET", url))
                if url not in discovery_map:
                    raise AssertionError(f"Unmocked discovery URL: {url}")
                payload, status = discovery_map[url]
                return _FakeResponse(payload, status)

            def post(self, url: str, data=None, **kwargs):
                """Accept headers, timeout, auth, and other kwargs for compatibility."""
                request_log.append(("POST", url))
                code = None
                if isinstance(data, dict):
                    code = data.get("code") or data.get("authorization_code")
                key = (url, code)
                if key not in token_map:
                    raise AssertionError(f"Unmocked token request: {url} code={code}")
                payload, status = token_map[key]
                return _FakeResponse(payload, status)

        fake_client = _FakeClient()

        def _client_factory():
            return fake_client

        import intric.main.aiohttp_client as aiohttp_client_module

        monkeypatch.setattr(aiohttp_client_module, "aiohttp_client", _client_factory)
        monkeypatch.setattr(
            "intric.authentication.federation_router.aiohttp_client",
            _client_factory,
        )
        monkeypatch.setattr(
            "intric.users.user_router.aiohttp_client",
            _client_factory,
            raising=False,
        )

        def _summary() -> dict[str, list[tuple[str, str]]]:
            return {"requests": request_log}

        return _summary

    return _install


@pytest.fixture
async def tenant_user_token(test_tenant, test_settings):
    """Create a JWT token for a regular (non-admin) tenant user.

    This token represents a normal user within the tenant,
    NOT a system administrator. Used to test authorization boundaries.

    Creates the JWT directly using jwt.encode() with test_settings values,
    matching the pattern used in patch_auth_service_jwt fixture.
    """
    import jwt
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)

    # Create JWT payload matching app's expectations
    payload = {
        "sub": f"user@{test_tenant.slug}.test",  # Email as subject
        "username": "testuser",  # Username for regular user
        "iss": test_settings.jwt_issuer,
        "aud": test_settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=30)).timestamp()),
        "tenant_id": str(test_tenant.id),
        "email": f"user@{test_tenant.slug}.test",
    }

    # Encode using test JWT secret (HS256)
    token = jwt.encode(
        payload,
        test_settings.jwt_secret,
        algorithm=test_settings.jwt_algorithm
    )

    return token


@pytest.fixture(autouse=True)
async def seed_default_models(setup_database, monkeypatch):
    """Seed default completion and embedding models for integration tests.

    Since we disabled auto-seeding in lifespan.py, tests need at least one
    completion model to create assistants/apps/services.

    This fixture also patches TenantService.create_tenant to auto-enable models
    for any new tenants created during tests.

    This fixture runs automatically for all integration tests after database setup.
    """
    from intric.ai_models.completion_models.completion_model import CompletionModelCreate
    from intric.ai_models.embedding_models.embedding_model import EmbeddingModelCreate
    from intric.ai_models.completion_models.completion_models_repo import CompletionModelsRepository
    from intric.ai_models.embedding_models.embedding_models_repo import AdminEmbeddingModelsService
    from intric.database.tables.ai_models_table import CompletionModelSettings, EmbeddingModelSettings
    from intric.database.database import sessionmanager
    from intric.tenants.tenant_service import TenantService
    from intric.tenants.tenant import TenantBase, TenantInDB

    # Create default models
    async with sessionmanager.session() as session:
        async with session.begin():
            # Create a default completion model (using unique name to avoid conflicts with tests)
            completion_repo = CompletionModelsRepository(session=session)
            default_completion = CompletionModelCreate(
                name="fixture-gpt-4",
                nickname="Fixture GPT-4",
                family="openai",
                token_limit=8000,
                is_deprecated=False,
                stability="stable",
                hosting="usa",
                open_source=False,
                org="OpenAI",
                vision=True,
                reasoning=False,
                base_url="https://api.openai.com/v1",
                litellm_model_name="gpt-4",
            )
            completion_model = await completion_repo.create_model(default_completion)

            # Create a default embedding model (using unique name to avoid conflicts with tests)
            embedding_repo = AdminEmbeddingModelsService(session=session)
            default_embedding = EmbeddingModelCreate(
                name="fixture-text-embedding",
                family="openai",
                is_deprecated=False,
                open_source=False,
                dimensions=1536,
                max_input=8191,
                max_batch_size=100,
                stability="stable",
                hosting="usa",
                org="OpenAI",
                litellm_model_name="text-embedding-ada-002",
            )
            embedding_model = await embedding_repo.create_model(default_embedding)

            # Enable both models for all existing tenants
            from intric.database.tables.tenant_table import Tenants
            import sqlalchemy as sa

            result = await session.execute(sa.select(Tenants))
            tenants = result.scalars().all()

            for tenant in tenants:
                # Enable completion model
                completion_settings = CompletionModelSettings(
                    tenant_id=tenant.id,
                    completion_model_id=completion_model.id,
                    is_org_enabled=True,
                    is_org_default=True,
                )
                session.add(completion_settings)

                # Enable embedding model
                embedding_settings = EmbeddingModelSettings(
                    tenant_id=tenant.id,
                    embedding_model_id=embedding_model.id,
                    is_org_enabled=True,
                    is_org_default=True,
                )
                session.add(embedding_settings)

    # Patch TenantService.create_tenant to auto-enable models for new tenants in tests
    original_create_tenant = TenantService.create_tenant

    async def create_tenant_with_models(self, tenant: TenantBase) -> TenantInDB:
        # Call original method
        tenant_in_db = await original_create_tenant(self, tenant)

        # Auto-enable default models (test-only behavior)
        session = self.repo.session
        import sqlalchemy as sa

        # Enable completion model
        stmt = sa.select(CompletionModelSettings).where(
            CompletionModelSettings.tenant_id == tenant_in_db.id,
            CompletionModelSettings.completion_model_id == completion_model.id,
        )
        existing = await session.execute(stmt)
        if not existing.scalar_one_or_none():
            completion_settings = CompletionModelSettings(
                tenant_id=tenant_in_db.id,
                completion_model_id=completion_model.id,
                is_org_enabled=True,
                is_org_default=True,
            )
            session.add(completion_settings)

        # Enable embedding model
        stmt = sa.select(EmbeddingModelSettings).where(
            EmbeddingModelSettings.tenant_id == tenant_in_db.id,
            EmbeddingModelSettings.embedding_model_id == embedding_model.id,
        )
        existing = await session.execute(stmt)
        if not existing.scalar_one_or_none():
            embedding_settings = EmbeddingModelSettings(
                tenant_id=tenant_in_db.id,
                embedding_model_id=embedding_model.id,
                is_org_enabled=True,
                is_org_default=True,
            )
            session.add(embedding_settings)

        return tenant_in_db

    monkeypatch.setattr(TenantService, "create_tenant", create_tenant_with_models)


@pytest.fixture
def mock_transcription_models(monkeypatch):
    """Stub transcription model enablement to avoid external dependencies."""
    from uuid import uuid4

    from intric.transcription_models.infrastructure import enable_transcription_models_service

    async def mock_get_model_id_by_name(self, model_name: str):
        return uuid4()

    async def mock_enable_transcription_model(
        self,
        transcription_model_id,
        tenant_id,
        is_org_enabled: bool = True,
        is_org_default: bool = False,
    ):
        return None

    monkeypatch.setattr(
        enable_transcription_models_service.TranscriptionModelEnableService,
        "get_model_id_by_name",
        mock_get_model_id_by_name,
    )
    monkeypatch.setattr(
        enable_transcription_models_service.TranscriptionModelEnableService,
        "enable_transcription_model",
        mock_enable_transcription_model,
    )


@pytest.fixture
async def debug_auth_config(test_settings):
    """
    Debug fixture to print auth configuration at runtime.

    This helps diagnose authentication issues by showing:
    - What values test_settings has
    - What values get_settings() returns at runtime
    - Whether Settings singleton is working correctly
    - What the actual API key header name is
    """
    from intric.main.config import get_settings
    from intric.server.dependencies.auth_definitions import API_KEY_HEADER

    runtime_settings = get_settings()

    print("\n=== AUTH DEBUG ===")
    print(f"Test settings intric_super_api_key: {test_settings.intric_super_api_key}")
    print(f"Runtime settings intric_super_api_key: {runtime_settings.intric_super_api_key}")
    print(f"Test settings api_key_header_name: {test_settings.api_key_header_name}")
    print(f"Runtime settings api_key_header_name: {runtime_settings.api_key_header_name}")
    print(f"API_KEY_HEADER name: {API_KEY_HEADER.model.name}")
    print(f"Settings object IDs match: {id(test_settings) == id(runtime_settings)}")
    print("=================\n")
