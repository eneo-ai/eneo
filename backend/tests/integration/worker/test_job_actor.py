"""Whom a job runs as in the worker: the person who queued it, the service
key signed in again, or the space whose own scheduled work it is."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.authentication.auth_models import is_service_api_key, is_space_actor
from eneo.authentication.principal import Principal
from eneo.authentication.principal_types import PrincipalType
from eneo.database.tables.job_table import Jobs
from eneo.jobs.job_models import Task
from eneo.jobs.task_models import ResourceTaskParams, task_actor
from eneo.main.models import Status
from eneo.worker.job_actor import JobActor, load_job_user
from eneo.worker.worker import Worker


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


async def test_a_failure_is_recorded_for_a_job_whose_key_is_revoked(
    db_container, service_key
):
    """The key cannot be signed in again, so the job cannot run. That it
    failed is written all the same: nobody has to be signed in for that."""
    job_id = uuid4()
    async with db_container() as container:
        await container.session().execute(
            sa.insert(Jobs).values(
                id=job_id,
                task=Task.CRAWL.value,
                status=Status.IN_PROGRESS.value,
                service_principal_id=service_key.key.service_principal_id,
                api_key_id=service_key.key.id,
            )
        )
        await container.api_key_v2_repo().update(
            key_id=service_key.key.id,
            tenant_id=service_key.tenant_id,
            revoked_at=datetime.now(timezone.utc),
        )

    recorded = await Worker()._record_job_failure(
        job_id, AssertionError("the key could not be signed in")
    )

    assert recorded is True
    async with db_container() as container:
        job = await container.job_repo().get_job(job_id)
    assert job.status == Status.FAILED
    assert job.failure_code is not None
    assert job.finished_at is not None


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


async def _space(client, admin_token) -> UUID:
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": f"job-actor-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    return UUID(resp.json()["id"])


async def test_a_spaces_own_job_runs_as_that_space_and_nowhere_else(
    client, db_container, admin_user, admin_token
):
    space_id = await _space(client, admin_token)
    other_space_id = await _space(client, admin_token)
    async with db_container() as container:
        scheduled = await container.user_service().get_space_actor_user(
            space_id=space_id, tenant_id=admin_user.tenant_id
        )
    assert scheduled is not None
    params = ResourceTaskParams(id=uuid4(), **task_actor(scheduled))

    async with db_container() as container:
        user = await load_job_user(container, JobActor.of(params))

    assert user is not None
    assert is_space_actor(user)
    assert user.tenant_id == admin_user.tenant_id
    assert Principal.from_user(user).principal_type == PrincipalType.SPACE
    # Nobody owns the job, and no person or stored key is behind it.
    assert (params.user_id, params.service_principal_id, params.api_key_id) == (
        None,
        None,
        None,
    )
    async with db_container(user=user) as container:
        users = await container.session().scalar(
            sa.text("SELECT count(*) FROM users WHERE id = :id"), {"id": user.id}
        )
        keys = await container.session().scalar(
            sa.text("SELECT count(*) FROM api_keys_v2 WHERE id = :id"), {"id": user.id}
        )
        own = container.actor_manager().get_space_actor(
            await container.space_repo().get_space_access_facts(space_id)
        )
        other = container.actor_manager().get_space_actor(
            await container.space_repo().get_space_access_facts(other_space_id)
        )
    assert (users, keys) == (0, 0)
    assert own.can_create_websites() and own.can_edit_space()
    assert not other.can_read_space()


async def test_a_space_of_another_organisation_runs_nothing(
    client, db_container, admin_token
):
    space_id = await _space(client, admin_token)

    async with db_container() as container:
        foreign = await load_job_user(
            container, JobActor(tenant_id=uuid4(), acting_space_id=space_id)
        )
        gone = await load_job_user(
            container, JobActor(tenant_id=uuid4(), acting_space_id=uuid4())
        )

    assert foreign is None
    assert gone is None
