"""Unit tests for audit category mappings."""

import pytest

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.category_mappings import (
    CATEGORY_DESCRIPTIONS,
    CATEGORY_MAPPINGS,
    get_category_for_action,
)


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
            assert action in all_action_values, f"{action} is not a valid ActionType value"

    def test_all_categories_are_valid(self):
        """Verify that all mapped categories are one of the 7 valid categories."""
        valid_categories = {
            'admin_actions',
            'user_actions',
            'security_events',
            'file_operations',
            'integration_events',
            'system_actions',
            'audit_access',
        }

        for category in CATEGORY_MAPPINGS.values():
            assert category in valid_categories, (
                f"Invalid category '{category}' found in mappings"
            )

    def test_admin_actions_count(self):
        """Verify that admin_actions category has correct number of action types."""
        admin_actions = [
            action for action, cat in CATEGORY_MAPPINGS.items()
            if cat == 'admin_actions'
        ]
        assert len(admin_actions) == 13, (
            f"Expected 13 admin actions, got {len(admin_actions)}"
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
            ActionType.TENANT_SETTINGS_UPDATED,
            ActionType.CREDENTIALS_UPDATED,
            ActionType.FEDERATION_UPDATED,
            ActionType.MODULE_ADDED,
            ActionType.MODULE_ADDED_TO_TENANT,
        ]

        for action_type in admin_action_types:
            assert CATEGORY_MAPPINGS[action_type] == 'admin_actions', (
                f"{action_type} should be mapped to 'admin_actions'"
            )

    def test_user_actions_count(self):
        """Verify that user_actions category has correct number of action types."""
        user_actions = [
            action for action, cat in CATEGORY_MAPPINGS.items()
            if cat == 'user_actions'
        ]
        assert len(user_actions) == 28, (
            f"Expected 28 user actions, got {len(user_actions)}"
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
            assert CATEGORY_MAPPINGS[action_type] == 'security_events', (
                f"{action_type} should be mapped to 'security_events'"
            )

    def test_file_operations_mapping(self):
        """Verify file operation action types are correctly mapped."""
        file_actions = [
            ActionType.FILE_UPLOADED,
            ActionType.FILE_DELETED,
        ]

        for action_type in file_actions:
            assert CATEGORY_MAPPINGS[action_type] == 'file_operations', (
                f"{action_type} should be mapped to 'file_operations'"
            )

    def test_integration_events_count(self):
        """Verify that integration_events category has correct number of action types."""
        integration_actions = [
            action for action, cat in CATEGORY_MAPPINGS.items()
            if cat == 'integration_events'
        ]
        assert len(integration_actions) == 11, (
            f"Expected 11 integration events, got {len(integration_actions)}"
        )

    def test_system_actions_mapping(self):
        """Verify system action types are correctly mapped."""
        system_actions = [
            ActionType.RETENTION_POLICY_APPLIED,
            ActionType.ENCRYPTION_KEY_ROTATED,
            ActionType.SYSTEM_MAINTENANCE,
        ]

        for action_type in system_actions:
            assert CATEGORY_MAPPINGS[action_type] == 'system_actions', (
                f"{action_type} should be mapped to 'system_actions'"
            )

    def test_audit_access_mapping(self):
        """Verify audit access action types are correctly mapped."""
        audit_actions = [
            ActionType.AUDIT_LOG_VIEWED,
            ActionType.AUDIT_LOG_EXPORTED,
        ]

        for action_type in audit_actions:
            assert CATEGORY_MAPPINGS[action_type] == 'audit_access', (
                f"{action_type} should be mapped to 'audit_access'"
            )


class TestGetCategoryForAction:
    """Test suite for get_category_for_action() helper function."""

    def test_get_category_for_known_action(self):
        """Test getting category for a known action type."""
        assert get_category_for_action(ActionType.USER_CREATED.value) == 'admin_actions'
        assert get_category_for_action(ActionType.ASSISTANT_CREATED.value) == 'user_actions'
        assert get_category_for_action(ActionType.FILE_UPLOADED.value) == 'file_operations'
        assert get_category_for_action(ActionType.AUDIT_LOG_VIEWED.value) == 'audit_access'

    def test_get_category_for_unknown_action_defaults_to_user_actions(self):
        """Test that unknown action types default to 'user_actions'."""
        unknown_action = "unknown_action_type"
        assert get_category_for_action(unknown_action) == 'user_actions'

    def test_get_category_accepts_string_values(self):
        """Test that the function accepts string values (not just enums)."""
        # Should work with string values
        assert get_category_for_action("user_created") == 'admin_actions'
        assert get_category_for_action("file_uploaded") == 'file_operations'


class TestCategoryDescriptions:
    """Test suite for category descriptions."""

    def test_all_seven_categories_have_descriptions(self):
        """Verify that all 7 categories have descriptions."""
        expected_categories = {
            'admin_actions',
            'user_actions',
            'security_events',
            'file_operations',
            'integration_events',
            'system_actions',
            'audit_access',
        }

        assert set(CATEGORY_DESCRIPTIONS.keys()) == expected_categories

    def test_descriptions_are_non_empty_strings(self):
        """Verify that all descriptions are non-empty strings."""
        for category, description in CATEGORY_DESCRIPTIONS.items():
            assert isinstance(description, str), (
                f"Description for {category} should be a string"
            )
            assert len(description) > 0, (
                f"Description for {category} should not be empty"
            )

    def test_specific_category_descriptions(self):
        """Verify specific category descriptions are correct."""
        assert CATEGORY_DESCRIPTIONS['admin_actions'] == (
            'User management, role changes, API keys, tenant settings'
        )
        assert CATEGORY_DESCRIPTIONS['user_actions'] == (
            'Assistant, space, app operations, templates, model configs'
        )
        assert CATEGORY_DESCRIPTIONS['security_events'] == (
            'Security classification lifecycle events'
        )
        assert CATEGORY_DESCRIPTIONS['file_operations'] == (
            'File uploads and deletions'
        )
        assert CATEGORY_DESCRIPTIONS['integration_events'] == (
            'Integration connections, knowledge sources, website crawling'
        )
        assert CATEGORY_DESCRIPTIONS['system_actions'] == (
            'Retention policies, encryption, maintenance'
        )
        assert CATEGORY_DESCRIPTIONS['audit_access'] == (
            'Viewing and exporting audit logs'
        )


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
            'admin_actions',
            'user_actions',
            'security_events',
            'file_operations',
            'integration_events',
            'system_actions',
            'audit_access',
        ]

        for category in categories:
            count = sum(1 for cat in CATEGORY_MAPPINGS.values() if cat == category)
            assert count > 0, f"Category '{category}' has no action types mapped to it"

    def test_category_counts_match_expected(self):
        """Verify exact counts for each category."""
        expected_counts = {
            'admin_actions': 13,
            'user_actions': 28,
            'security_events': 6,
            'file_operations': 2,
            'integration_events': 11,
            'system_actions': 3,
            'audit_access': 2,
        }

        for category, expected_count in expected_counts.items():
            actual_count = sum(
                1 for cat in CATEGORY_MAPPINGS.values() if cat == category
            )
            assert actual_count == expected_count, (
                f"Category '{category}' should have {expected_count} actions, "
                f"but has {actual_count}"
            )
