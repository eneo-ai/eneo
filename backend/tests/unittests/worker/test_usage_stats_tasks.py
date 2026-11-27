"""The nightly recalculation of usage statistics runs per organisation and
signs nobody in."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from eneo.tenants.tenant import TenantInDB, TenantState
from eneo.worker.usage_stats_tasks import recalculate_all_tenants_usage_stats


class ProviderStub:
    def __init__(self):
        self._value = None

    def override(self, new_value):
        self._value = new_value
        return new_value

    def reset_override(self):
        self._value = None

    def __call__(self):
        if callable(self._value):
            return self._value()
        return self._value


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    """A session the recalculation may open a transaction on, and nothing
    else: reading a user through it fails the test."""

    def begin(self):
        return FakeTransaction()

    async def scalar(self, statement):  # noqa: ARG002
        raise AssertionError("The recalculation looked a user up")

    async def execute(self, statement):  # noqa: ARG002
        raise AssertionError("The recalculation queried outside its service")


class FakeTenantRepo:
    def __init__(self, tenants):
        self._tenants = tenants

    async def get_all_tenants(self):
        return self._tenants


class FakeUsageService:
    def __init__(self, user_provider, tenant_provider):
        self.calls = []
        self.user_provider = user_provider
        self.tenant_provider = tenant_provider

    async def recalculate_all_usage_stats_in_transaction(self, tenant_id):
        self.calls.append((tenant_id, self.user_provider(), self.tenant_provider()))


class FakeContainer:
    def __init__(self, tenants):
        self.user = ProviderStub()
        self.tenant = ProviderStub()
        self.session = ProviderStub()
        self._tenant_repo = FakeTenantRepo(tenants)
        self._usage_service = FakeUsageService(self.user, self.tenant)

    def tenant_repo(self):
        return self._tenant_repo

    def completion_model_usage_service(self):
        return self._usage_service


def build_tenant():
    return TenantInDB(
        id=uuid4(),
        name="Tenant",
        display_name="Tenant",
        slug="tenant",
        quota_limit=1024**3,
        state=TenantState.ACTIVE,
        modules=[],
        api_credentials={},
        federation_config={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@asynccontextmanager
async def _fresh_session():
    yield FakeSession()


async def test_the_nightly_recalculation_covers_active_organisations_with_no_person():
    """The statistics are the organisation's own, so the recalculation runs
    for an organisation whoever is or is not left in it."""
    tenant_a = build_tenant()
    tenant_b = build_tenant()
    suspended_tenant = build_tenant()
    suspended_tenant.state = TenantState.SUSPENDED
    container = FakeContainer([tenant_a, tenant_b, suspended_tenant])

    with patch("eneo.worker.usage_stats_tasks.sessionmanager") as mock_sm:
        mock_sm.session = _fresh_session
        result = await recalculate_all_tenants_usage_stats(container)

    assert result is True
    usage_calls = container.completion_model_usage_service().calls
    assert [tenant_id for tenant_id, _, _ in usage_calls] == [tenant_a.id, tenant_b.id]
    for tenant_id, user_ctx, tenant_ctx in usage_calls:
        assert tenant_ctx.id == tenant_id
        assert user_ctx is None
    # Nothing of one organisation is left for the next one.
    assert container.tenant() is None


async def test_the_nightly_recalculation_takes_organisations_in_order():
    tenants = [build_tenant() for _ in range(5)]
    container = FakeContainer(tenants)

    with patch("eneo.worker.usage_stats_tasks.sessionmanager") as mock_sm:
        mock_sm.session = _fresh_session
        result = await recalculate_all_tenants_usage_stats(container)

    assert result is True
    usage_calls = container.completion_model_usage_service().calls
    assert [tenant_id for tenant_id, _, _ in usage_calls] == [t.id for t in tenants]
