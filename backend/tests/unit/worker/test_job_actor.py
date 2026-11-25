from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.worker.job_actor import JobActor, load_job_user


def _container(*, person=None, service_key_user=None, space_actor=None):
    container = MagicMock()
    container.user_repo.return_value.get_user_by_id = AsyncMock(return_value=person)
    container.user_service.return_value.get_service_key_user = AsyncMock(
        return_value=service_key_user
    )
    container.user_service.return_value.get_space_actor_user = AsyncMock(
        return_value=space_actor
    )
    return container


def test_the_actor_is_read_from_the_params():
    params = SimpleNamespace(user_id=None, api_key_id=uuid4(), tenant_id=uuid4())

    actor = JobActor.of(params)

    assert actor == JobActor(api_key_id=params.api_key_id, tenant_id=params.tenant_id)
    assert actor.is_service_key
    assert actor.present


def test_params_without_an_actor_run_as_nobody():
    actor = JobActor.of(SimpleNamespace())

    assert not actor.present
    assert not actor.is_service_key


def test_a_person_is_present_and_not_a_service_key():
    actor = JobActor(user_id=uuid4(), tenant_id=uuid4())

    assert actor.present
    assert not actor.is_service_key


async def test_a_persons_job_runs_as_that_person():
    person = SimpleNamespace(id=uuid4())
    container = _container(person=person)

    user = await load_job_user(container, JobActor(user_id=person.id))

    assert user is person
    container.user_repo.return_value.get_user_by_id.assert_awaited_once_with(
        id=person.id
    )
    container.user_service.return_value.get_service_key_user.assert_not_awaited()


async def test_a_service_keys_job_runs_as_the_key_signed_in_again():
    key_id, tenant_id = uuid4(), uuid4()
    key_user = SimpleNamespace(id=key_id)
    container = _container(service_key_user=key_user)

    user = await load_job_user(
        container, JobActor(api_key_id=key_id, tenant_id=tenant_id)
    )

    assert user is key_user
    container.user_service.return_value.get_service_key_user.assert_awaited_once_with(
        key_id=key_id, tenant_id=tenant_id
    )
    container.user_repo.return_value.get_user_by_id.assert_not_awaited()


async def test_a_job_whose_key_lost_its_access_has_no_user():
    container = _container(service_key_user=None)

    user = await load_job_user(
        container, JobActor(api_key_id=uuid4(), tenant_id=uuid4())
    )

    assert user is None


async def test_a_job_without_an_actor_has_no_user():
    container = _container()

    assert await load_job_user(container, JobActor()) is None
    container.user_repo.return_value.get_user_by_id.assert_not_awaited()
    container.user_service.return_value.get_service_key_user.assert_not_awaited()


def test_a_spaces_own_job_is_present_without_a_person_or_a_key():
    params = SimpleNamespace(
        user_id=None, api_key_id=None, tenant_id=uuid4(), acting_space_id=uuid4()
    )

    actor = JobActor.of(params)

    assert actor.is_space
    assert actor.present
    assert not actor.is_service_key


async def test_a_spaces_own_job_runs_as_the_space():
    space_id, tenant_id = uuid4(), uuid4()
    space_actor = SimpleNamespace(acting_space_id=space_id)
    container = _container(space_actor=space_actor)

    user = await load_job_user(
        container, JobActor(tenant_id=tenant_id, acting_space_id=space_id)
    )

    assert user is space_actor
    container.user_service.return_value.get_space_actor_user.assert_awaited_once_with(
        space_id=space_id, tenant_id=tenant_id
    )
    container.user_repo.return_value.get_user_by_id.assert_not_awaited()


async def test_a_spaces_own_job_has_no_user_once_the_space_is_gone():
    container = _container(space_actor=None)

    user = await load_job_user(
        container, JobActor(tenant_id=uuid4(), acting_space_id=uuid4())
    )

    assert user is None
