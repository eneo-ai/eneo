from __future__ import annotations

import contextlib
import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from eneo.data_retention.infrastructure import data_retention_worker
from eneo.data_retention.infrastructure.data_retention_service import (
    RETENTION_BATCH_SIZE,
    FlowDebugRedactionCounts,
    FlowRunHistoryPurgeBlockedCounts,
    FlowTemplateAssetPurgeCounts,
)
from eneo.flows.infrastructure.flow_run_history_purge_repo import (
    FlowRunHistoryPurgeCounts,
    FlowRunHistoryPurgeResult,
)

_SENSITIVE_FLOW_ID = uuid4()
_SENSITIVE_TENANT_ID = uuid4()
_SENSITIVE_FILE_ID = uuid4()
_SENSITIVE_PAYLOAD = "confidential runtime source payload"


class _TransactionContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


class _Session:
    def __init__(self) -> None:
        self.transaction_count = 0

    def begin(self) -> _TransactionContext:
        self.transaction_count += 1
        return _TransactionContext()


class _SessionProvider:
    def __init__(self) -> None:
        self.override_value: object | None = None
        self.reset_count = 0

    def override(self, value: object) -> None:
        self.override_value = value

    def reset_override(self) -> None:
        self.reset_count += 1
        self.override_value = None


class _DataRetentionService:
    def __init__(
        self,
        *,
        purge_batches: list[FlowRunHistoryPurgeResult | Exception] | None = None,
    ) -> None:
        self.purge_batches = purge_batches or [
            FlowRunHistoryPurgeResult(
                counts=FlowRunHistoryPurgeCounts(
                    flow_runs_considered=2,
                    flow_runs_purged=2,
                    flow_generated_files_deleted=3,
                    flow_runtime_source_candidates=5,
                    flow_runtime_source_candidate_bytes=500,
                    flow_runtime_source_bindings_deleted=2,
                    flow_runtime_source_files_deleted=1,
                    flow_runtime_source_bytes_deleted=100,
                    flow_webhook_deliveries_deleted=5,
                    flow_audit_outbox_rows_deleted=7,
                    flow_review_checkpoints_deleted=11,
                ),
                affected_flow_tenant_ids=frozenset(
                    {(_SENSITIVE_FLOW_ID, _SENSITIVE_TENANT_ID)}
                ),
            ),
            FlowRunHistoryPurgeResult(
                counts=FlowRunHistoryPurgeCounts(
                    flow_runs_considered=1,
                    flow_runs_purged=1,
                    flow_generated_files_deleted=13,
                    flow_runtime_source_candidates=7,
                    flow_runtime_source_candidate_bytes=700,
                    flow_runtime_source_bindings_deleted=3,
                    flow_runtime_source_files_deleted=2,
                    flow_runtime_source_bytes_deleted=200,
                    flow_webhook_deliveries_deleted=17,
                    flow_audit_outbox_rows_deleted=19,
                    flow_review_checkpoints_deleted=23,
                ),
                affected_flow_tenant_ids=frozenset(
                    {(_SENSITIVE_FLOW_ID, _SENSITIVE_TENANT_ID)}
                ),
            ),
            FlowRunHistoryPurgeResult(),
        ]
        self.purge_now_values: list[datetime] = []
        self.purge_limits: list[int] = []
        self.template_asset_purge_limits: list[int] = []
        self.blocked_now_values: list[datetime] = []
        self.redaction_now_values: list[datetime] = []
        self.builder_now_values: list[datetime] = []

    async def delete_old_questions(self) -> int:
        return 2

    async def delete_old_app_runs(self) -> int:
        return 3

    async def delete_old_sessions(self) -> int:
        return 5

    async def delete_expired_builder_sessions(self, *, now: datetime) -> int:
        self.builder_now_values.append(now)
        return 13

    async def purge_old_flow_run_history_batch(
        self, *, now: datetime, limit: int
    ) -> FlowRunHistoryPurgeResult:
        self.purge_now_values.append(now)
        self.purge_limits.append(limit)
        next_batch = self.purge_batches.pop(0)
        if isinstance(next_batch, Exception):
            raise next_batch
        return next_batch

    async def purge_soft_deleted_flow_template_assets(
        self, *, limit: int
    ) -> FlowTemplateAssetPurgeCounts:
        self.template_asset_purge_limits.append(limit)
        return FlowTemplateAssetPurgeCounts(
            flow_template_assets_purged=29,
            flow_template_asset_files_deleted=31,
            flow_template_assets_skipped_published_reference=41,
            flow_template_assets_skipped_undetermined_reference=43,
        )

    async def count_blocked_flow_run_history_purge_candidates(
        self, *, now: datetime
    ) -> FlowRunHistoryPurgeBlockedCounts:
        self.blocked_now_values.append(now)
        return FlowRunHistoryPurgeBlockedCounts(
            skipped_undelivered_audit=31,
            skipped_unresolved_webhook=41,
            skipped_active_rerun=37,
        )

    async def redact_old_flow_debug_evidence(
        self, *, now: datetime
    ) -> FlowDebugRedactionCounts:
        self.redaction_now_values.append(now)
        return FlowDebugRedactionCounts(
            debug_step_results=7,
            debug_step_attempts=11,
        )

    async def delete_old_delivered_flow_audit_outbox_rows(self) -> int:
        return 23


class _Container:
    def __init__(self, service: _DataRetentionService | None = None) -> None:
        self.session = _SessionProvider()
        self._service = service or _DataRetentionService()

    def data_retention_service(self) -> _DataRetentionService:
        return self._service


@pytest.mark.asyncio
async def test_cleanup_old_data_runs_flow_purge_batches_in_separate_transactions(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setattr(data_retention_worker.logger, "disabled", False)
    monkeypatch.setattr(data_retention_worker.logger, "propagate", True)
    caplog.set_level(logging.INFO, logger=data_retention_worker.logger.name)
    session = _Session()

    @contextlib.asynccontextmanager
    async def session_context() -> AsyncIterator[_Session]:
        yield session

    monkeypatch.setattr(
        data_retention_worker.sessionmanager, "session", session_context
    )

    cleanup_old_data = cast(
        Callable[..., Awaitable[data_retention_worker.CleanupResults]],
        getattr(data_retention_worker.cleanup_old_data, "__wrapped__"),
    )
    container = _Container()
    service = container._service

    result = await cleanup_old_data(container=container)
    expected_independent_cleanup_transactions = 11

    assert result["success"] is True
    assert result["deleted"]["builder_sessions"] == 13
    assert result["deleted"]["flow_audit_outbox_delivered_rows"] == 23
    assert result["deleted"]["flow_runs_considered"] == 3
    assert result["deleted"]["flow_runs_lock_deferred"] == 0
    assert result["deleted"]["flow_runs_purged"] == 3
    assert result["deleted"]["flow_generated_files_deleted"] == 16
    assert result["deleted"]["flow_runtime_source_candidates"] == 12
    assert result["deleted"]["flow_runtime_source_candidate_bytes"] == 1200
    assert result["deleted"]["flow_runtime_source_bindings_deleted"] == 5
    assert result["deleted"]["flow_runtime_source_files_deleted"] == 3
    assert result["deleted"]["flow_runtime_source_bytes_deleted"] == 300
    assert result["deleted"]["flow_webhook_deliveries_deleted"] == 22
    assert result["deleted"]["flow_audit_outbox_rows_deleted"] == 26
    assert result["deleted"]["flow_review_checkpoints_deleted"] == 34
    assert result["deleted"]["flow_template_assets_purged"] == 29
    assert result["deleted"]["flow_template_asset_files_deleted"] == 31
    assert result["deleted"]["flow_template_assets_skipped_published_reference"] == 41
    assert (
        result["deleted"]["flow_template_assets_skipped_undetermined_reference"] == 43
    )
    assert result["deleted"]["flow_runs_skipped_undelivered_audit"] == 31
    assert result["deleted"]["flow_runs_skipped_unresolved_webhook"] == 41
    assert result["deleted"]["flow_runs_skipped_active_rerun"] == 37
    assert result["deleted"]["total"] == 233
    assert "flow_runtime_source_candidate_bytes: 1200" in caplog.text
    assert "flow_runtime_source_bytes_deleted: 300" in caplog.text
    assert "flow_runs_considered: 3" in caplog.text
    assert "flow_runs_lock_deferred: 0" in caplog.text
    assert "flow_runs_skipped_unresolved_webhook: 41" in caplog.text
    assert str(_SENSITIVE_FLOW_ID) not in caplog.text
    assert str(_SENSITIVE_TENANT_ID) not in caplog.text
    assert session.transaction_count == expected_independent_cleanup_transactions
    assert container.session.reset_count == 1
    assert service.purge_limits == [RETENTION_BATCH_SIZE] * 3
    assert service.template_asset_purge_limits == [RETENTION_BATCH_SIZE]
    all_flow_runtime_now_values = (
        service.purge_now_values
        + service.blocked_now_values
        + service.redaction_now_values
    )
    assert len(set(all_flow_runtime_now_values)) == 1
    assert service.builder_now_values == service.purge_now_values[:1]


@pytest.mark.asyncio
async def test_cleanup_old_data_preserves_committed_flow_purge_counts_after_later_batch_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setattr(data_retention_worker.logger, "disabled", False)
    monkeypatch.setattr(data_retention_worker.logger, "propagate", True)
    caplog.set_level(logging.INFO, logger=data_retention_worker.logger.name)
    session = _Session()

    @contextlib.asynccontextmanager
    async def session_context() -> AsyncIterator[_Session]:
        yield session

    monkeypatch.setattr(
        data_retention_worker.sessionmanager, "session", session_context
    )

    cleanup_old_data = cast(
        Callable[..., Awaitable[data_retention_worker.CleanupResults]],
        getattr(data_retention_worker.cleanup_old_data, "__wrapped__"),
    )
    service = _DataRetentionService(
        purge_batches=[
            FlowRunHistoryPurgeResult(
                counts=FlowRunHistoryPurgeCounts(
                    flow_runs_considered=2,
                    flow_runs_purged=2,
                    flow_generated_files_deleted=3,
                    flow_runtime_source_candidates=5,
                    flow_runtime_source_candidate_bytes=500,
                    flow_runtime_source_bindings_deleted=2,
                    flow_runtime_source_files_deleted=1,
                    flow_runtime_source_bytes_deleted=100,
                )
            ),
            DBAPIError(
                statement="DELETE FROM files WHERE id = ANY(:file_ids)",
                params={
                    "file_ids": [_SENSITIVE_FILE_ID],
                    "flow_id": _SENSITIVE_FLOW_ID,
                    "tenant_id": _SENSITIVE_TENANT_ID,
                },
                orig=RuntimeError(_SENSITIVE_PAYLOAD),
                connection_invalidated=False,
            ),
        ]
    )
    container = _Container(service=service)

    result = await cleanup_old_data(container=container)

    assert result["success"] is False
    assert result["errors"] == [
        "Failed to purge old Flow run history batch: DBAPIError"
    ]
    assert result["deleted"]["flow_runs_considered"] == 2
    assert result["deleted"]["flow_runs_lock_deferred"] == 0
    assert result["deleted"]["flow_runs_purged"] == 2
    assert result["deleted"]["flow_generated_files_deleted"] == 3
    assert result["deleted"]["flow_runtime_source_candidates"] == 5
    assert result["deleted"]["flow_runtime_source_candidate_bytes"] == 500
    assert result["deleted"]["flow_runtime_source_bindings_deleted"] == 2
    assert result["deleted"]["flow_runtime_source_files_deleted"] == 1
    assert result["deleted"]["flow_runtime_source_bytes_deleted"] == 100
    assert result["deleted"]["flow_template_assets_purged"] == 29
    assert result["deleted"]["flow_template_asset_files_deleted"] == 31
    assert result["deleted"]["builder_sessions"] == 13
    assert result["deleted"]["flow_runs_skipped_undelivered_audit"] == 0
    assert result["deleted"]["flow_runs_skipped_unresolved_webhook"] == 0
    assert result["deleted"]["flow_runs_skipped_active_rerun"] == 0
    assert result["deleted"]["flow_debug_rows"] == 7
    assert result["deleted"]["flow_attempt_provenance"] == 11
    assert result["deleted"]["flow_audit_outbox_delivered_rows"] == 23
    sanitized_output = "\n".join((*result["errors"], caplog.text))
    assert str(_SENSITIVE_FILE_ID) not in sanitized_output
    assert str(_SENSITIVE_FLOW_ID) not in sanitized_output
    assert str(_SENSITIVE_TENANT_ID) not in sanitized_output
    assert _SENSITIVE_PAYLOAD not in sanitized_output
    assert "DELETE FROM files" not in sanitized_output
    assert service.blocked_now_values == []
    assert session.transaction_count == 9
    assert container.session.reset_count == 1


@pytest.mark.asyncio
async def test_cleanup_old_data_reports_lock_deferred_page_without_polling(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(data_retention_worker.logger, "disabled", False)
    monkeypatch.setattr(data_retention_worker.logger, "propagate", True)
    caplog.set_level(logging.INFO, logger=data_retention_worker.logger.name)
    session = _Session()

    @contextlib.asynccontextmanager
    async def session_context() -> AsyncIterator[_Session]:
        yield session

    monkeypatch.setattr(
        data_retention_worker.sessionmanager, "session", session_context
    )
    cleanup_old_data = inspect.unwrap(data_retention_worker.cleanup_old_data)
    service = _DataRetentionService(
        purge_batches=[
            FlowRunHistoryPurgeResult(
                counts=FlowRunHistoryPurgeCounts(
                    flow_runs_considered=1,
                    flow_runs_lock_deferred=1,
                )
            ),
            FlowRunHistoryPurgeResult(
                counts=FlowRunHistoryPurgeCounts(
                    flow_runs_considered=1,
                    flow_runs_purged=1,
                )
            ),
        ]
    )
    container = _Container(service=service)

    result = await cleanup_old_data(container=container)

    assert result["success"] is True
    assert result["deleted"]["flow_runs_considered"] == 1
    assert result["deleted"]["flow_runs_lock_deferred"] == 1
    assert result["deleted"]["flow_runs_purged"] == 0
    assert service.purge_limits == [RETENTION_BATCH_SIZE]
    assert service.blocked_now_values == []
    assert "concurrent locks (count=1)" in caplog.text
