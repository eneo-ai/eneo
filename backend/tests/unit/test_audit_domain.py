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
    assert ActionType.API_KEY_GENERATED == "api_key_generated"
    assert ActionType.ROLE_MODIFIED == "role_modified"
    assert ActionType.WEBSITE_CRAWLED == "website_crawled"
    # Test new action types
    assert ActionType.ROLE_CREATED == "role_created"
    assert ActionType.ROLE_DELETED == "role_deleted"
    assert ActionType.ASSISTANT_TRANSFERRED == "assistant_transferred"
    assert ActionType.ASSISTANT_PUBLISHED == "assistant_published"
    assert ActionType.SPACE_DELETED == "space_deleted"
    assert ActionType.APP_PUBLISHED == "app_published"
    assert ActionType.TEMPLATE_CREATED == "template_created"
    assert ActionType.WEBSITE_CREATED == "website_created"
    assert ActionType.GROUP_CHAT_CREATED == "group_chat_created"
    assert ActionType.COLLECTION_CREATED == "collection_created"
    assert ActionType.SECURITY_CLASSIFICATION_CREATED == "security_classification_created"
    assert ActionType.SECURITY_CLASSIFICATION_ENABLED == "security_classification_enabled"


def test_entity_types_enum():
    """Test EntityType enum values."""
    assert EntityType.USER == "user"
    assert EntityType.ASSISTANT == "assistant"
    assert EntityType.SPACE == "space"
    assert EntityType.API_KEY == "api_key"
    assert EntityType.WEBSITE == "website"
    # Test new entity types
    assert EntityType.ROLE == "role"
    assert EntityType.MODULE == "module"
    assert EntityType.TEMPLATE == "template"
    assert EntityType.GROUP_CHAT == "group_chat"
    assert EntityType.COLLECTION == "collection"
    assert EntityType.APP_RUN == "app_run"
    assert EntityType.SECURITY_CLASSIFICATION == "security_classification"


def test_actor_types_enum():
    """Test ActorType enum values."""
    assert ActorType.USER == "user"
    assert ActorType.SYSTEM == "system"
    assert ActorType.API_KEY == "api_key"


def test_outcome_enum():
    """Test Outcome enum values."""
    assert Outcome.SUCCESS == "success"
    assert Outcome.FAILURE == "failure"
