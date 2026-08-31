from __future__ import annotations

import contextlib
import inspect
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Never

import pytest

from eneo.data_retention.infrastructure import data_retention_worker


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
    def __init__(self, *, app_runs_error: Exception | None = None) -> None:
        self.app_runs_error = app_runs_error
        self.builder_client_error_now_values: list[datetime] = []
        self.flow_destructive_calls: list[str] = []

    async def delete_old_questions(self) -> int:
        return 2

    async def delete_old_app_runs(self) -> int:
        if self.app_runs_error is not None:
            raise self.app_runs_error
        return 3

    async def delete_old_sessions(self) -> int:
        return 5

    async def delete_expired_builder_client_errors_batch(self, *, now: datetime) -> int:
        self.builder_client_error_now_values.append(now)
        return 2 if len(self.builder_client_error_now_values) <= 2 else 0

    def _reject_flow_destructive_call(self, name: str) -> Never:
        self.flow_destructive_calls.append(name)
        raise AssertionError(f"Scheduled cleanup called {name}")

    async def purge_old_flow_run_history_batch(self, **_: object) -> Never:
        self._reject_flow_destructive_call("purge_old_flow_run_history_batch")

    async def count_blocked_flow_run_history_purge_candidates(
        self, **_: object
    ) -> Never:
        self._reject_flow_destructive_call(
            "count_blocked_flow_run_history_purge_candidates"
        )

    async def purge_abandoned_flow_runtime_uploads(self, **_: object) -> Never:
        self._reject_flow_destructive_call("purge_abandoned_flow_runtime_uploads")

    async def purge_soft_deleted_flow_template_assets(self, **_: object) -> Never:
        self._reject_flow_destructive_call("purge_soft_deleted_flow_template_assets")

    async def redact_old_flow_debug_evidence(self, **_: object) -> Never:
        self._reject_flow_destructive_call("redact_old_flow_debug_evidence")

    async def delete_old_delivered_flow_audit_outbox_rows(self) -> Never:
        self._reject_flow_destructive_call(
            "delete_old_delivered_flow_audit_outbox_rows"
        )


class _Container:
    def __init__(self, service: _DataRetentionService | None = None) -> None:
        self.session = _SessionProvider()
        self._service = service or _DataRetentionService()

    def data_retention_service(self) -> _DataRetentionService:
        return self._service


@pytest.mark.asyncio
async def test_cleanup_old_data_preserves_builder_sessions_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()

    @contextlib.asynccontextmanager
    async def session_context() -> AsyncIterator[_Session]:
        yield session

    monkeypatch.setattr(
        data_retention_worker.sessionmanager, "session", session_context
    )
    cleanup_old_data = inspect.unwrap(data_retention_worker.cleanup_old_data)
    container = _Container()
    service = container._service

    result = await cleanup_old_data(container=container)

    assert result["success"] is True
    assert result["deleted"] == {
        "questions": 2,
        "app_runs": 3,
        "sessions": 5,
        "builder_client_errors": 4,
        "total": 14,
    }
    assert service.flow_destructive_calls == []
    assert len(service.builder_client_error_now_values) == 3
    assert session.transaction_count == 6
    assert container.session.reset_count == 1


@pytest.mark.asyncio
async def test_cleanup_old_data_keeps_non_flow_partial_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()

    @contextlib.asynccontextmanager
    async def session_context() -> AsyncIterator[_Session]:
        yield session

    monkeypatch.setattr(
        data_retention_worker.sessionmanager, "session", session_context
    )
    cleanup_old_data = inspect.unwrap(data_retention_worker.cleanup_old_data)
    service = _DataRetentionService(app_runs_error=RuntimeError("sensitive value"))
    container = _Container(service=service)

    result = await cleanup_old_data(container=container)

    assert result["success"] is False
    assert result["errors"] == ["Failed to delete old app runs: RuntimeError"]
    assert result["deleted"] == {
        "questions": 2,
        "app_runs": 0,
        "sessions": 5,
        "builder_client_errors": 4,
        "total": 11,
    }
    assert "sensitive value" not in "\n".join(result["errors"])
    assert service.flow_destructive_calls == []
    assert session.transaction_count == 6
    assert container.session.reset_count == 1
