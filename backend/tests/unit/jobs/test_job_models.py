from uuid import uuid4

from eneo.jobs.job_models import Job, Task
from eneo.main.models import Status


def _job(**owner) -> Job:
    return Job(task=Task.RUN_APP, status=Status.QUEUED, **owner)


def test_a_persons_job_belongs_to_that_person_only():
    person_id = uuid4()
    job = _job(user_id=person_id)

    assert job.owned_by(person_id, None)
    assert not job.owned_by(uuid4(), None)
    assert not job.owned_by(None, uuid4())


def test_a_service_principals_job_belongs_to_that_principal_whatever_the_key():
    principal_id = uuid4()
    job = _job(service_principal_id=principal_id, api_key_id=uuid4())

    assert job.owned_by(None, principal_id)
    assert not job.owned_by(None, uuid4())
    assert not job.owned_by(uuid4(), None)


def test_a_job_without_an_owner_belongs_to_nobody():
    job = _job()

    assert not job.owned_by(None, None)
    assert not job.owned_by(uuid4(), None)
    assert not job.owned_by(None, uuid4())
