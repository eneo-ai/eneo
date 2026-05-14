from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import intric.worker.crawl.circuit_breaker as circuit_breaker_module
from intric.websites.domain.website import (
    WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
    UpdateInterval,
)
from intric.worker.crawl.circuit_breaker import update_crawl_circuit_breaker


class _FakeExecuteResult:
    rowcount = 1


class _FakeSession:
    def __init__(self, *, current_failures: int | None = None) -> None:
        self.current_failures = current_failures
        self.executed: list[object] = []
        self.scalar_statements: list[object] = []

    async def execute(self, stmt: object) -> _FakeExecuteResult:
        self.executed.append(stmt)
        return _FakeExecuteResult()

    async def scalar(self, stmt: object) -> int | None:
        self.scalar_statements.append(stmt)
        return self.current_failures


def _compiled_params(stmt: object) -> dict[str, object]:
    compile_stmt = getattr(stmt, "compile", None)
    assert callable(compile_stmt)
    params = compile_stmt().params
    assert isinstance(params, Mapping)
    return dict(params)


@pytest.mark.asyncio
async def test_successful_crawl_resets_circuit_breaker() -> None:
    website_id = uuid4()
    tenant_id = uuid4()
    session = _FakeSession()

    await update_crawl_circuit_breaker(
        session,
        website_id=website_id,
        tenant_id=tenant_id,
        website_url="https://example.com",
        crawl_successful=True,
    )

    assert session.scalar_statements == []
    assert len(session.executed) == 1
    params = _compiled_params(session.executed[0])
    assert params["id_1"] == website_id
    assert params["tenant_id_1"] == tenant_id
    assert params["consecutive_failures"] == 0
    assert params["next_retry_at"] is None


@pytest.mark.asyncio
async def test_failed_crawl_increments_failures_and_sets_bounded_backoff() -> None:
    website_id = uuid4()
    tenant_id = uuid4()
    observed_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    session = _FakeSession(current_failures=2)

    await update_crawl_circuit_breaker(
        session,
        website_id=website_id,
        tenant_id=tenant_id,
        website_url="https://example.com",
        crawl_successful=False,
        observed_at=observed_at,
    )

    assert len(session.scalar_statements) == 1
    assert len(session.executed) == 1
    params = _compiled_params(session.executed[0])
    assert params["id_1"] == website_id
    assert params["tenant_id_1"] == tenant_id
    assert params["consecutive_failures"] == 3
    assert params["next_retry_at"] == observed_at + timedelta(hours=4)


@pytest.mark.asyncio
async def test_first_failed_crawl_sets_one_hour_backoff_from_observed_time() -> None:
    website_id = uuid4()
    tenant_id = uuid4()
    observed_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    session = _FakeSession(current_failures=None)

    await update_crawl_circuit_breaker(
        session,
        website_id=website_id,
        tenant_id=tenant_id,
        website_url="https://example.com",
        crawl_successful=False,
        observed_at=observed_at,
    )

    assert len(session.scalar_statements) == 1
    assert len(session.executed) == 1
    params = _compiled_params(session.executed[0])
    assert params["consecutive_failures"] == 1
    assert params["next_retry_at"] == observed_at + timedelta(hours=1)


@pytest.mark.asyncio
async def test_failed_crawl_backoff_is_capped_at_twenty_four_hours() -> None:
    website_id = uuid4()
    tenant_id = uuid4()
    observed_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    session = _FakeSession(current_failures=5)

    await update_crawl_circuit_breaker(
        session,
        website_id=website_id,
        tenant_id=tenant_id,
        website_url="https://example.com",
        crawl_successful=False,
        observed_at=observed_at,
    )

    assert len(session.scalar_statements) == 1
    assert len(session.executed) == 1
    params = _compiled_params(session.executed[0])
    assert params["consecutive_failures"] == 6
    assert params["next_retry_at"] == observed_at + timedelta(hours=24)


@pytest.mark.asyncio
async def test_failed_crawl_below_threshold_keeps_backoff_branch() -> None:
    website_id = uuid4()
    tenant_id = uuid4()
    observed_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    session = _FakeSession(current_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD - 2)

    await update_crawl_circuit_breaker(
        session,
        website_id=website_id,
        tenant_id=tenant_id,
        website_url="https://example.com",
        crawl_successful=False,
        observed_at=observed_at,
    )

    assert len(session.scalar_statements) == 1
    assert len(session.executed) == 1
    params = _compiled_params(session.executed[0])
    assert params["consecutive_failures"] == WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD - 1
    assert "update_interval" not in params
    assert params["next_retry_at"] == observed_at + timedelta(hours=24)


@pytest.mark.asyncio
async def test_failed_crawl_auto_disables_at_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website_id = uuid4()
    tenant_id = uuid4()
    session = _FakeSession(current_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD - 1)
    mock_logger = MagicMock()
    monkeypatch.setattr(circuit_breaker_module, "logger", mock_logger)

    await update_crawl_circuit_breaker(
        session,
        website_id=website_id,
        tenant_id=tenant_id,
        website_url="https://example.com",
        crawl_successful=False,
    )

    assert len(session.scalar_statements) == 1
    assert len(session.executed) == 1
    params = _compiled_params(session.executed[0])
    assert params["id_1"] == website_id
    assert params["tenant_id_1"] == tenant_id
    assert params["consecutive_failures"] == WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD
    assert params["update_interval"] == UpdateInterval.NEVER
    assert params["next_retry_at"] is None
    mock_logger.error.assert_called_once()
    message = mock_logger.error.call_args.args[0]
    assert "auto-disabled" in message
    assert mock_logger.error.call_args.kwargs["extra"] == {
        "website_id": str(website_id),
        "url": "https://example.com",
        "consecutive_failures": WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
    }
