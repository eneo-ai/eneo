"""Unit tests for async audit logging."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome


@pytest.mark.asyncio
async def test_log_async_enqueues_to_arq():
    """Test that log_async enqueues the audit log to ARQ."""
    # Mock the repository and job_manager
    mock_repository = MagicMock()
    mock_job_manager = AsyncMock()

    service = AuditService(mock_repository)

    # Patch job_manager
    with patch("intric.audit.application.audit_service.job_manager", mock_job_manager):
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
        assert call_args[0][0] == "log_audit_event"

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

    with patch("intric.audit.application.audit_service.job_manager", mock_job_manager):
        request_id = uuid4()

        job_id = await service.log_async(
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
