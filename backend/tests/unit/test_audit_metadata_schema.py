"""Unit tests for AuditMetadata Pydantic schema.

These schemas ensure consistent audit log metadata structure
across all audit log entries.
"""

import pytest
from pydantic import ValidationError

from intric.audit.domain.audit_metadata_schema import (
    AuditActor,
    AuditChange,
    AuditMetadata,
    AuditTarget,
)


class TestAuditActor:
    """Tests for AuditActor model."""

    def test_actor_with_all_fields(self):
        """Test creating actor with all fields populated."""
        actor = AuditActor(
            id="user-123",
            name="Test User",
            email="test@example.com",
            type="user",
            via="web",
        )
        assert actor.id == "user-123"
        assert actor.name == "Test User"
        assert actor.email == "test@example.com"
        assert actor.type == "user"
        assert actor.via == "web"

    def test_actor_with_required_fields_only(self):
        """Test creating actor with only required id field."""
        actor = AuditActor(id="user-123")
        assert actor.id == "user-123"
        assert actor.name is None
        assert actor.email is None
        assert actor.type is None
        assert actor.via is None

    def test_actor_forbids_extra_fields(self):
        """Test that extra fields are not allowed."""
        with pytest.raises(ValidationError):
            AuditActor(
                id="user-123",
                extra_field="not allowed",  # Extra field should fail
            )

    def test_actor_id_required(self):
        """Test that id field is required."""
        with pytest.raises(ValidationError):
            AuditActor(name="Test User")  # Missing id


class TestAuditTarget:
    """Tests for AuditTarget model."""

    def test_target_with_all_fields(self):
        """Test creating target with all fields populated."""
        target = AuditTarget(
            id="entity-456",
            name="Test Entity",
        )
        assert target.id == "entity-456"
        assert target.name == "Test Entity"

    def test_target_with_required_fields_only(self):
        """Test creating target with only required id field."""
        target = AuditTarget(id="entity-456")
        assert target.id == "entity-456"
        assert target.name is None

    def test_target_allows_extra_fields(self):
        """Test that extra fields ARE allowed for context-specific data."""
        target = AuditTarget(
            id="entity-456",
            name="Test Entity",
            space_name="Test Space",  # Extra field for context
            member_email="member@example.com",  # Extra field for context
        )
        assert target.id == "entity-456"
        assert target.space_name == "Test Space"
        assert target.member_email == "member@example.com"

    def test_target_id_required(self):
        """Test that id field is required."""
        with pytest.raises(ValidationError):
            AuditTarget(name="Test Entity")  # Missing id


class TestAuditChange:
    """Tests for AuditChange model."""

    def test_change_with_string_values(self):
        """Test creating change with string values."""
        change = AuditChange(old="old_value", new="new_value")
        assert change.old == "old_value"
        assert change.new == "new_value"

    def test_change_with_boolean_values(self):
        """Test creating change with boolean values."""
        change = AuditChange(old=False, new=True)
        assert change.old is False
        assert change.new is True

    def test_change_with_none_values(self):
        """Test creating change where old or new is None."""
        change = AuditChange(old=None, new="new_value")
        assert change.old is None
        assert change.new == "new_value"

    def test_change_with_list_values(self):
        """Test creating change with list values (for model changes)."""
        old_models = [{"id": "model-1", "name": "Model A"}]
        new_models = [
            {"id": "model-1", "name": "Model A"},
            {"id": "model-2", "name": "Model B"},
        ]
        change = AuditChange(old=old_models, new=new_models)
        assert len(change.old) == 1
        assert len(change.new) == 2

    def test_change_forbids_extra_fields(self):
        """Test that extra fields are not allowed."""
        with pytest.raises(ValidationError):
            AuditChange(
                old="old",
                new="new",
                extra="not allowed",
            )

    def test_change_requires_both_old_and_new(self):
        """Test that both old and new are required."""
        with pytest.raises(ValidationError):
            AuditChange(old="only_old")  # Missing new

        with pytest.raises(ValidationError):
            AuditChange(new="only_new")  # Missing old


class TestAuditMetadata:
    """Tests for AuditMetadata model."""

    def test_metadata_with_all_fields(self):
        """Test creating complete metadata with actor, target, and changes."""
        metadata = AuditMetadata(
            actor=AuditActor(id="user-123", name="Test User"),
            target=AuditTarget(id="entity-456", name="Test Entity"),
            changes={
                "name": AuditChange(old="Old Name", new="New Name"),
                "status": AuditChange(old=False, new=True),
            },
        )
        assert metadata.actor.id == "user-123"
        assert metadata.target.id == "entity-456"
        assert len(metadata.changes) == 2
        assert metadata.changes["name"].old == "Old Name"

    def test_metadata_without_changes(self):
        """Test creating metadata without changes (for create/delete actions)."""
        metadata = AuditMetadata(
            actor=AuditActor(id="user-123"),
            target=AuditTarget(id="entity-456"),
        )
        assert len(metadata.changes) == 0

    def test_metadata_to_dict(self):
        """Test to_dict() produces expected structure."""
        metadata = AuditMetadata(
            actor=AuditActor(id="user-123", name="Test User", email="test@example.com"),
            target=AuditTarget(id="entity-456", name="Test Entity"),
            changes={"name": AuditChange(old="Old", new="New")},
        )

        result = metadata.to_dict()

        # Verify structure
        assert "actor" in result
        assert "target" in result
        assert "changes" in result

        # Verify actor
        assert result["actor"]["id"] == "user-123"
        assert result["actor"]["name"] == "Test User"
        assert result["actor"]["email"] == "test@example.com"

        # Verify target
        assert result["target"]["id"] == "entity-456"
        assert result["target"]["name"] == "Test Entity"

        # Verify changes
        assert result["changes"]["name"]["old"] == "Old"
        assert result["changes"]["name"]["new"] == "New"

    def test_metadata_to_dict_excludes_none(self):
        """Test to_dict() excludes None values."""
        metadata = AuditMetadata(
            actor=AuditActor(id="user-123"),  # name and email are None
            target=AuditTarget(id="entity-456"),  # name is None
        )

        result = metadata.to_dict()

        # None values should be excluded
        assert "name" not in result["actor"]
        assert "email" not in result["actor"]
        assert "name" not in result["target"]

    def test_metadata_forbids_extra_fields(self):
        """Test that extra fields are not allowed at top level."""
        with pytest.raises(ValidationError):
            AuditMetadata(
                actor=AuditActor(id="user-123"),
                target=AuditTarget(id="entity-456"),
                extra_field="not allowed",
            )


class TestAuditMetadataCreateSimple:
    """Tests for AuditMetadata.create_simple() factory method."""

    def test_create_simple_minimal(self):
        """Test create_simple with minimal required fields."""
        metadata = AuditMetadata.create_simple(
            actor_id="user-123",
            target_id="entity-456",
        )

        assert metadata.actor.id == "user-123"
        assert metadata.actor.name is None
        assert metadata.target.id == "entity-456"
        assert metadata.target.name is None
        assert len(metadata.changes) == 0

    def test_create_simple_with_names(self):
        """Test create_simple with optional names."""
        metadata = AuditMetadata.create_simple(
            actor_id="user-123",
            target_id="entity-456",
            actor_name="Test User",
            actor_email="test@example.com",
            target_name="Test Entity",
        )

        assert metadata.actor.id == "user-123"
        assert metadata.actor.name == "Test User"
        assert metadata.actor.email == "test@example.com"
        assert metadata.target.id == "entity-456"
        assert metadata.target.name == "Test Entity"

    def test_create_simple_with_extra_target_context(self):
        """Test create_simple with extra target context fields."""
        metadata = AuditMetadata.create_simple(
            actor_id="user-123",
            target_id="entity-456",
            target_name="Test Entity",
            space_name="Test Space",
            member_email="member@example.com",
        )

        result = metadata.to_dict()

        # Extra fields should be present in target
        assert result["target"]["space_name"] == "Test Space"
        assert result["target"]["member_email"] == "member@example.com"


class TestAuditMetadataModelRouterPatterns:
    """Tests for model router audit metadata patterns.

    These tests verify the consolidated changes pattern used in
    completion_models_router, transcription_models_router, and
    embedding_model_router.
    """

    def test_is_org_enabled_change_structure(self):
        """Test structure for is_org_enabled toggle."""
        metadata = AuditMetadata(
            actor=AuditActor(id="admin-123", name="Admin User"),
            target=AuditTarget(id="model-456", name="GPT-4"),
            changes={
                "is_org_enabled": AuditChange(old=False, new=True),
            },
        )

        result = metadata.to_dict()

        assert result["changes"]["is_org_enabled"]["old"] is False
        assert result["changes"]["is_org_enabled"]["new"] is True

    def test_is_org_default_change_structure(self):
        """Test structure for is_org_default toggle."""
        metadata = AuditMetadata(
            actor=AuditActor(id="admin-123", name="Admin User"),
            target=AuditTarget(id="model-456", name="GPT-4"),
            changes={
                "is_org_default": AuditChange(old=False, new=True),
            },
        )

        result = metadata.to_dict()

        assert result["changes"]["is_org_default"]["old"] is False
        assert result["changes"]["is_org_default"]["new"] is True

    def test_security_classification_change_structure(self):
        """Test structure for security_classification change."""
        metadata = AuditMetadata(
            actor=AuditActor(id="admin-123", name="Admin User"),
            target=AuditTarget(id="model-456", name="GPT-4"),
            changes={
                "security_classification": AuditChange(
                    old=None, new="Confidential"
                ),
            },
        )

        result = metadata.to_dict()

        assert result["changes"]["security_classification"]["old"] is None
        assert result["changes"]["security_classification"]["new"] == "Confidential"

    def test_consolidated_model_changes_structure(self):
        """Test consolidated changes structure (multiple fields in one entry)."""
        metadata = AuditMetadata(
            actor=AuditActor(
                id="admin-123",
                name="Admin User",
                email="admin@example.com",
            ),
            target=AuditTarget(id="model-456", name="GPT-4"),
            changes={
                "is_org_enabled": AuditChange(old=False, new=True),
                "is_org_default": AuditChange(old=False, new=True),
                "security_classification": AuditChange(old=None, new="Internal"),
            },
        )

        result = metadata.to_dict()

        # All three changes in a single audit entry
        assert len(result["changes"]) == 3
        assert "is_org_enabled" in result["changes"]
        assert "is_org_default" in result["changes"]
        assert "security_classification" in result["changes"]


class TestSpaceRouterMetadataPatterns:
    """Tests for space router audit metadata patterns.

    These tests verify the SET comparison and snapshot patterns
    used in space_router for SPACE_UPDATED, SPACE_MEMBER_REMOVED,
    and ROLE_MODIFIED actions.
    """

    def test_completion_models_change_structure(self):
        """Test structure for completion_models changes using SET comparison."""
        metadata = AuditMetadata(
            actor=AuditActor(id="user-123", name="Test User"),
            target=AuditTarget(id="space-456", name="Test Space"),
            changes={
                "completion_models": AuditChange(
                    old=[{"id": "model-1", "name": "GPT-3.5"}],
                    new=[
                        {"id": "model-1", "name": "GPT-3.5"},
                        {"id": "model-2", "name": "GPT-4"},
                    ],
                ),
            },
        )

        result = metadata.to_dict()

        assert len(result["changes"]["completion_models"]["old"]) == 1
        assert len(result["changes"]["completion_models"]["new"]) == 2

    def test_space_member_removed_metadata_structure(self):
        """Test metadata structure for SPACE_MEMBER_REMOVED with full context."""
        target = AuditTarget(
            id="space-456",  # Required id field
            name="Test Space",
            space_id="space-456",
            space_name="Test Space",
            member_id="member-789",
            member_name="John Doe",
            member_email="john@example.com",
        )

        metadata = AuditMetadata(
            actor=AuditActor(
                id="admin-123",
                name="Admin User",
                email="admin@example.com",
            ),
            target=target,
        )

        result = metadata.to_dict()

        # Verify all context fields are present
        assert result["target"]["space_id"] == "space-456"
        assert result["target"]["space_name"] == "Test Space"
        assert result["target"]["member_id"] == "member-789"
        assert result["target"]["member_name"] == "John Doe"
        assert result["target"]["member_email"] == "john@example.com"

    def test_role_modified_metadata_structure(self):
        """Test metadata structure for ROLE_MODIFIED with changes."""
        target = AuditTarget(
            id="member-789",  # Required id field
            name="John Doe",
            space_id="space-456",
            space_name="Test Space",
            member_id="member-789",
            member_name="John Doe",
            member_email="john@example.com",
        )

        metadata = AuditMetadata(
            actor=AuditActor(
                id="admin-123",
                name="Admin User",
                email="admin@example.com",
            ),
            target=target,
            changes={
                "role": AuditChange(old="member", new="admin"),
            },
        )

        result = metadata.to_dict()

        # Verify context and changes
        assert result["target"]["space_name"] == "Test Space"
        assert result["target"]["member_name"] == "John Doe"
        assert result["changes"]["role"]["old"] == "member"
        assert result["changes"]["role"]["new"] == "admin"
