"""Unit tests for audit category mappings."""

import json
from pathlib import Path

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.category_mappings import (
    CATEGORY_MAPPINGS,
    get_category_for_action,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_MESSAGES_DIR = REPO_ROOT / "frontend" / "apps" / "web" / "messages"


class TestCategoryMappings:
    """Test suite for audit category mappings."""

    def test_all_action_types_are_mapped(self):
        """Verify that all ActionType enum values have a category mapping."""
        all_action_values = set(action.value for action in ActionType)
        mapped_actions = set(CATEGORY_MAPPINGS.keys())

        # Check if any action types are missing from mappings
        unmapped_actions = all_action_values - mapped_actions
        assert not unmapped_actions, (
            f"The following action types are not mapped to categories: {unmapped_actions}"
        )

    def test_all_mappings_are_valid_action_types(self):
        """Verify that all mapped keys are valid ActionType string values."""
        all_action_values = set(action.value for action in ActionType)
        for action in CATEGORY_MAPPINGS.keys():
            assert action in all_action_values, (
                f"{action} is not a valid ActionType value"
            )

    def test_all_categories_are_valid(self):
        """Verify that all mapped categories are one of the 7 valid categories."""
        valid_categories = {
            "admin_actions",
            "user_actions",
            "security_events",
            "file_operations",
            "integration_events",
            "system_actions",
            "audit_access",
        }

        for category in CATEGORY_MAPPINGS.values():
            assert category in valid_categories, (
                f"Invalid category '{category}' found in mappings"
            )

    def test_admin_actions_mapping(self):
        """Verify specific admin action types are correctly mapped."""
        admin_action_types = [
            ActionType.USER_CREATED,
            ActionType.USER_DELETED,
            ActionType.USER_UPDATED,
            ActionType.ROLE_CREATED,
            ActionType.ROLE_MODIFIED,
            ActionType.ROLE_DELETED,
            ActionType.PERMISSION_CHANGED,
            ActionType.API_KEY_GENERATED,
            ActionType.API_KEY_CREATED,
            ActionType.API_KEY_UPDATED,
            ActionType.API_KEY_REVOKED,
            ActionType.API_KEY_SUSPENDED,
            ActionType.API_KEY_REACTIVATED,
            ActionType.API_KEY_ROTATED,
            ActionType.API_KEY_EXPIRATION_EXTENDED,
            ActionType.API_KEY_PURGED,
            ActionType.API_KEY_EXPIRED,
            ActionType.API_KEY_USED,
            ActionType.API_KEY_AUTH_FAILED,
            ActionType.TENANT_POLICY_UPDATED,
            ActionType.TENANT_SETTINGS_UPDATED,
            ActionType.CREDENTIALS_UPDATED,
            ActionType.FEDERATION_UPDATED,
            ActionType.MODULE_ADDED,
            ActionType.MODULE_ADDED_TO_TENANT,
        ]

        for action_type in admin_action_types:
            assert CATEGORY_MAPPINGS[action_type] == "admin_actions", (
                f"{action_type} should be mapped to 'admin_actions'"
            )

    def test_user_actions_mapping(self):
        """Verify representative user actions are mapped correctly."""
        user_action_types = [
            ActionType.TOOL_APPROVAL_SUBMITTED,
            ActionType.FLOW_CREATED,
            ActionType.FLOW_RUN_CREATED,
            ActionType.FLOW_RUN_RERUN_REQUESTED,
        ]

        for action_type in user_action_types:
            assert CATEGORY_MAPPINGS[action_type] == "user_actions", (
                f"{action_type} should be mapped to 'user_actions'"
            )

    def test_security_events_mapping(self):
        """Verify security event action types are correctly mapped."""
        security_actions = [
            ActionType.SECURITY_CLASSIFICATION_CREATED,
            ActionType.SECURITY_CLASSIFICATION_UPDATED,
            ActionType.SECURITY_CLASSIFICATION_DELETED,
            ActionType.SECURITY_CLASSIFICATION_LEVELS_UPDATED,
            ActionType.SECURITY_CLASSIFICATION_ENABLED,
            ActionType.SECURITY_CLASSIFICATION_DISABLED,
        ]

        for action_type in security_actions:
            assert CATEGORY_MAPPINGS[action_type] == "security_events", (
                f"{action_type} should be mapped to 'security_events'"
            )

    def test_file_operations_mapping(self):
        """Verify file operation action types are correctly mapped."""
        file_actions = [
            ActionType.FILE_UPLOADED,
            ActionType.FILE_DELETED,
        ]

        for action_type in file_actions:
            assert CATEGORY_MAPPINGS[action_type] == "file_operations", (
                f"{action_type} should be mapped to 'file_operations'"
            )

    def test_mcp_events_mapping(self):
        """Verify MCP action types are correctly mapped to integration_events."""
        mcp_actions = [
            ActionType.MCP_SERVER_CREATED,
            ActionType.MCP_SERVER_UPDATED,
            ActionType.MCP_SERVER_DELETED,
            ActionType.MCP_SERVER_ENABLED,
            ActionType.MCP_SERVER_DISABLED,
            ActionType.MCP_SERVER_TOOL_ENABLED,
            ActionType.MCP_SERVER_TOOL_DISABLED,
        ]

        for action_type in mcp_actions:
            assert CATEGORY_MAPPINGS[action_type] == "integration_events", (
                f"{action_type} should be mapped to 'integration_events'"
            )

    def test_system_actions_mapping(self):
        """Verify system action types are correctly mapped."""
        system_actions = [
            ActionType.RETENTION_POLICY_APPLIED,
            ActionType.ENCRYPTION_KEY_ROTATED,
            ActionType.SYSTEM_MAINTENANCE,
        ]

        for action_type in system_actions:
            assert CATEGORY_MAPPINGS[action_type] == "system_actions", (
                f"{action_type} should be mapped to 'system_actions'"
            )

    def test_audit_access_mapping(self):
        """Verify audit access action types are correctly mapped."""
        audit_actions = [
            ActionType.AUDIT_SESSION_CREATED,
            ActionType.AUDIT_LOG_VIEWED,
            ActionType.AUDIT_LOG_EXPORTED,
        ]

        for action_type in audit_actions:
            assert CATEGORY_MAPPINGS[action_type] == "audit_access", (
                f"{action_type} should be mapped to 'audit_access'"
            )


class TestGetCategoryForAction:
    """Test suite for get_category_for_action() helper function."""

    def test_get_category_for_known_action(self):
        """Test getting category for a known action type."""
        assert get_category_for_action(ActionType.USER_CREATED.value) == "admin_actions"
        assert (
            get_category_for_action(ActionType.ASSISTANT_CREATED.value)
            == "user_actions"
        )
        assert (
            get_category_for_action(ActionType.FILE_UPLOADED.value) == "file_operations"
        )
        assert (
            get_category_for_action(ActionType.AUDIT_LOG_VIEWED.value) == "audit_access"
        )

    def test_get_category_for_unknown_action_defaults_to_user_actions(self):
        """Test that unknown action types default to 'user_actions'."""
        unknown_action = "unknown_action_type"
        assert get_category_for_action(unknown_action) == "user_actions"

    def test_get_category_accepts_string_values(self):
        """Test that the function accepts string values (not just enums)."""
        # Should work with string values
        assert get_category_for_action("user_created") == "admin_actions"
        assert get_category_for_action("file_uploaded") == "file_operations"


class TestCategoryDistribution:
    """Test suite for verifying balanced distribution of action types across categories."""

    def test_total_mapped_actions_count(self):
        """Verify the total number of mapped action types."""
        # We should have all ActionType enum values mapped
        total_mapped = len(CATEGORY_MAPPINGS)
        total_action_types = len(ActionType)

        assert total_mapped == total_action_types, (
            f"Expected {total_action_types} mappings, got {total_mapped}"
        )

    def test_no_category_is_empty(self):
        """Verify that no category has zero action types mapped to it."""
        categories = [
            "admin_actions",
            "user_actions",
            "security_events",
            "file_operations",
            "integration_events",
            "system_actions",
            "audit_access",
        ]

        for category in categories:
            count = sum(1 for cat in CATEGORY_MAPPINGS.values() if cat == category)
            assert count > 0, f"Category '{category}' has no action types mapped to it"


class TestActionMessageCatalog:
    """Verify that every backend audit action has frontend display messages."""

    def test_all_action_types_have_en_and_sv_messages(self):
        locales = {
            locale: json.loads((FRONTEND_MESSAGES_DIR / f"{locale}.json").read_text())
            for locale in ("en", "sv")
        }

        missing_or_empty = []
        for action in ActionType:
            for locale, messages in locales.items():
                for key in (
                    f"audit_action_{action.value}",
                    f"audit_action_{action.value}_description",
                ):
                    if not messages.get(key):
                        missing_or_empty.append(f"{locale}:{key}")

        assert not missing_or_empty, (
            "Missing or empty audit action messages: "
            f"{', '.join(sorted(missing_or_empty))}"
        )
