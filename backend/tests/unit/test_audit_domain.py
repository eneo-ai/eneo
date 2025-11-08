"""Unit tests for audit domain models."""

from datetime import datetime
from uuid import uuid4

import pytest

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.audit_log import AuditLog
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome


def test_audit_log_creation_success():
    """Test creating a valid audit log with successful outcome."""
    audit_log = AuditLog(
        id=uuid4(),
        tenant_id=uuid4(),
        actor_id=uuid4(),
        actor_type=ActorType.USER,
        action=ActionType.USER_CREATED,
        entity_type=EntityType.USER,
        entity_id=uuid4(),
        timestamp=datetime.utcnow(),
        description="User created successfully",
        metadata={"user": "test@example.com"},
        outcome=Outcome.SUCCESS,
    )

    assert audit_log.outcome == Outcome.SUCCESS
    assert audit_log.action == ActionType.USER_CREATED
    assert audit_log.error_message is None


def test_audit_log_failure_requires_error_message():
    """Test that failure outcome requires error_message."""
    with pytest.raises(ValueError, match="error_message required"):
        AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime.utcnow(),
            description="User creation failed",
            metadata={},
            outcome=Outcome.FAILURE,
            # error_message is missing - should raise ValueError
        )


def test_audit_log_failure_with_error_message():
    """Test creating audit log with failure outcome and error message."""
    audit_log = AuditLog(
        id=uuid4(),
        tenant_id=uuid4(),
        actor_id=uuid4(),
        actor_type=ActorType.USER,
        action=ActionType.USER_CREATED,
        entity_type=EntityType.USER,
        entity_id=uuid4(),
        timestamp=datetime.utcnow(),
        description="User creation failed",
        metadata={},
        outcome=Outcome.FAILURE,
        error_message="Email already exists",
    )

    assert audit_log.outcome == Outcome.FAILURE
    assert audit_log.error_message == "Email already exists"


def test_action_types_enum():
    """Test ActionType enum values."""
    assert ActionType.USER_CREATED == "user_created"
    assert ActionType.ASSISTANT_DELETED == "assistant_deleted"
    assert ActionType.SPACE_MEMBER_ADDED == "space_member_added"


def test_entity_types_enum():
    """Test EntityType enum values."""
    assert EntityType.USER == "user"
    assert EntityType.ASSISTANT == "assistant"
    assert EntityType.SPACE == "space"


def test_actor_types_enum():
    """Test ActorType enum values."""
    assert ActorType.USER == "user"
    assert ActorType.SYSTEM == "system"
    assert ActorType.API_KEY == "api_key"


def test_outcome_enum():
    """Test Outcome enum values."""
    assert Outcome.SUCCESS == "success"
    assert Outcome.FAILURE == "failure"
