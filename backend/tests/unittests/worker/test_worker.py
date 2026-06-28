from uuid import uuid4

from eneo.worker.worker import _job_id_from_ctx


def test_job_id_from_ctx_returns_uuid_from_uuid_value():
    job_id = uuid4()

    assert _job_id_from_ctx({"job_id": job_id}) == job_id


def test_job_id_from_ctx_parses_uuid_strings():
    job_id = uuid4()

    assert _job_id_from_ctx({"job_id": str(job_id)}) == job_id


def test_job_id_from_ctx_returns_none_for_invalid_ids():
    assert _job_id_from_ctx({"job_id": "arq:cron:job"}) is None
