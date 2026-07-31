import asyncio
from uuid import uuid4

import pytest

from eneo.files.text import ExtractionError
from eneo.jobs.job_models import (
    JobFailureCode,
    JobInDb,
    JobPublic,
    Task,
    failure_code_for_exception,
)
from eneo.main.models import Status


@pytest.mark.parametrize(
    ("source_code", "expected"),
    [
        ("EXTRACTION_FAILED", JobFailureCode.EXTRACTION_FAILED),
        ("NO_EXTRACTABLE_TEXT", JobFailureCode.NO_EXTRACTABLE_TEXT),
        ("ENCRYPTED", JobFailureCode.ENCRYPTED),
        ("CORRUPT", JobFailureCode.CORRUPT),
        ("UNSUPPORTED_FORMAT", JobFailureCode.UNSUPPORTED_FORMAT),
    ],
)
def test_extraction_failure_codes_are_mapped_explicitly(
    source_code: str,
    expected: JobFailureCode,
) -> None:
    error = ExtractionError("internal extraction detail", code=source_code)

    assert failure_code_for_exception(error) is expected


def test_unknown_extraction_failure_uses_the_bounded_extraction_fallback() -> None:
    error = ExtractionError("internal extraction detail", code="FUTURE_DETAIL")

    assert failure_code_for_exception(error) is JobFailureCode.EXTRACTION_FAILED


def test_worker_cancellation_has_a_stable_failure_code() -> None:
    assert (
        failure_code_for_exception(asyncio.CancelledError()) is JobFailureCode.CANCELLED
    )


def test_unexpected_processing_failure_uses_one_generic_code() -> None:
    assert (
        failure_code_for_exception(RuntimeError("database password leaked here"))
        is JobFailureCode.PROCESSING_FAILED
    )


def test_public_job_exposes_the_stable_failure_code() -> None:
    job = JobPublic(
        id=uuid4(),
        name="document.pdf",
        status=Status.FAILED,
        task=Task.UPLOAD_FILE,
        failure_code=JobFailureCode.ENCRYPTED,
    )

    assert job.model_dump(mode="json")["failure_code"] == "encrypted"


def test_persisted_job_accepts_a_future_failure_code() -> None:
    job = JobInDb(
        id=uuid4(),
        user_id=uuid4(),
        name="document.pdf",
        status=Status.FAILED,
        task=Task.UPLOAD_FILE,
        failure_code="future_failure_code",
    )

    assert job.failure_code == "future_failure_code"


def test_public_job_masks_failed_knowledge_prose_and_unknown_codes() -> None:
    persisted = JobInDb(
        id=uuid4(),
        user_id=uuid4(),
        name="document.pdf",
        status=Status.FAILED,
        task=Task.UPLOAD_FILE,
        result_location="password=secret database host",
        failure_code="future_failure_code",
    )

    public = JobPublic.model_validate(persisted)

    assert public.result_location is None
    assert public.failure_code is None


def test_public_job_preserves_successful_knowledge_location() -> None:
    persisted = JobInDb(
        id=uuid4(),
        user_id=uuid4(),
        name="document.pdf",
        status=Status.COMPLETE,
        task=Task.UPLOAD_FILE,
        result_location="/api/v1/info-blobs/123/",
    )

    assert JobPublic.model_validate(persisted).result_location == (
        "/api/v1/info-blobs/123/"
    )


def test_public_job_preserves_non_knowledge_failure_details() -> None:
    persisted = JobInDb(
        id=uuid4(),
        user_id=uuid4(),
        name="intranet.example",
        status=Status.FAILED,
        task=Task.CRAWL,
        result_location="The crawl exceeded its configured time limit",
    )

    assert JobPublic.model_validate(persisted).result_location == (
        "The crawl exceeded its configured time limit"
    )
