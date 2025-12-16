import uuid

import pytest

from intric.ai_models.completion_models.completion_model import (
    ModelHostingLocation,
    ModelStability,
)
from intric.ai_models.embedding_models.embedding_model import (
    EmbeddingModelFamily,
    EmbeddingModelLegacy,
)
from intric.main.config import Settings, reset_settings
from intric.tenants.tenant import TenantInDB
from intric.users.user import UserInDB


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Create test settings with explicit values for unit tests.

    Similar to integration tests, this provides a clean, isolated configuration
    that doesn't depend on .env file or environment variables.
    """
    return Settings(
        # Fake API key for unit tests that instantiate OpenAI clients
        openai_api_key="sk-fake-unit-test-key-for-adapter-instantiation",
        anthropic_api_key=None,
        azure_api_key=None,
        berget_api_key=None,
        mistral_api_key=None,
        ovhcloud_api_key=None,
        vllm_api_key=None,

        # Minimal database settings (not used in unit tests)
        postgres_user="unit_test_user",
        postgres_host="localhost",
        postgres_password="unit_test_password",
        postgres_port=5432,
        postgres_db="unit_test_db",

        # Redis settings (not used in unit tests)
        redis_host="localhost",
        redis_port=6379,

        # Security
        encryption_key="yPIAaWTENh5knUuz75NYHblR3672X-7lH-W6AD4F1hs=",

        # Feature flags - default to single-tenant mode for unit tests
        tenant_credentials_enabled=False,
        federation_per_tenant_enabled=False,

        # Crawler settings - ensure TTL > max_length to pass validation
        crawl_max_length=1800,  # 30 minutes
        tenant_worker_semaphore_ttl_seconds=3600,  # 1 hour (must be > crawl_max_length)

        # Testing mode
        testing=True,
        dev=True,
    )


@pytest.fixture(autouse=True)
def reset_settings_after_test():
    """Reset settings after each test to prevent state leakage."""
    yield
    reset_settings()


@pytest.fixture
def embedding_model_small():
    return EmbeddingModelLegacy(
        id=uuid.uuid4(),
        name="text-embedding-3-small",
        family=EmbeddingModelFamily.OPEN_AI,
        open_source=False,
        dimensions=512,
        max_input=8191,
        stability=ModelStability.STABLE,
        hosting=ModelHostingLocation.USA,
        is_deprecated=False,
    )


@pytest.fixture
def tenant(embedding_model_small: EmbeddingModelLegacy):
    return TenantInDB(
        id=uuid.uuid4(),
        name="test_tenant",
        quota_limit=0,
        quota_used=0,
    )


@pytest.fixture
def user(tenant: TenantInDB):
    return UserInDB(
        id=uuid.uuid4(),
        username="test_user",
        email="test@user.com",
        salt="test_salt",
        password="test_pass",
        used_tokens=0,
        tenant_id=tenant.id,
        quota_used=0,
        tenant=tenant,
        state="active",
    )
