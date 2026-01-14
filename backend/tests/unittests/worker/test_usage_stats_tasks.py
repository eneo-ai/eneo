"""Unit tests for tenant usage statistics task helpers."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from intric.jobs.job_models import Task
from intric.jobs.task_models import UpdateUsageStatsTaskParams
from intric.tenants.tenant import TenantInDB, TenantState
from intric.users.user import UserInDB
from intric.worker.usage_stats_tasks import (
    recalculate_all_tenants_usage_stats,
    recalculate_tenant_usage_stats,
)


class ProviderStub:
    def __init__(self):
        self._value = None

    def override(self, new_value):
        self._value = new_value
        return new_value

    def reset(self):
        self._value = None

    def reset_override(self):
        self._value = None

    def value(self):
        if callable(self._value):
            return self._value()
        return self._value

    def __call__(self):
        return self.value()


class FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):  # noqa: D401
        return self._row


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: D401
        return False


class FakeSession:
    def __init__(self, rows):
        if rows is None:
            rows = [None]
        if not isinstance(rows, list):
            rows = [rows]
        self._rows = rows
        self._calls = 0

    async def execute(self, statement):  # noqa: ARG002
        if self._calls < len(self._rows):
            row = self._rows[self._calls]
        else:
            row = None
        self._calls += 1
        return FakeResult(row)

    def begin(self):  # noqa: D401
        return FakeTransaction()


class FakeTenantRepo:
    def __init__(self, primary_tenant, tenants=None):
        self._primary = primary_tenant
        self._tenants = tenants if tenants is not None else ([primary_tenant] if primary_tenant else [])

    async def get(self, tenant_id):
        for tenant in self._tenants:
            if tenant and tenant.id == tenant_id:
                return tenant
        if self._primary and self._primary.id == tenant_id:
            return self._primary
        return None

    async def get_all_tenants(self):
        return self._tenants


class FakeUserRepo:
    def __init__(self, users=None):
        self._users = {}
        for user in users or []:
            self._users[user.id] = user

    async def get_user_by_id(self, user_id):
        return self._users.get(user_id)


class FakeJobService:
    def __init__(self):
        self.calls = []

    async def queue_job(self, task, *, name, task_params):
        self.calls.append((task, name, task_params))


class FakeUsageService:
    def __init__(self, user_provider, tenant_provider):
        self.calls = []
        self.user_provider = user_provider
        self.tenant_provider = tenant_provider

    async def recalculate_all_usage_stats_in_transaction(self, tenant_id):
        self.calls.append((tenant_id, self.user_provider(), self.tenant_provider()))


class FakeContainer:
    def __init__(
        self,
        *,
        tenant,
        user_row,
        user_obj,
        job_service,
        tenant_list=None,
        user_rows=None,
        users=None,
    ):
        self.user = ProviderStub()
        self.tenant = ProviderStub()
        self.session = ProviderStub()

        self._tenant_repo = FakeTenantRepo(tenant, tenant_list)
        self._user_repo = FakeUserRepo(users or ([user_obj] if user_obj else []))
        session_rows = user_rows if user_rows is not None else [user_row]
        self._session = FakeSession(session_rows)
        self.session.override(self._session)
        self._job_service = job_service
        self._usage_service = FakeUsageService(self.user, self.tenant)

    def tenant_repo(self):
        return self._tenant_repo

    def user_repo(self):
        return self._user_repo

    def job_service(self):
        return self._job_service

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


def build_user(tenant_id, tenant=None):
    return UserInDB(
        id=uuid4(),
        username="ops",
        email="ops@example.com",
        salt="salt",
        password="hashed123",
        used_tokens=0,
        tenant_id=tenant_id,
        tenant=tenant,
        quota_limit=1024**3,
        user_groups=[],
        roles=[],
        state="active",
    )


@pytest.mark.asyncio
async def test_recalculate_tenant_usage_stats_success():
    tenant = build_tenant()
    user = build_user(tenant.id, tenant)
    user_row = SimpleNamespace(id=user.id)
    job_service = FakeJobService()
    container = FakeContainer(tenant=tenant, user_row=user_row, user_obj=user, job_service=job_service)

    result = await recalculate_tenant_usage_stats(container, tenant.id)

    assert result is True
    assert job_service.calls  # one call queued
    task, _, params = job_service.calls[0]
    assert task == Task.UPDATE_MODEL_USAGE_STATS
    assert isinstance(params, UpdateUsageStatsTaskParams)
    assert params.tenant_id == tenant.id
    assert container.user() == user
    assert container.tenant() == tenant


@pytest.mark.asyncio
async def test_recalculate_tenant_usage_stats_rejects_user_mismatch():
    tenant = build_tenant()
    wrong_tenant = build_tenant()  # different tenant
    user = build_user(wrong_tenant.id, wrong_tenant)  # user from different tenant
    user_row = SimpleNamespace(id=user.id)
    job_service = FakeJobService()
    container = FakeContainer(tenant=tenant, user_row=user_row, user_obj=user, job_service=job_service)

    result = await recalculate_tenant_usage_stats(container, tenant.id)

    assert result is False
    assert container.user.value() is None
    assert not job_service.calls


@pytest.mark.asyncio
async def test_recalculate_tenant_usage_stats_handles_missing_user():
    tenant = build_tenant()
    user_row = None  # session will return no user rows
    job_service = FakeJobService()
    container = FakeContainer(tenant=tenant, user_row=user_row, user_obj=None, job_service=job_service)

    result = await recalculate_tenant_usage_stats(container, tenant.id)

    assert result is False
    assert not job_service.calls


@pytest.mark.asyncio
async def test_recalculate_tenant_usage_stats_isolated_between_tenants():
    tenant_a = build_tenant()
    tenant_b = build_tenant()

    user_a = build_user(tenant_a.id, tenant_a)
    user_b = build_user(tenant_b.id, tenant_b)

    row_a = SimpleNamespace(id=user_a.id)
    row_b = SimpleNamespace(id=user_b.id)

    job_service = FakeJobService()

    container_a = FakeContainer(tenant=tenant_a, user_row=row_a, user_obj=user_a, job_service=job_service)
    container_b = FakeContainer(tenant=tenant_b, user_row=row_b, user_obj=user_b, job_service=job_service)

    result_a = await recalculate_tenant_usage_stats(container_a, tenant_a.id)
    result_b = await recalculate_tenant_usage_stats(container_b, tenant_b.id)

    assert result_a is True
    assert result_b is True
    assert len(job_service.calls) == 2

    first_task, _, first_params = job_service.calls[0]
    second_task, _, second_params = job_service.calls[1]

    assert first_task == Task.UPDATE_MODEL_USAGE_STATS
    assert second_task == Task.UPDATE_MODEL_USAGE_STATS
    assert first_params.tenant_id == tenant_a.id
    assert second_params.tenant_id == tenant_b.id

    # Ensure per-container context is scoped to the tenant of the job being queued
    assert container_a.tenant() == tenant_a
    assert container_b.tenant() == tenant_b
    assert container_a.user() == user_a
    assert container_b.user() == user_b


@pytest.mark.asyncio
async def test_recalculate_all_tenants_usage_stats_processes_active_tenants_only():
    tenant_a = build_tenant()
    tenant_b = build_tenant()
    suspended_tenant = build_tenant()
    suspended_tenant.state = TenantState.SUSPENDED

    user_a = build_user(tenant_a.id, tenant_a)
    user_b = build_user(tenant_b.id, tenant_b)

    user_rows = [SimpleNamespace(id=user_a.id), SimpleNamespace(id=user_b.id), None]

    job_service = FakeJobService()
    container = FakeContainer(
        tenant=tenant_a,
        user_row=None,
        user_obj=None,
        job_service=job_service,
        tenant_list=[tenant_a, tenant_b, suspended_tenant],
        user_rows=user_rows,
        users=[user_a, user_b],
    )

    # Create a mock sessionmanager that returns FakeSession with correct user per iteration
    iteration = [0]

    @asynccontextmanager
    async def mock_session():
        # First call is for getting tenant list, subsequent calls are per-tenant
        if iteration[0] == 0:
            # Initial tenant list fetch - doesn't query users
            yield FakeSession([None])
        else:
            # Per-tenant iteration - return the correct user row
            user_idx = iteration[0] - 1
            if user_idx < len(user_rows):
                yield FakeSession([user_rows[user_idx]])
            else:
                yield FakeSession([None])
        iteration[0] += 1

    with patch("intric.worker.usage_stats_tasks.sessionmanager") as mock_sm:
        mock_sm.session = mock_session
        result = await recalculate_all_tenants_usage_stats(container)

    assert result is True
    usage_calls = container.completion_model_usage_service().calls
    assert len(usage_calls) == 2

    processed_ids = {tenant_id for tenant_id, _, _ in usage_calls}
    assert processed_ids == {tenant_a.id, tenant_b.id}

    for tenant_id, user_ctx, tenant_ctx in usage_calls:
        assert tenant_ctx.id == tenant_id
        assert user_ctx.tenant_id == tenant_id

    assert suspended_tenant.id not in processed_ids


@pytest.mark.asyncio
async def test_recalculate_all_tenants_usage_stats_balances_multiple_tenants():
    tenants = [build_tenant() for _ in range(5)]
    users = [build_user(t.id, t) for t in tenants]
    user_rows = [SimpleNamespace(id=u.id) for u in users]

    job_service = FakeJobService()
    container = FakeContainer(
        tenant=tenants[0],
        user_row=None,
        user_obj=None,
        job_service=job_service,
        tenant_list=tenants,
        user_rows=user_rows,
        users=users,
    )

    # Create a mock sessionmanager that returns FakeSession with correct user per iteration
    iteration = [0]

    @asynccontextmanager
    async def mock_session():
        # First call is for getting tenant list, subsequent calls are per-tenant
        if iteration[0] == 0:
            # Initial tenant list fetch - doesn't query users
            yield FakeSession([None])
        else:
            # Per-tenant iteration - return the correct user row
            user_idx = iteration[0] - 1
            if user_idx < len(user_rows):
                yield FakeSession([user_rows[user_idx]])
            else:
                yield FakeSession([None])
        iteration[0] += 1

    with patch("intric.worker.usage_stats_tasks.sessionmanager") as mock_sm:
        mock_sm.session = mock_session
        result = await recalculate_all_tenants_usage_stats(container)

    assert result is True
    usage_calls = container.completion_model_usage_service().calls
    assert len(usage_calls) == len(tenants)
    ordered_ids = [tenant_id for tenant_id, _, _ in usage_calls]
    expected_order = [t.id for t in tenants]
    assert ordered_ids == expected_order
    assert {tenant_id for tenant_id in ordered_ids} == set(expected_order)
