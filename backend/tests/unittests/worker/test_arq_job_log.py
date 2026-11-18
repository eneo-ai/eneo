"""arq logs each job it runs. A job's arguments, result and error can quote
what it works on, which retention removes and a log would keep, so arq's
lines name the job and its timing only."""

import inspect
import logging

import pytest
from arq.worker import Worker as ArqWorker

from eneo.worker import arq as arq_settings

_PRIVATE = "Utredning om Anna Svensson.pdf"


def test_arq_logs_a_job_without_its_arguments_or_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    arq_logger = logging.getLogger("arq.worker")
    caplog.set_level(logging.INFO, logger="arq.worker")

    arq_logger.info(
        arq_settings.ARQ_JOB_STARTED,
        0.5,
        "job-1:upload_info_blob",
        f"UploadInfoBlob(filename='{_PRIVATE}')",
        "",
    )
    try:
        raise ValueError(f"could not read {_PRIVATE}")
    except ValueError as error:
        arq_logger.exception(
            arq_settings.ARQ_JOB_FAILED,
            1.0,
            "job-1:upload_info_blob",
            "ValueError",
            error,
            extra={"extra": None},
        )

    logged = caplog.text + "".join(repr(r.__dict__) for r in caplog.records)
    assert _PRIVATE not in logged
    started, failed = caplog.records
    assert "job-1:upload_info_blob" in started.getMessage()
    assert "job-1:upload_info_blob failed, ValueError" in failed.getMessage()
    assert failed.exc_info is None


def test_the_lines_rewritten_are_arqs_own() -> None:
    """If arq changes these lines, the filter would no longer match them."""
    source = inspect.getsource(ArqWorker.run_job)

    assert repr(arq_settings.ARQ_JOB_STARTED) in source
    assert repr(arq_settings.ARQ_JOB_FAILED) in source


def test_arq_does_not_log_a_jobs_result() -> None:
    assert arq_settings.WorkerSettings["log_results"] is False
    assert arq_settings.CrawlerWorkerSettings["log_results"] is False
