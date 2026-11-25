from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.jobs.task_models import ResourceTaskParams, TaskParams, task_actor


def _person():
    return SimpleNamespace(id=uuid4(), tenant_id=uuid4(), active_api_key=None)


def _service_key_user(service_principal_id):
    """The made-up user a service key signs in as: its id is the key's id."""
    key = SimpleNamespace(
        id=uuid4(), ownership="service", service_principal_id=service_principal_id
    )
    return SimpleNamespace(id=key.id, tenant_id=uuid4(), active_api_key=key)


def test_a_person_queues_a_job_as_themselves():
    person = _person()

    assert task_actor(person) == {
        "user_id": person.id,
        "service_principal_id": None,
        "api_key_id": None,
        "tenant_id": person.tenant_id,
    }


def test_a_personal_key_queues_a_job_as_its_owner():
    owner = _person()
    owner.active_api_key = SimpleNamespace(
        id=uuid4(), ownership="user", service_principal_id=None
    )

    actor = task_actor(owner)

    assert actor["user_id"] == owner.id
    assert actor["api_key_id"] is None


def test_a_service_key_queues_a_job_for_its_principal_and_names_itself():
    principal_id = uuid4()
    user = _service_key_user(principal_id)

    assert task_actor(user) == {
        "user_id": None,
        "service_principal_id": principal_id,
        "api_key_id": user.active_api_key.id,
        "tenant_id": user.tenant_id,
    }


def test_a_service_key_without_a_principal_queues_nothing():
    with pytest.raises(ValueError):
        task_actor(_service_key_user(None))


def test_params_carry_the_actor_to_the_worker():
    user = _service_key_user(uuid4())

    params = ResourceTaskParams(id=uuid4(), **task_actor(user))

    assert params.user_id is None
    assert params.service_principal_id == user.active_api_key.service_principal_id
    assert params.api_key_id == user.active_api_key.id
    assert params.tenant_id == user.tenant_id


def test_params_queued_before_services_could_own_jobs_still_load():
    user_id = uuid4()

    params = TaskParams.model_validate({"user_id": str(user_id)})

    assert params.user_id == user_id
    assert params.service_principal_id is None


def test_a_job_does_not_run_as_a_person_and_a_service_at_once():
    with pytest.raises(ValidationError):
        TaskParams(
            user_id=uuid4(),
            service_principal_id=uuid4(),
            api_key_id=uuid4(),
            tenant_id=uuid4(),
        )


@pytest.mark.parametrize("missing", ["api_key_id", "tenant_id"])
def test_a_service_job_names_its_key_and_its_organisation(missing):
    fields = {
        "service_principal_id": uuid4(),
        "api_key_id": uuid4(),
        "tenant_id": uuid4(),
    }
    fields[missing] = None

    with pytest.raises(ValidationError):
        TaskParams(**fields)


def test_params_match_only_their_own_owner():
    person_id, principal_id = uuid4(), uuid4()
    persons = TaskParams(user_id=person_id)
    services = TaskParams(
        service_principal_id=principal_id, api_key_id=uuid4(), tenant_id=uuid4()
    )

    assert persons.same_actor(person_id, None)
    assert not persons.same_actor(uuid4(), None)
    assert not persons.same_actor(None, principal_id)
    assert services.same_actor(None, principal_id)
    assert not services.same_actor(None, uuid4())
    assert not services.same_actor(person_id, None)
