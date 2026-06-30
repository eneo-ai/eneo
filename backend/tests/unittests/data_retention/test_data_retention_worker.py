from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import cast

import pytest

from intric.data_retention.infrastructure import data_retention_worker
from intric.data_retention.infrastructure.data_retention_service import (
    RETENTION_BATCH_SIZE,
    FlowDebugRedactionCounts,
    FlowRunHistoryPurgeBlockedCounts,
    FlowRunHistoryPurgeCounts,
    FlowTemplateAssetPurgeCounts,
)


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
        purge_batches: list[FlowRunHistoryPurgeCounts | Exception] | None = None,
    ) -> None:
        self.purge_batches = purge_batches or [
            FlowRunHistoryPurgeCounts(
                flow_runs_purged=2,
                flow_generated_files_deleted=3,
                flow_webhook_deliveries_deleted=5,
                flow_audit_outbox_rows_deleted=7,
                flow_review_checkpoints_deleted=11,
            ),
            FlowRunHistoryPurgeCounts(
                flow_runs_purged=1,
                flow_generated_files_deleted=13,
                flow_webhook_deliveries_deleted=17,
                flow_audit_outbox_rows_deleted=19,
                flow_review_checkpoints_deleted=23,
            ),
            FlowRunHistoryPurgeCounts(),
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
    ) -> FlowRunHistoryPurgeCounts:
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
):
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
    assert result["deleted"]["flow_runs_purged"] == 3
    assert result["deleted"]["flow_generated_files_deleted"] == 16
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
    assert result["deleted"]["flow_runs_skipped_active_rerun"] == 37
    assert result["deleted"]["total"] == 225
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
):
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
            FlowRunHistoryPurgeCounts(
                flow_runs_purged=2,
                flow_generated_files_deleted=3,
            ),
            RuntimeError("purge exploded"),
        ]
    )
    container = _Container(service=service)

    result = await cleanup_old_data(container=container)

    assert result["success"] is False
    assert result["errors"] == [
        "Failed to purge old Flow run history batch: purge exploded"
    ]
    assert result["deleted"]["flow_runs_purged"] == 2
    assert result["deleted"]["flow_generated_files_deleted"] == 3
    assert result["deleted"]["flow_template_assets_purged"] == 29
    assert result["deleted"]["flow_template_asset_files_deleted"] == 31
    assert result["deleted"]["builder_sessions"] == 13
    assert result["deleted"]["flow_runs_skipped_undelivered_audit"] == 0
    assert result["deleted"]["flow_runs_skipped_active_rerun"] == 0
    assert result["deleted"]["flow_debug_rows"] == 7
    assert result["deleted"]["flow_attempt_provenance"] == 11
    assert result["deleted"]["flow_audit_outbox_delivered_rows"] == 23
    assert service.blocked_now_values == []
    assert session.transaction_count == 9
    assert container.session.reset_count == 1
