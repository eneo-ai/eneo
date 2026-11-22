from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.audit.application import export_worker_task
from eneo.audit.application.audit_task_params import AuditExportTaskParams
from tests.log_capture import chained_error, emitted, logged_errors


class _FailingExport:
    def __init__(self, repository: object) -> None:
        del repository

    async def stream_export_to_file(self, **_: object) -> int:
        raise chained_error()


async def test_a_failed_export_logs_the_kind_of_error_not_its_text(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    """An export's error can quote the audit rows it was writing. Mutant: the
    job's failure is logged with its message or traceback."""
    monkeypatch.setattr(
        export_worker_task,
        "get_settings",
        lambda: SimpleNamespace(export_dir=tmp_path),
    )
    monkeypatch.setattr(export_worker_task, "AuditExportService", _FailingExport)
    monkeypatch.setattr(
        export_worker_task, "ExportJobManager", lambda redis: AsyncMock()
    )

    with emitted(export_worker_task.logger) as records:
        result = await export_worker_task.export_audit_logs_task(
            job_id=uuid4(),
            params=AuditExportTaskParams(tenant_id=uuid4()),
            session=MagicMock(),
            redis=MagicMock(),
        )

    assert result["status"] == "failed"
    assert logged_errors(records), [record.getMessage() for record in records]
