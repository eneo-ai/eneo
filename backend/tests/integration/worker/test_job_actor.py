"""A job a service key queued runs as that key, signed in again in the worker."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.authentication.auth_models import is_service_api_key
from eneo.jobs.task_models import ResourceTaskParams, task_actor
from eneo.worker.job_actor import JobActor, load_job_user


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def service_key(client, db_container, admin_user, admin_token):
    """A service key, and the params a job it queues would carry."""
    resp = await client.post(
        "/api/v1/api-keys",
        json={
            "name": f"svc-key-{uuid4().hex[:8]}",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
            "ownership": "service",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    key_id = UUID(resp.json()["api_key"]["id"])
    async with db_container() as container:
        key = await container.api_key_v2_repo().get(
            key_id=key_id, tenant_id=admin_user.tenant_id
        )
        assert key is not None
        signed_in = await container.user_service()._build_service_user(key)
    params = ResourceTaskParams(id=uuid4(), **task_actor(signed_in))
    return SimpleNamespace(key=key, params=params, tenant_id=admin_user.tenant_id)


async def test_the_worker_signs_the_service_key_in_again(db_container, service_key):
    async with db_container() as container:
        user = await load_job_user(container, JobActor.of(service_key.params))

    assert user is not None
    assert is_service_api_key(user)
    assert user.tenant_id == service_key.tenant_id
    assert user.active_api_key.id == service_key.key.id
    assert (
        user.active_api_key.service_principal_id == service_key.key.service_principal_id
    )
    # The job belongs to the principal, and the key is only how it runs.
    assert service_key.params.user_id is None
    assert (
        service_key.params.service_principal_id == service_key.key.service_principal_id
    )


async def test_a_job_does_not_run_once_its_key_is_revoked(db_container, service_key):
    async with db_container() as container:
        await container.api_key_v2_repo().update(
            key_id=service_key.key.id,
            tenant_id=service_key.tenant_id,
            revoked_at=datetime.now(timezone.utc),
        )

    async with db_container() as container:
        assert await load_job_user(container, JobActor.of(service_key.params)) is None


async def test_a_job_does_not_run_while_its_principal_is_disabled(
    db_container, service_key
):
    async with db_container() as container:
        await container.session().execute(
            sa.text(
                "UPDATE service_principals SET state = 'disabled', disabled_at = now()"
                " WHERE id = :id"
            ),
            {"id": service_key.key.service_principal_id},
        )

    async with db_container() as container:
        assert await load_job_user(container, JobActor.of(service_key.params)) is None


async def test_a_key_of_another_organisation_runs_nothing(db_container, service_key):
    foreign = JobActor(api_key_id=service_key.key.id, tenant_id=uuid4())

    async with db_container() as container:
        assert await load_job_user(container, foreign) is None


async def test_a_persons_job_runs_as_that_person(db_container, admin_user):
    params = ResourceTaskParams(id=uuid4(), **task_actor(admin_user))

    async with db_container() as container:
        user = await load_job_user(container, JobActor.of(params))

    assert user is not None
    assert user.id == admin_user.id
    assert not is_service_api_key(user)
