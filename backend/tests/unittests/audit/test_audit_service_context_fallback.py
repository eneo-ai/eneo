"""Unit tests for audit_service falling back to per-request contextvars."""

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.audit.application.audit_service import AuditService, _fill_request_context
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.main.request_context import (
    clear_request_context,
    set_request_context,
)


@pytest.fixture(autouse=True)
def reset_context():
    clear_request_context()
    yield
    clear_request_context()


def test_fill_returns_explicit_values_when_all_provided():
    request_id = uuid4()
    set_request_context(
        ip_address="9.9.9.9", user_agent="ctx-agent", request_id=uuid4()
    )

    ip, ua, req = _fill_request_context("1.2.3.4", "explicit-agent", request_id)

    assert ip == "1.2.3.4"
    assert ua == "explicit-agent"
    assert req == request_id


def test_fill_falls_back_to_contextvars_for_missing_fields():
    ctx_request_id = uuid4()
    set_request_context(
        ip_address="10.0.0.5",
        user_agent="middleware-agent",
        request_id=ctx_request_id,
    )

    ip, ua, req = _fill_request_context(None, None, None)

    assert ip == "10.0.0.5"
    assert ua == "middleware-agent"
    assert req == ctx_request_id


def test_fill_returns_none_when_context_is_empty():
    ip, ua, req = _fill_request_context(None, None, None)

    assert ip is None
    assert ua is None
    assert req is None


def test_fill_mixes_explicit_and_contextvar_values():
    set_request_context(ip_address="172.16.0.1", user_agent="from-ctx")

    ip, ua, req = _fill_request_context("203.0.113.5", None, None)

    assert ip == "203.0.113.5"  # explicit wins
    assert ua == "from-ctx"  # filled from context
    assert req is None  # absent from both


@pytest.mark.asyncio
async def test_log_async_picks_up_context_when_kwargs_omitted(monkeypatch):
    """Calling log_async without ip/ua/request_id reads them from contextvars."""

    enqueued: dict = {}

    async def fake_enqueue(task, job_id, params):  # noqa: ARG001
        enqueued.update(params)

    monkeypatch.setattr(
        "eneo.audit.application.audit_service.job_manager.enqueue", fake_enqueue
    )

    request_id = UUID("550e8400-e29b-41d4-a716-446655440000")
    set_request_context(
        ip_address="198.51.100.7",
        user_agent="probe/2.0",
        request_id=request_id,
    )

    repo = AsyncMock()
    service = AuditService(repository=repo)

    tenant_id = uuid4()
    actor_id = uuid4()
    entity_id = uuid4()

    await service.log_async(
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=ActionType.ASSISTANT_CREATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=entity_id,
        description="probe",
        metadata={},
    )

    assert enqueued["ip_address"] == "198.51.100.7"
    assert enqueued["user_agent"] == "probe/2.0"
    assert enqueued["request_id"] == str(request_id)


@pytest.mark.asyncio
async def test_log_async_writes_null_when_context_is_empty(monkeypatch):
    """Worker / migration paths have no contextvars and must write NULL."""

    enqueued: dict = {}

    async def fake_enqueue(task, job_id, params):  # noqa: ARG001
        enqueued.update(params)

    monkeypatch.setattr(
        "eneo.audit.application.audit_service.job_manager.enqueue", fake_enqueue
    )

    repo = AsyncMock()
    service = AuditService(repository=repo)

    await service.log_async(
        tenant_id=uuid4(),
        actor_id=uuid4(),
        action=ActionType.ASSISTANT_CREATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=uuid4(),
        description="worker probe",
        metadata={},
    )

    assert enqueued["ip_address"] is None
    assert enqueued["user_agent"] is None
    assert enqueued["request_id"] is None


@pytest.mark.asyncio
async def test_log_async_explicit_kwargs_override_contextvars(monkeypatch):
    enqueued: dict = {}

    async def fake_enqueue(task, job_id, params):  # noqa: ARG001
        enqueued.update(params)

    monkeypatch.setattr(
        "eneo.audit.application.audit_service.job_manager.enqueue", fake_enqueue
    )

    set_request_context(
        ip_address="10.0.0.5",
        user_agent="from-ctx",
        request_id=uuid4(),
    )

    repo = AsyncMock()
    service = AuditService(repository=repo)

    explicit_request_id = UUID("11111111-1111-1111-1111-111111111111")
    await service.log_async(
        tenant_id=uuid4(),
        actor_id=uuid4(),
        action=ActionType.ASSISTANT_CREATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=uuid4(),
        description="explicit",
        metadata={},
        ip_address="1.2.3.4",
        user_agent="explicit-agent",
        request_id=explicit_request_id,
    )

    assert enqueued["ip_address"] == "1.2.3.4"
    assert enqueued["user_agent"] == "explicit-agent"
    assert enqueued["request_id"] == str(explicit_request_id)


@pytest.mark.asyncio
async def test_log_async_skips_when_should_log_returns_false(monkeypatch):
    """Sanity: contextvar fallback does not interfere with the should_log gate."""

    enqueued: dict = {}

    async def fake_enqueue(task, job_id, params):  # noqa: ARG001
        enqueued.update(params)

    monkeypatch.setattr(
        "eneo.audit.application.audit_service.job_manager.enqueue", fake_enqueue
    )

    repo = AsyncMock()
    service = AuditService(repository=repo)
    monkeypatch.setattr(service, "_should_log_action", AsyncMock(return_value=False))

    set_request_context(ip_address="9.9.9.9")

    job_id = await service.log_async(
        tenant_id=uuid4(),
        actor_id=uuid4(),
        action=ActionType.ASSISTANT_CREATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=uuid4(),
        description="filtered",
        metadata={},
    )

    assert job_id is None
    assert enqueued == {}


@pytest.mark.asyncio
async def test_log_async_swallows_redis_enqueue_failure(monkeypatch, caplog):
    """Audit is best-effort: a Redis/ARQ enqueue exception must not propagate.

    Otherwise a transient Redis outage would 500 every mutation that audits,
    turning a partial degradation into a full one. The handler should log a
    warning and return None so callers continue without noticing.
    """
    import logging

    async def fake_enqueue(task, job_id, params):  # noqa: ARG001
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr(
        "eneo.audit.application.audit_service.job_manager.enqueue", fake_enqueue
    )

    repo = AsyncMock()
    service = AuditService(repository=repo)

    caplog.set_level(logging.WARNING, logger="eneo.audit.application.audit_service")

    job_id = await service.log_async(
        tenant_id=uuid4(),
        actor_id=uuid4(),
        action=ActionType.ASSISTANT_CREATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=uuid4(),
        description="probe",
        metadata={},
    )

    assert job_id is None
    assert any(
        "Failed to enqueue audit event" in record.message
        and record.levelname == "WARNING"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_log_persists_contextvars_through_repository(monkeypatch):
    """The sync log() method also reads contextvars."""

    request_id = UUID("550e8400-e29b-41d4-a716-446655440000")
    set_request_context(
        ip_address="203.0.113.10",
        user_agent="sync-agent",
        request_id=request_id,
    )

    repo = AsyncMock()
    repo.create = AsyncMock(side_effect=lambda log: log)
    service = AuditService(repository=repo)

    result = await service.log(
        tenant_id=uuid4(),
        actor_id=uuid4(),
        action=ActionType.ASSISTANT_CREATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=uuid4(),
        description="sync probe",
        metadata={},
        actor_type=ActorType.USER,
    )

    assert result is not None
    assert result.ip_address == "203.0.113.10"
    assert result.user_agent == "sync-agent"
    assert result.request_id == request_id
