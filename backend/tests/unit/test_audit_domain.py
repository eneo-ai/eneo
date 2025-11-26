"""Unit tests for audit domain models."""

from dataclasses import is_dataclass
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.audit_log import AuditLog
from intric.audit.domain.constants import (
    MAX_DESCRIPTION_LENGTH,
    MAX_ERROR_MESSAGE_LENGTH,
    MAX_USER_AGENT_LENGTH,
    MIN_RETENTION_DAYS,
    MAX_RETENTION_DAYS,
    DEFAULT_RETENTION_DAYS,
)
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome


class TestAuditLogCreation:
    """Tests for basic AuditLog creation."""

    def test_audit_log_creation_success(self):
        """Test creating a valid audit log with successful outcome."""
        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            description="User created successfully",
            metadata={"user": "test@example.com"},
            outcome=Outcome.SUCCESS,
        )

        assert audit_log.outcome == Outcome.SUCCESS
        assert audit_log.action == ActionType.USER_CREATED
        assert audit_log.error_message is None

    def test_audit_log_failure_requires_error_message(self):
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
                timestamp=datetime.now(timezone.utc),
                description="User creation failed",
                metadata={},
                outcome=Outcome.FAILURE,
                # error_message is missing - should raise ValueError
            )

    def test_audit_log_failure_with_error_message(self):
        """Test creating audit log with failure outcome and error message."""
        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            description="User creation failed",
            metadata={},
            outcome=Outcome.FAILURE,
            error_message="Email already exists",
        )

        assert audit_log.outcome == Outcome.FAILURE
        assert audit_log.error_message == "Email already exists"

    def test_audit_log_is_dataclass(self):
        """AuditLog should be a dataclass."""
        assert is_dataclass(AuditLog)


class TestDescriptionValidation:
    """Tests for description field validation."""

    def test_description_at_max_length_succeeds(self):
        """Description exactly at MAX_DESCRIPTION_LENGTH (500) should succeed."""
        description = "a" * MAX_DESCRIPTION_LENGTH
        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            description=description,
            metadata={},
            outcome=Outcome.SUCCESS,
        )
        assert len(audit_log.description) == MAX_DESCRIPTION_LENGTH

    def test_description_exceeds_max_length_raises_value_error(self):
        """Description > 500 chars should raise ValueError with specific message."""
        description = "a" * (MAX_DESCRIPTION_LENGTH + 1)
        with pytest.raises(ValueError, match=f"must not exceed {MAX_DESCRIPTION_LENGTH}"):
            AuditLog(
                id=uuid4(),
                tenant_id=uuid4(),
                actor_id=uuid4(),
                actor_type=ActorType.USER,
                action=ActionType.USER_CREATED,
                entity_type=EntityType.USER,
                entity_id=uuid4(),
                timestamp=datetime.now(timezone.utc),
                description=description,
                metadata={},
                outcome=Outcome.SUCCESS,
            )

    def test_description_empty_string_raises_value_error(self):
        """Empty string description should raise ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            AuditLog(
                id=uuid4(),
                tenant_id=uuid4(),
                actor_id=uuid4(),
                actor_type=ActorType.USER,
                action=ActionType.USER_CREATED,
                entity_type=EntityType.USER,
                entity_id=uuid4(),
                timestamp=datetime.now(timezone.utc),
                description="",
                metadata={},
                outcome=Outcome.SUCCESS,
            )

    def test_description_whitespace_only_raises_value_error(self):
        """Whitespace-only description should raise ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            AuditLog(
                id=uuid4(),
                tenant_id=uuid4(),
                actor_id=uuid4(),
                actor_type=ActorType.USER,
                action=ActionType.USER_CREATED,
                entity_type=EntityType.USER,
                entity_id=uuid4(),
                timestamp=datetime.now(timezone.utc),
                description="   \t\n  ",
                metadata={},
                outcome=Outcome.SUCCESS,
            )

    def test_description_with_unicode_at_boundary(self):
        """Multi-byte unicode chars at 500 char boundary should validate correctly."""
        # Note: Python counts characters, not bytes
        description = "日" * MAX_DESCRIPTION_LENGTH  # 500 Japanese characters
        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            description=description,
            metadata={},
            outcome=Outcome.SUCCESS,
        )
        assert len(audit_log.description) == MAX_DESCRIPTION_LENGTH


class TestErrorMessageValidation:
    """Tests for error_message field validation."""

    def test_error_message_at_max_length_succeeds(self):
        """Error message exactly at MAX_ERROR_MESSAGE_LENGTH should succeed."""
        error_message = "e" * MAX_ERROR_MESSAGE_LENGTH
        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            description="Operation failed",
            metadata={},
            outcome=Outcome.FAILURE,
            error_message=error_message,
        )
        assert len(audit_log.error_message) == MAX_ERROR_MESSAGE_LENGTH

    def test_error_message_exceeds_max_length_raises_value_error(self):
        """Error message > 2000 chars should raise ValueError."""
        error_message = "e" * (MAX_ERROR_MESSAGE_LENGTH + 1)
        with pytest.raises(ValueError, match=f"must not exceed {MAX_ERROR_MESSAGE_LENGTH}"):
            AuditLog(
                id=uuid4(),
                tenant_id=uuid4(),
                actor_id=uuid4(),
                actor_type=ActorType.USER,
                action=ActionType.USER_CREATED,
                entity_type=EntityType.USER,
                entity_id=uuid4(),
                timestamp=datetime.now(timezone.utc),
                description="Operation failed",
                metadata={},
                outcome=Outcome.FAILURE,
                error_message=error_message,
            )

    def test_error_message_with_success_outcome_is_allowed(self):
        """Success outcome with error_message populated should NOT raise."""
        # This is intentionally allowed - sometimes we want to log warnings
        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            description="User created with warning",
            metadata={},
            outcome=Outcome.SUCCESS,
            error_message="Warning: duplicate email detected",
        )
        assert audit_log.outcome == Outcome.SUCCESS
        assert audit_log.error_message is not None

    def test_error_message_empty_string_with_failure_raises(self):
        """Empty string error_message with FAILURE outcome should raise."""
        # Empty string is falsy, so 'not self.error_message' will be True
        with pytest.raises(ValueError, match="error_message required"):
            AuditLog(
                id=uuid4(),
                tenant_id=uuid4(),
                actor_id=uuid4(),
                actor_type=ActorType.USER,
                action=ActionType.USER_CREATED,
                entity_type=EntityType.USER,
                entity_id=uuid4(),
                timestamp=datetime.now(timezone.utc),
                description="Operation failed",
                metadata={},
                outcome=Outcome.FAILURE,
                error_message="",  # Empty string
            )


class TestUserAgentValidation:
    """Tests for user_agent field validation (truncation behavior)."""

    def test_user_agent_truncated_at_1000_chars(self):
        """User agent > 1000 chars should be silently truncated (not raise)."""
        long_user_agent = "Mozilla/5.0 " + "x" * 2000
        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            description="Test truncation",
            metadata={},
            outcome=Outcome.SUCCESS,
            user_agent=long_user_agent,
        )
        assert len(audit_log.user_agent) == MAX_USER_AGENT_LENGTH
        assert audit_log.user_agent.startswith("Mozilla/5.0 ")

    def test_user_agent_exactly_at_limit_not_truncated(self):
        """User agent at exactly 1000 chars should not be modified."""
        user_agent = "a" * MAX_USER_AGENT_LENGTH
        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            description="Test exact length",
            metadata={},
            outcome=Outcome.SUCCESS,
            user_agent=user_agent,
        )
        assert len(audit_log.user_agent) == MAX_USER_AGENT_LENGTH
        assert audit_log.user_agent == user_agent

    def test_user_agent_none_is_valid(self):
        """None user_agent should be accepted."""
        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            description="Test None user_agent",
            metadata={},
            outcome=Outcome.SUCCESS,
            user_agent=None,
        )
        assert audit_log.user_agent is None


class TestOptionalFields:
    """Tests for optional field handling."""

    def test_optional_ip_address_none(self):
        """None ip_address should be valid."""
        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            description="Test",
            metadata={},
            outcome=Outcome.SUCCESS,
            ip_address=None,
        )
        assert audit_log.ip_address is None

    def test_optional_request_id_none(self):
        """None request_id should be valid."""
        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            description="Test",
            metadata={},
            outcome=Outcome.SUCCESS,
            request_id=None,
        )
        assert audit_log.request_id is None

    def test_optional_deleted_at_none(self):
        """None deleted_at should be valid (not soft-deleted)."""
        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            description="Test",
            metadata={},
            outcome=Outcome.SUCCESS,
            deleted_at=None,
        )
        assert audit_log.deleted_at is None

    def test_all_optional_fields_populated(self):
        """All optional fields can be populated together."""
        request_id = uuid4()
        now = datetime.now(timezone.utc)
        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=now,
            description="Full audit log",
            metadata={"key": "value"},
            outcome=Outcome.SUCCESS,
            ip_address="192.168.1.1",
            user_agent="TestAgent/1.0",
            request_id=request_id,
            error_message=None,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
        assert audit_log.ip_address == "192.168.1.1"
        assert audit_log.user_agent == "TestAgent/1.0"
        assert audit_log.request_id == request_id


class TestConstants:
    """Tests for audit domain constants."""

    def test_max_description_length_is_500(self):
        """MAX_DESCRIPTION_LENGTH should be 500."""
        assert MAX_DESCRIPTION_LENGTH == 500

    def test_max_error_message_length_is_2000(self):
        """MAX_ERROR_MESSAGE_LENGTH should be 2000."""
        assert MAX_ERROR_MESSAGE_LENGTH == 2000

    def test_max_user_agent_length_is_1000(self):
        """MAX_USER_AGENT_LENGTH should be 1000."""
        assert MAX_USER_AGENT_LENGTH == 1000

    def test_retention_constants(self):
        """Retention policy constants should have correct values."""
        assert MIN_RETENTION_DAYS == 1
        assert MAX_RETENTION_DAYS == 2555  # ~7 years
        assert DEFAULT_RETENTION_DAYS == 365  # 1 year


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
    assert ActionType.COLLECTION_UPDATED == "collection_updated"
    assert ActionType.COLLECTION_DELETED == "collection_deleted"
    assert ActionType.INTEGRATION_ADDED == "integration_added"
    assert ActionType.INTEGRATION_CONNECTED == "integration_connected"
    assert ActionType.INTEGRATION_KNOWLEDGE_CREATED == "integration_knowledge_created"
    assert ActionType.COMPLETION_MODEL_UPDATED == "completion_model_updated"
    assert ActionType.EMBEDDING_MODEL_UPDATED == "embedding_model_updated"
    assert ActionType.TRANSCRIPTION_MODEL_UPDATED == "transcription_model_updated"
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
    assert EntityType.INTEGRATION == "integration"
    assert EntityType.INTEGRATION_KNOWLEDGE == "integration_knowledge"
    assert EntityType.COMPLETION_MODEL == "completion_model"
    assert EntityType.EMBEDDING_MODEL == "embedding_model"
    assert EntityType.TRANSCRIPTION_MODEL == "transcription_model"


def test_actor_types_enum():
    """Test ActorType enum values."""
    assert ActorType.USER == "user"
    assert ActorType.SYSTEM == "system"
    assert ActorType.API_KEY == "api_key"


def test_outcome_enum():
    """Test Outcome enum values."""
    assert Outcome.SUCCESS == "success"
    assert Outcome.FAILURE == "failure"


class TestEnumCompleteness:
    """Tests for enum completeness and type consistency."""

    def test_all_action_types_are_string_enums(self):
        """All ActionType members should inherit from str."""
        for action in ActionType:
            assert isinstance(action.value, str)
            assert isinstance(action, str)

    def test_all_entity_types_are_string_enums(self):
        """All EntityType members should inherit from str."""
        for entity in EntityType:
            assert isinstance(entity.value, str)
            assert isinstance(entity, str)

    def test_actor_type_count_is_3(self):
        """ActorType enum should have exactly 3 members."""
        assert len(ActorType) == 3
        assert set(ActorType) == {ActorType.USER, ActorType.SYSTEM, ActorType.API_KEY}

    def test_outcome_count_is_2(self):
        """Outcome enum should have exactly 2 members."""
        assert len(Outcome) == 2
        assert set(Outcome) == {Outcome.SUCCESS, Outcome.FAILURE}

    def test_action_types_have_unique_values(self):
        """All ActionType values should be unique."""
        values = [a.value for a in ActionType]
        assert len(values) == len(set(values)), "Duplicate ActionType values found"

    def test_entity_types_have_unique_values(self):
        """All EntityType values should be unique."""
        values = [e.value for e in EntityType]
        assert len(values) == len(set(values)), "Duplicate EntityType values found"

    def test_action_type_audit_session_created_exists(self):
        """AUDIT_SESSION_CREATED action should exist."""
        assert hasattr(ActionType, "AUDIT_SESSION_CREATED")
        assert ActionType.AUDIT_SESSION_CREATED.value == "audit_session_created"

    def test_action_type_audit_log_viewed_exists(self):
        """AUDIT_LOG_VIEWED action should exist."""
        assert hasattr(ActionType, "AUDIT_LOG_VIEWED")
        assert ActionType.AUDIT_LOG_VIEWED.value == "audit_log_viewed"

    def test_action_type_audit_log_exported_exists(self):
        """AUDIT_LOG_EXPORTED action should exist."""
        assert hasattr(ActionType, "AUDIT_LOG_EXPORTED")
        assert ActionType.AUDIT_LOG_EXPORTED.value == "audit_log_exported"

    def test_entity_type_audit_log_exists(self):
        """AUDIT_LOG entity type should exist."""
        assert hasattr(EntityType, "AUDIT_LOG")
        assert EntityType.AUDIT_LOG.value == "audit_log"
