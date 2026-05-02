from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import cast

import pytest

from intric.data_retention.infrastructure import data_retention_worker
from intric.data_retention.infrastructure.data_retention_service import (
    FlowRuntimeCleanupCounts,
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
    async def delete_old_questions(self) -> int:
        return 2

    async def delete_old_app_runs(self) -> int:
        return 3

    async def delete_old_sessions(self) -> int:
        return 5

    async def cleanup_old_flow_runtime_data(
        self,
    ) -> FlowRuntimeCleanupCounts:
        return {
            "debug_step_results": 7,
            "debug_step_attempts": 11,
            "generated_artifact_rows": 13,
            "generated_artifact_files": 17,
            "reconciled_artifact_references": 19,
        }

    async def delete_old_delivered_flow_audit_outbox_rows(self) -> int:
        return 23


class _Container:
    def __init__(self) -> None:
        self.session = _SessionProvider()
        self._service = _DataRetentionService()

    def data_retention_service(self) -> _DataRetentionService:
        return self._service


@pytest.mark.asyncio
async def test_cleanup_old_data_reports_delivered_flow_audit_outbox_rows(
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

    result = await cleanup_old_data(container=container)
    expected_independent_cleanup_transactions = 5

    assert result["success"] is True
    assert result["deleted"]["flow_audit_outbox_delivered_rows"] == 23
    assert result["deleted"]["total"] == 100
    assert session.transaction_count == expected_independent_cleanup_transactions
    assert container.session.reset_count == 1
