"""Fixtures for audit integration tests."""

import pytest
from sqlalchemy import select
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from intric.database.tables.users_table import Users


@pytest.fixture
async def test_user(db_session, test_tenant):
    """Get the default test user ID."""
    async with db_session() as session:
        query = select(Users.id).where(
            Users.email == "test@example.com",
            Users.tenant_id == test_tenant.id
        )
        result = await session.execute(query)
        user_id = result.scalar_one_or_none()
        if not user_id:
            raise ValueError("No test user found in database")
        return user_id


@pytest.fixture
async def auth_headers(admin_user_api_key):
    """Return HTTP headers with valid admin API key for audit endpoints."""
    # admin_user_api_key is an ApiKeyCreated object, extract the actual key string
    return {"X-API-Key": admin_user_api_key.key}


@pytest.fixture
async def auth_headers_with_session(client, auth_headers, redis_client, db_container):
    """Create audit session and return headers + cookies for /logs access.

    Returns a tuple of (headers, cookies_dict) for use in tests that need
    both authentication and an active audit session.

    Note: We return cookies as a simple dict to avoid httpx cookie domain/path
    issues that can prevent cookies from being sent on subsequent requests.

    Note: This fixture resets the rate limit and audit config cache before creating
    a session to ensure tests don't interfere with each other.
    """
    # Get user and tenant IDs to construct keys
    async with db_container() as container:
        user = container.user()
        user_id = user.id
        tenant_id = user.tenant_id

    # Reset rate limit directly via Redis to avoid test interference
    # (tests like test_rate_limiting_enforces_5_sessions_per_hour consume the limit)
    rate_limit_key = f"rate_limit:audit_session:{user_id}:{tenant_id}"
    try:
        await redis_client.delete(rate_limit_key)
    except Exception:
        pass  # Ignore errors, session creation will fail if rate limited anyway

    # Also clear audit config cache for this tenant to ensure clean state
    # This prevents stale cached "disabled" values from previous tests
    audit_cache_keys = [
        f"audit_config:{tenant_id}:audit_access",
        f"audit_action:{tenant_id}:audit_log_viewed",
        f"audit_action:{tenant_id}:audit_log_exported",
        f"audit_action:{tenant_id}:audit_session_created",
    ]
    for cache_key in audit_cache_keys:
        try:
            await redis_client.delete(cache_key)
        except Exception:
            pass

    response = await client.post(
        "/api/v1/audit/access-session",
        json={
            "category": "integration_test",
            "description": "Integration test session for audit API testing"
        },
        headers=auth_headers
    )
    assert response.status_code == 200, f"Failed to create audit session: {response.text}"

    # Extract cookie value as simple dict to avoid domain matching issues
    # httpx Cookies objects can fail to send cookies due to domain/path mismatch
    cookies_dict = {
        "audit_session_id": response.cookies.get("audit_session_id")
    }

    return auth_headers, cookies_dict


@dataclass
class TestUser2:
    """Test user from a second tenant for isolation testing."""
    id: str
    email: str
    tenant_id: str
    token: str


@pytest.fixture
async def test_tenant_2(db_container):
    """Create a second tenant for multi-tenant isolation tests."""
    from intric.tenants.tenant import TenantBase

    async with db_container() as container:
        tenant_service = container.tenant_service()
        tenant = await tenant_service.create_tenant(
            TenantBase(
                name="test_tenant_2",
                slug="test-tenant-2"
            )
        )
        return tenant


@pytest.fixture
async def test_user_2(db_container, test_tenant_2, test_settings):
    """Create an admin user in the second tenant with API key auth.

    Returns a TestUser2 object with id, email, tenant_id, and API key.
    """
    import psycopg2
    from psycopg2 import sql
    import bcrypt

    # Create user in tenant 2 via raw SQL (same pattern as main conftest)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )

    try:
        cur = conn.cursor()
        tenant_id = test_tenant_2.id

        # Create password hash
        pwd_bytes = "test_password_2".encode('utf-8')
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(password=pwd_bytes, salt=salt)

        # Insert user
        add_user_query = sql.SQL(
            "INSERT INTO users (username, email, password, salt, tenant_id, used_tokens, state) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id"
        )
        cur.execute(
            add_user_query,
            ("test_user_2", "test2@example.com", hashed_password.decode('utf-8'),
             salt.decode(), tenant_id, 0, "active"),
        )
        user_id = cur.fetchone()[0]

        # Get or create Owner role
        check_role_query = sql.SQL("SELECT id FROM predefined_roles WHERE name = %s")
        cur.execute(check_role_query, ("Owner",))
        role = cur.fetchone()

        if role is None:
            owner_permissions = ["admin", "assistants", "services", "collections",
                               "insights", "AI", "editor", "websites"]
            add_role_query = sql.SQL(
                "INSERT INTO predefined_roles (name, permissions) VALUES (%s, %s) RETURNING id"
            )
            cur.execute(add_role_query, ("Owner", owner_permissions))
            predefined_role_id = cur.fetchone()[0]
        else:
            predefined_role_id = role[0]

        # Assign Owner role to user
        assign_role_query = sql.SQL(
            "INSERT INTO users_predefined_roles (user_id, predefined_role_id) VALUES (%s, %s)"
        )
        cur.execute(assign_role_query, (user_id, predefined_role_id))

        conn.commit()
        cur.close()
    finally:
        conn.close()

    # Create API key for the user
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_email("test2@example.com")

        auth_service = container.auth_service()
        api_key = await auth_service.create_user_api_key(
            prefix="test2",
            user_id=user.id,
            delete_old=True
        )

        return TestUser2(
            id=str(user.id),
            email=user.email,
            tenant_id=str(tenant_id),
            token=api_key.key  # Use API key instead of JWT token
        )


@pytest.fixture
async def container(db_container):
    """Provide configured DI container for service access.

    Convenience fixture that provides a pre-configured container
    with the default test user and tenant.
    """
    async with db_container() as container:
        yield container


@pytest.fixture
async def sample_audit_logs(db_session, test_tenant, test_user):
    """Create diverse audit logs for pagination and filtering tests.

    Creates 55 logs with varied actions, timestamps, and metadata
    to test pagination, filtering, and export functionality.
    """
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
    from intric.audit.domain.audit_log import AuditLog
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.domain.actor_types import ActorType
    from intric.audit.domain.outcome import Outcome

    logs = []
    actions = [
        ActionType.USER_CREATED,
        ActionType.USER_DELETED,
        ActionType.ASSISTANT_CREATED,
        ActionType.SPACE_CREATED,
        ActionType.FILE_UPLOADED,
    ]

    async with db_session() as session:
        repo = AuditLogRepositoryImpl(session)

        for i in range(55):
            action = actions[i % len(actions)]
            log = AuditLog(
                id=uuid4(),
                tenant_id=test_tenant.id,
                actor_id=test_user,
                actor_type=ActorType.USER,
                action=action,
                entity_type=EntityType.USER if "USER" in action.value.upper() else EntityType.ASSISTANT,
                entity_id=uuid4(),
                timestamp=datetime.now(timezone.utc) - timedelta(hours=i),
                description=f"Test audit log {i + 1} - {action.value}",
                metadata={"test_index": i, "batch": "sample_audit_logs"},
                outcome=Outcome.SUCCESS,
            )
            created = await repo.create(log)
            logs.append(created)

    return logs


@pytest.fixture
async def searchable_audit_logs(db_session, test_tenant, test_user):
    """Create audit logs with specific entity names for search testing.

    Creates logs with varied descriptions containing searchable entity names:
    - "Sales Bot" (assistant) - 15 logs for pagination test
    - "Documents" (collection) - 3 logs
    - "Marketing App" (app) - 2 logs
    - Generic logs without entity names - 5 logs

    Total: 25 logs for comprehensive search testing.
    """
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
    from intric.audit.domain.audit_log import AuditLog
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.domain.actor_types import ActorType
    from intric.audit.domain.outcome import Outcome

    logs = []

    async with db_session() as session:
        repo = AuditLogRepositoryImpl(session)

        # Create 15 logs with "Sales Bot" for pagination testing
        for i in range(15):
            log = AuditLog(
                id=uuid4(),
                tenant_id=test_tenant.id,
                actor_id=test_user,
                actor_type=ActorType.USER,
                action=ActionType.ASSISTANT_CREATED if i % 2 == 0 else ActionType.ASSISTANT_UPDATED,
                entity_type=EntityType.ASSISTANT,
                entity_id=uuid4(),
                timestamp=datetime.now(timezone.utc) - timedelta(hours=i),
                description=f"{'Created' if i % 2 == 0 else 'Updated'} assistant 'Sales Bot' - action {i + 1}",
                metadata={"entity_name": "Sales Bot", "test_batch": "searchable"},
                outcome=Outcome.SUCCESS,
            )
            created = await repo.create(log)
            logs.append(created)

        # Create 3 logs with "Documents" collection
        for i in range(3):
            log = AuditLog(
                id=uuid4(),
                tenant_id=test_tenant.id,
                actor_id=test_user,
                actor_type=ActorType.USER,
                action=ActionType.COLLECTION_CREATED,
                entity_type=EntityType.COLLECTION,
                entity_id=uuid4(),
                timestamp=datetime.now(timezone.utc) - timedelta(hours=20 + i),
                description=f"Created collection 'Documents' - item {i + 1}",
                metadata={"entity_name": "Documents", "test_batch": "searchable"},
                outcome=Outcome.SUCCESS,
            )
            created = await repo.create(log)
            logs.append(created)

        # Create 2 logs with "Marketing App"
        for i in range(2):
            log = AuditLog(
                id=uuid4(),
                tenant_id=test_tenant.id,
                actor_id=test_user,
                actor_type=ActorType.USER,
                action=ActionType.APP_CREATED,
                entity_type=EntityType.APP,
                entity_id=uuid4(),
                timestamp=datetime.now(timezone.utc) - timedelta(hours=25 + i),
                description=f"Created app 'Marketing App' - version {i + 1}",
                metadata={"entity_name": "Marketing App", "test_batch": "searchable"},
                outcome=Outcome.SUCCESS,
            )
            created = await repo.create(log)
            logs.append(created)

        # Create 5 generic logs without specific entity names
        for i in range(5):
            log = AuditLog(
                id=uuid4(),
                tenant_id=test_tenant.id,
                actor_id=test_user,
                actor_type=ActorType.USER,
                action=ActionType.SESSION_STARTED,
                entity_type=EntityType.USER,
                entity_id=uuid4(),
                timestamp=datetime.now(timezone.utc) - timedelta(hours=30 + i),
                description=f"User session started - session {i + 1}",
                metadata={"test_batch": "searchable"},
                outcome=Outcome.SUCCESS,
            )
            created = await repo.create(log)
            logs.append(created)

    return logs
