"""Integration tests for audit logging ARQ worker."""

import pytest
from datetime import datetime
from uuid import uuid4

from intric.audit.application.audit_worker_task import log_audit_event_task
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome
from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_log_audit_event_task(db_session, test_tenant, test_user):
    """Test that the worker task successfully persists audit logs."""
    async with db_session() as session:
        job_id = str(uuid4())
        entity_id = uuid4()

        # Prepare params as they would come from ARQ
        params = {
            "tenant_id": str(test_tenant.id),
            "actor_id": str(test_user),
            "actor_type": ActorType.USER.value,
            "action": ActionType.ASSISTANT_CREATED.value,
            "entity_type": EntityType.ASSISTANT.value,
            "entity_id": str(entity_id),
            "timestamp": datetime.utcnow().isoformat(),
            "description": "Worker created assistant",
            "metadata": {"test": "worker"},
            "outcome": Outcome.SUCCESS.value,
            "ip_address": "192.168.1.1",
            "user_agent": "TestClient",
            "request_id": None,
            "error_message": None,
        }

        # Execute worker task
        result = await log_audit_event_task(
            job_id=job_id,
            params=params,
            session=session,
        )

        # Verify result
        assert "audit_log_id" in result
        assert result["audit_log_id"] is not None

        # Verify log was persisted
        repository = AuditLogRepositoryImpl(session)
        logs, count = await repository.get_logs(tenant_id=test_tenant.id)

        assert count >= 1

        # Find our log
        created_log = next(
            (log for log in logs if log.description == "Worker created assistant"),
            None
        )
        assert created_log is not None
        assert created_log.action == ActionType.ASSISTANT_CREATED
        assert created_log.actor_id == test_user
        assert created_log.ip_address == "192.168.1.1"


@pytest.mark.asyncio
async def test_worker_task_handles_failure_outcome(db_session, test_tenant, test_user):
    """Test worker task with failure outcome and error message."""
    async with db_session() as session:
        job_id = str(uuid4())

        params = {
            "tenant_id": str(test_tenant.id),
            "actor_id": str(test_user),
            "actor_type": ActorType.USER.value,
            "action": ActionType.USER_CREATED.value,
            "entity_type": EntityType.USER.value,
            "entity_id": str(uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "description": "Failed to create user",
            "metadata": {},
            "outcome": Outcome.FAILURE.value,
            "ip_address": None,
            "user_agent": None,
            "request_id": None,
            "error_message": "Email already exists",
        }

        # Execute worker task
        result = await log_audit_event_task(
            job_id=job_id,
            params=params,
            session=session,
        )

        assert "audit_log_id" in result

        # Verify failure log was persisted
        repository = AuditLogRepositoryImpl(session)
        logs, count = await repository.get_logs(tenant_id=test_tenant.id)

        failed_log = next(
            (log for log in logs if log.outcome == Outcome.FAILURE),
            None
        )
        assert failed_log is not None
        assert failed_log.error_message == "Email already exists"


@pytest.mark.asyncio
async def test_worker_task_validates_params(db_session, test_tenant):
    """Test that worker task validates parameters."""
    async with db_session() as session:
        # Invalid params (missing required fields)
        invalid_params = {
            "tenant_id": str(test_tenant.id),
            # Missing other required fields
        }

        with pytest.raises(Exception):  # Will raise validation error
            await log_audit_event_task(
                job_id=str(uuid4()),
                params=invalid_params,
                session=session,
            )
