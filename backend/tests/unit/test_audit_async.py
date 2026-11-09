"""Unit tests for async audit logging."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from eneo.audit.application import audit_service as audit_service_module
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.jobs import job_manager as job_manager_module
from eneo.jobs.job_manager import JobManager
from eneo.jobs.job_models import Task
from eneo.main.config import get_settings
from tests.silent_server import freezing_redis


@pytest.mark.asyncio
async def test_log_async_enqueues_to_arq():
    """Test that log_async enqueues the audit log to ARQ."""
    # Mock the repository and job_manager
    mock_repository = MagicMock()
    mock_job_manager = AsyncMock()

    service = AuditService(mock_repository)

    # Patch job_manager
    with patch("eneo.audit.application.audit_service.job_manager", mock_job_manager):
        tenant_id = uuid4()
        actor_id = uuid4()
        entity_id = uuid4()

        job_id = await service.log_async(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=entity_id,
            description="Test async log",
            metadata={"test": True},
        )

        # Verify job_manager.enqueue was called
        assert mock_job_manager.enqueue.called
        call_args = mock_job_manager.enqueue.call_args

        # Verify function name
        assert call_args[0][0] == Task.LOG_AUDIT_EVENT

        # Verify job_id
        assert call_args[0][1] == job_id

        # Verify params
        params = call_args[0][2]
        assert params["tenant_id"] == str(tenant_id)
        assert params["actor_id"] == str(actor_id)
        assert params["action"] == "user_created"
        assert params["entity_type"] == "user"
        assert params["entity_id"] == str(entity_id)
        assert params["description"] == "Test async log"
        assert params["outcome"] == "success"


@pytest.mark.asyncio
async def test_log_async_validation():
    """Test that log_async validates failure requires error_message."""
    mock_repository = MagicMock()
    service = AuditService(mock_repository)

    with pytest.raises(ValueError, match="error_message required"):
        await service.log_async(
            tenant_id=uuid4(),
            actor_id=uuid4(),
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            description="Test",
            metadata={},
            outcome=Outcome.FAILURE,
            # Missing error_message
        )


@pytest.mark.asyncio
async def test_log_async_with_optional_params():
    """Test log_async with optional parameters."""
    mock_repository = MagicMock()
    mock_job_manager = AsyncMock()

    service = AuditService(mock_repository)

    with patch("eneo.audit.application.audit_service.job_manager", mock_job_manager):
        request_id = uuid4()

        await service.log_async(
            tenant_id=uuid4(),
            actor_id=uuid4(),
            action=ActionType.ASSISTANT_CREATED,
            entity_type=EntityType.ASSISTANT,
            entity_id=uuid4(),
            description="Test",
            metadata={"key": "value"},
            actor_type=ActorType.SYSTEM,
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            request_id=request_id,
        )

        # Verify params include optional fields
        params = mock_job_manager.enqueue.call_args[0][2]
        assert params["actor_type"] == "system"
        assert params["ip_address"] == "192.168.1.1"
        assert params["user_agent"] == "Mozilla/5.0"
        assert params["request_id"] == str(request_id)


def test_audit_tasks_are_registered_in_task_enum():
    assert Task.LOG_AUDIT_EVENT.value == "log_audit_event"
    assert Task.EXPORT_AUDIT_LOGS.value == "export_audit_logs"


async def _manager(monkeypatch, port: int) -> JobManager:
    """A job manager on the local test Redis: one connection, 1 s reads."""
    settings = get_settings().model_copy(
        update={
            "redis_host": "127.0.0.1",
            "redis_port": port,
            "redis_db": 0,
            "redis_conn_timeout": 1,
            "redis_max_connections": 1,
        }
    )
    monkeypatch.setattr(job_manager_module, "get_settings", lambda: settings)
    manager = JobManager()
    await manager.init()
    monkeypatch.setattr(audit_service_module, "job_manager", manager)
    return manager


async def _log(service: AuditService) -> object:
    return await service.log_async(
        tenant_id=uuid4(),
        actor_id=uuid4(),
        action=ActionType.USER_CREATED,
        entity_type=EntityType.USER,
        entity_id=uuid4(),
        description="Test",
        metadata={},
    )


@pytest.mark.asyncio
async def test_log_async_returns_within_the_bound_when_redis_is_silent(monkeypatch):
    # Redis answers arq's startup and the WATCH of the enqueue, then stops
    # answering. The enqueue and the transaction cleanup after it end at the
    # read bound, and the audit becomes the usual warning instead of holding
    # the request. The pool has one connection: each stalled enqueue must
    # give it back, or the next one finds none once Redis answers again.
    service = AuditService(MagicMock())

    async with freezing_redis(freeze_after=b"WATCH") as redis:
        manager = await _manager(monkeypatch, redis.port)
        try:
            for _ in range(2):
                redis.freeze_after = b"WATCH"
                with patch.object(audit_service_module.logger, "warning") as warned:
                    started = time.monotonic()
                    async with asyncio.timeout(15):
                        job_id = await _log(service)
                    elapsed = time.monotonic() - started

                assert job_id is None
                assert elapsed < 5
                assert warned.call_args.args[0].startswith(
                    "Failed to enqueue audit event"
                )

                redis.thaw()
                async with asyncio.timeout(5):
                    assert (
                        await manager.enqueue(Task.LOG_AUDIT_EVENT, uuid4(), {})
                        is not None
                    )
        finally:
            await manager.close()


@pytest.mark.asyncio
async def test_an_enqueue_whose_transaction_was_not_answered_is_a_warning(
    monkeypatch,
):
    # Redis takes the transaction but its EXEC reply never comes; the cleanup
    # after it is answered. arq reports such a transaction as it reports a
    # job already queued, and nothing shows this job was, so the audit
    # entry is missing and says so.
    service = AuditService(MagicMock())

    async with freezing_redis(unanswered=b"EXEC") as redis:
        manager = await _manager(monkeypatch, redis.port)
        try:
            with patch.object(audit_service_module.logger, "warning") as warned:
                async with asyncio.timeout(15):
                    job_id = await _log(service)
        finally:
            await manager.close()

    assert b"EXEC" in redis.commands
    assert job_id is None
    assert warned.call_args.args[0].startswith("Failed to enqueue audit event")


@pytest.mark.asyncio
async def test_a_jobless_enqueue_whose_transaction_was_not_answered_fails(
    monkeypatch,
):
    # The same unanswered EXEC for a task queued without a job id, as the
    # weekly crawl trigger queues it: the caller learns it was not queued.
    async with freezing_redis(unanswered=b"EXEC") as redis:
        manager = await _manager(monkeypatch, redis.port)
        try:
            with pytest.raises(RedisConnectionError):
                async with asyncio.timeout(15):
                    await manager.enqueue_jobless(Task.CRAWL_ALL_WEBSITES)
        finally:
            await manager.close()

    assert b"EXEC" in redis.commands
