"""Unit tests for AuditConfigService - testing all 7 categories and configurations."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID

from intric.audit.application.audit_config_service import (
    AuditConfigService,
    AUDIT_CONFIG_CACHE_TTL,
)
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.category_mappings import (
    CATEGORY_DESCRIPTIONS,
    CATEGORY_MAPPINGS,
)


# === All 7 Categories (ordered) ===
ALL_CATEGORIES = [
    "admin_actions",
    "user_actions",
    "security_events",
    "file_operations",
    "integration_events",
    "system_actions",
    "audit_access",
]

# Expected action counts per category
EXPECTED_CATEGORY_COUNTS = {
    "admin_actions": 13,
    "user_actions": 28,
    "security_events": 6,
    "file_operations": 2,
    "integration_events": 11,
    "system_actions": 3,
    "audit_access": 3,  # Includes AUDIT_SESSION_CREATED
}


@pytest.fixture
def mock_repository():
    """Create a mock audit config repository."""
    return AsyncMock()


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    return redis


@pytest.fixture
def config_service(mock_repository, mock_redis):
    """Create AuditConfigService with mocked dependencies."""
    with patch("intric.audit.application.audit_config_service.get_redis", return_value=mock_redis):
        service = AuditConfigService(mock_repository)
        return service


class TestCacheConfiguration:
    """Tests for cache TTL and key format."""

    def test_cache_ttl_is_60_seconds(self):
        """Verify cache TTL constant is 60 seconds."""
        assert AUDIT_CONFIG_CACHE_TTL == 60

    def test_cache_key_format_category(self, config_service):
        """Verify category cache key format: audit_config:{tenant_id}:{category}."""
        tenant_id = uuid4()
        key = config_service._cache_key(tenant_id, "admin_actions")
        assert key == f"audit_config:{tenant_id}:admin_actions"

    def test_cache_key_format_action(self, config_service):
        """Verify action cache key format: audit_action:{tenant_id}:{action}."""
        tenant_id = uuid4()
        key = config_service._action_cache_key(tenant_id, "user_created")
        assert key == f"audit_action:{tenant_id}:user_created"


class TestIsCategoryEnabled:
    """Tests for is_category_enabled() with all 7 categories."""

    @pytest.mark.parametrize("category", ALL_CATEGORIES)
    async def test_category_enabled_from_cache(self, config_service, mock_redis, category):
        """Test each of the 7 categories returns enabled from cache."""
        tenant_id = uuid4()
        mock_redis.get.return_value = b"true"

        result = await config_service.is_category_enabled(tenant_id, category)

        assert result is True
        mock_redis.get.assert_called_once()

    @pytest.mark.parametrize("category", ALL_CATEGORIES)
    async def test_category_disabled_from_cache(self, config_service, mock_redis, category):
        """Test each of the 7 categories returns disabled from cache."""
        tenant_id = uuid4()
        mock_redis.get.return_value = b"false"

        result = await config_service.is_category_enabled(tenant_id, category)

        assert result is False

    async def test_cache_miss_queries_database(self, config_service, mock_repository, mock_redis):
        """Test cache miss falls back to database query."""
        tenant_id = uuid4()
        mock_redis.get.return_value = None  # Cache miss
        mock_repository.find_by_tenant_and_category.return_value = ("admin_actions", True, {})

        result = await config_service.is_category_enabled(tenant_id, "admin_actions")

        assert result is True
        mock_repository.find_by_tenant_and_category.assert_called_once_with(
            tenant_id, "admin_actions"
        )

    async def test_database_miss_defaults_to_enabled(self, config_service, mock_repository, mock_redis):
        """Test no config in database defaults to enabled (backward compatible)."""
        tenant_id = uuid4()
        mock_redis.get.return_value = None
        mock_repository.find_by_tenant_and_category.return_value = None  # No config

        result = await config_service.is_category_enabled(tenant_id, "admin_actions")

        assert result is True  # Default to enabled

    async def test_cache_miss_stores_result_in_cache(self, config_service, mock_repository, mock_redis):
        """Test database result gets cached for 60 seconds."""
        tenant_id = uuid4()
        mock_redis.get.return_value = None
        mock_repository.find_by_tenant_and_category.return_value = ("admin_actions", False, {})

        await config_service.is_category_enabled(tenant_id, "admin_actions")

        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][1] == "false"
        assert call_args[1]["ex"] == 60

    async def test_redis_error_falls_back_to_database(self, config_service, mock_repository, mock_redis):
        """Test Redis error gracefully falls back to database."""
        tenant_id = uuid4()
        mock_redis.get.side_effect = Exception("Redis connection error")
        mock_repository.find_by_tenant_and_category.return_value = ("admin_actions", True, {})

        result = await config_service.is_category_enabled(tenant_id, "admin_actions")

        assert result is True

    async def test_database_error_defaults_to_enabled(self, config_service, mock_repository, mock_redis):
        """Test database error defaults to enabled (fail-safe)."""
        tenant_id = uuid4()
        mock_redis.get.return_value = None
        mock_repository.find_by_tenant_and_category.side_effect = Exception("Database error")

        result = await config_service.is_category_enabled(tenant_id, "admin_actions")

        assert result is True  # Fail-safe: don't lose audit logs


class TestGetConfig:
    """Tests for get_config() returning all 7 categories with metadata."""

    async def test_get_config_returns_all_seven_categories(self, config_service, mock_repository):
        """Verify get_config returns all 7 categories."""
        tenant_id = uuid4()
        mock_repository.find_by_tenant.return_value = []

        result = await config_service.get_config(tenant_id)

        assert len(result.categories) == 7
        category_names = [c.category for c in result.categories]
        assert category_names == ALL_CATEGORIES

    async def test_get_config_includes_descriptions(self, config_service, mock_repository):
        """Verify each category includes correct description."""
        tenant_id = uuid4()
        mock_repository.find_by_tenant.return_value = []

        result = await config_service.get_config(tenant_id)

        for cat_config in result.categories:
            assert cat_config.description == CATEGORY_DESCRIPTIONS[cat_config.category]

    async def test_get_config_includes_action_counts(self, config_service, mock_repository):
        """Verify each category includes correct action count."""
        tenant_id = uuid4()
        mock_repository.find_by_tenant.return_value = []

        result = await config_service.get_config(tenant_id)

        for cat_config in result.categories:
            expected_count = EXPECTED_CATEGORY_COUNTS[cat_config.category]
            assert cat_config.action_count == expected_count, (
                f"Category {cat_config.category} should have {expected_count} actions, "
                f"got {cat_config.action_count}"
            )

    async def test_get_config_includes_example_actions(self, config_service, mock_repository):
        """Verify each category includes up to 3 example actions."""
        tenant_id = uuid4()
        mock_repository.find_by_tenant.return_value = []

        result = await config_service.get_config(tenant_id)

        for cat_config in result.categories:
            assert len(cat_config.example_actions) <= 3
            assert len(cat_config.example_actions) > 0  # At least 1 example

    async def test_get_config_default_enabled_state(self, config_service, mock_repository):
        """Verify categories default to enabled when no config exists."""
        tenant_id = uuid4()
        mock_repository.find_by_tenant.return_value = []

        result = await config_service.get_config(tenant_id)

        for cat_config in result.categories:
            assert cat_config.enabled is True

    async def test_get_config_respects_database_state(self, config_service, mock_repository):
        """Verify get_config respects database enabled state."""
        tenant_id = uuid4()
        mock_repository.find_by_tenant.return_value = [
            ("admin_actions", False),
            ("user_actions", True),
            ("security_events", False),
        ]

        result = await config_service.get_config(tenant_id)

        config_dict = {c.category: c.enabled for c in result.categories}
        assert config_dict["admin_actions"] is False
        assert config_dict["user_actions"] is True
        assert config_dict["security_events"] is False
        # Unconfigured categories default to True
        assert config_dict["file_operations"] is True
        assert config_dict["audit_access"] is True


class TestUpdateConfig:
    """Tests for update_config() updating categories."""

    async def test_update_config_calls_repository(self, config_service, mock_repository, mock_redis):
        """Verify update_config calls repository for each update."""
        tenant_id = uuid4()
        mock_repository.find_by_tenant.return_value = []

        from intric.audit.schemas.audit_config_schemas import CategoryUpdate

        updates = [
            CategoryUpdate(category="admin_actions", enabled=False),
            CategoryUpdate(category="security_events", enabled=False),
        ]

        await config_service.update_config(tenant_id, updates)

        assert mock_repository.update.call_count == 2
        mock_repository.update.assert_any_call(tenant_id, "admin_actions", False)
        mock_repository.update.assert_any_call(tenant_id, "security_events", False)

    async def test_update_config_invalidates_cache(self, config_service, mock_repository, mock_redis):
        """Verify update_config invalidates Redis cache for category AND actions."""
        tenant_id = uuid4()
        mock_repository.find_by_tenant.return_value = []

        from intric.audit.schemas.audit_config_schemas import CategoryUpdate
        from intric.audit.domain.category_mappings import CATEGORY_MAPPINGS

        updates = [CategoryUpdate(category="admin_actions", enabled=False)]

        await config_service.update_config(tenant_id, updates)

        # Category cache should be invalidated
        expected_category_key = f"audit_config:{tenant_id}:admin_actions"
        delete_calls = [str(call) for call in mock_redis.delete.call_args_list]
        assert any(expected_category_key in call for call in delete_calls), \
            f"Category cache {expected_category_key} should be invalidated"

        # All action caches for this category should also be invalidated
        actions_in_category = [
            action for action, cat in CATEGORY_MAPPINGS.items()
            if cat == "admin_actions"
        ]
        # 1 category + N actions in admin_actions category
        expected_calls = 1 + len(actions_in_category)
        assert mock_redis.delete.call_count == expected_calls, \
            f"Expected {expected_calls} cache invalidations (1 category + {len(actions_in_category)} actions)"

    async def test_update_config_returns_updated_config(self, config_service, mock_repository, mock_redis):
        """Verify update_config returns updated AuditConfigResponse."""
        tenant_id = uuid4()
        mock_repository.find_by_tenant.return_value = [("admin_actions", False)]

        from intric.audit.schemas.audit_config_schemas import CategoryUpdate

        updates = [CategoryUpdate(category="admin_actions", enabled=False)]

        result = await config_service.update_config(tenant_id, updates)

        assert len(result.categories) == 7
        admin_config = next(c for c in result.categories if c.category == "admin_actions")
        assert admin_config.enabled is False


class TestIsActionEnabled:
    """Tests for is_action_enabled() 3-level check."""

    async def test_action_enabled_from_cache(self, config_service, mock_redis):
        """Test action enabled status from cache."""
        tenant_id = uuid4()
        mock_redis.get.return_value = b"true"

        result = await config_service.is_action_enabled(tenant_id, "user_created")

        assert result is True

    async def test_action_disabled_from_cache(self, config_service, mock_redis):
        """Test action disabled status from cache."""
        tenant_id = uuid4()
        mock_redis.get.return_value = b"false"

        result = await config_service.is_action_enabled(tenant_id, "user_created")

        assert result is False

    async def test_action_uses_category_state_when_no_override(self, config_service, mock_repository, mock_redis):
        """Test action inherits category enabled state when no override."""
        tenant_id = uuid4()
        mock_redis.get.return_value = None
        mock_repository.find_by_tenant_and_category.return_value = (
            "admin_actions",
            True,  # category enabled
            {},  # no overrides
        )

        result = await config_service.is_action_enabled(tenant_id, "user_created")

        assert result is True

    async def test_action_override_takes_precedence(self, config_service, mock_repository, mock_redis):
        """Test action override takes precedence over category state."""
        tenant_id = uuid4()
        mock_redis.get.return_value = None
        mock_repository.find_by_tenant_and_category.return_value = (
            "admin_actions",
            True,  # category enabled
            {"user_created": False},  # action override: disabled
        )

        result = await config_service.is_action_enabled(tenant_id, "user_created")

        assert result is False  # Override wins

    async def test_action_override_enables_when_category_disabled(self, config_service, mock_repository, mock_redis):
        """Test action can be enabled even when category is disabled."""
        tenant_id = uuid4()
        mock_redis.get.return_value = None
        mock_repository.find_by_tenant_and_category.return_value = (
            "admin_actions",
            False,  # category disabled
            {"user_created": True},  # action override: enabled
        )

        result = await config_service.is_action_enabled(tenant_id, "user_created")

        assert result is True  # Override wins

    async def test_action_default_enabled_when_no_config(self, config_service, mock_repository, mock_redis):
        """Test action defaults to enabled when no config exists."""
        tenant_id = uuid4()
        mock_redis.get.return_value = None
        mock_repository.find_by_tenant_and_category.return_value = None

        result = await config_service.is_action_enabled(tenant_id, "user_created")

        assert result is True

    async def test_action_caches_result(self, config_service, mock_repository, mock_redis):
        """Test action enabled result gets cached."""
        tenant_id = uuid4()
        mock_redis.get.return_value = None
        mock_repository.find_by_tenant_and_category.return_value = ("admin_actions", True, {})

        await config_service.is_action_enabled(tenant_id, "user_created")

        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert "audit_action:" in call_args[0][0]


class TestGetActionConfig:
    """Tests for get_action_config() returning all 66 actions with metadata."""

    async def test_get_action_config_returns_all_actions(self, config_service, mock_repository):
        """Verify get_action_config returns all action types."""
        tenant_id = uuid4()
        mock_repository.find_all_by_tenant.return_value = []

        result = await config_service.get_action_config(tenant_id)

        total_expected = len(ActionType)
        assert len(result.actions) == total_expected

    async def test_get_action_config_includes_swedish_metadata(self, config_service, mock_repository):
        """Verify actions include Swedish names and descriptions."""
        tenant_id = uuid4()
        mock_repository.find_all_by_tenant.return_value = []

        result = await config_service.get_action_config(tenant_id)

        for action_config in result.actions:
            assert action_config.name_sv is not None
            assert action_config.description_sv is not None
            assert len(action_config.name_sv) > 0
            assert len(action_config.description_sv) > 0

    async def test_get_action_config_includes_category(self, config_service, mock_repository):
        """Verify each action includes its category."""
        tenant_id = uuid4()
        mock_repository.find_all_by_tenant.return_value = []

        result = await config_service.get_action_config(tenant_id)

        for action_config in result.actions:
            assert action_config.category in ALL_CATEGORIES

    async def test_get_action_config_sorted_by_category_then_action(self, config_service, mock_repository):
        """Verify actions are sorted by category, then action name."""
        tenant_id = uuid4()
        mock_repository.find_all_by_tenant.return_value = []

        result = await config_service.get_action_config(tenant_id)

        # Verify sorting
        for i in range(1, len(result.actions)):
            prev = result.actions[i - 1]
            curr = result.actions[i]
            # Either current category is after previous, or same category with action >= previous
            assert (curr.category > prev.category) or (
                curr.category == prev.category and curr.action >= prev.action
            )

    async def test_get_action_config_default_enabled_state(self, config_service, mock_repository):
        """Verify actions default to enabled when no config."""
        tenant_id = uuid4()
        mock_repository.find_all_by_tenant.return_value = []

        result = await config_service.get_action_config(tenant_id)

        for action_config in result.actions:
            assert action_config.enabled is True

    async def test_get_action_config_respects_category_state(self, config_service, mock_repository):
        """Verify actions inherit category enabled state."""
        tenant_id = uuid4()
        mock_repository.find_all_by_tenant.return_value = [
            ("admin_actions", False, {}),  # Disabled category
            ("user_actions", True, {}),
        ]

        result = await config_service.get_action_config(tenant_id)

        for action_config in result.actions:
            if action_config.category == "admin_actions":
                assert action_config.enabled is False
            elif action_config.category == "user_actions":
                assert action_config.enabled is True

    async def test_get_action_config_respects_action_overrides(self, config_service, mock_repository):
        """Verify action overrides take precedence."""
        tenant_id = uuid4()
        mock_repository.find_all_by_tenant.return_value = [
            ("admin_actions", False, {"user_created": True}),  # Category off, action on
        ]

        result = await config_service.get_action_config(tenant_id)

        user_created_action = next(
            a for a in result.actions if a.action == "user_created"
        )
        assert user_created_action.enabled is True  # Override wins


class TestUpdateActionConfig:
    """Tests for update_action_config() with action overrides."""

    async def test_update_action_config_updates_overrides(self, config_service, mock_repository, mock_redis):
        """Verify update_action_config stores action overrides."""
        tenant_id = uuid4()
        mock_repository.find_by_tenant_and_category.return_value = ("admin_actions", True, {})
        mock_repository.find_all_by_tenant.return_value = []

        from intric.audit.schemas.audit_config_schemas import ActionUpdate

        updates = [ActionUpdate(action="user_created", enabled=False)]

        await config_service.update_action_config(tenant_id, updates)

        mock_repository.update.assert_called_once()
        call_args = mock_repository.update.call_args
        assert call_args[0][0] == tenant_id
        assert call_args[0][1] == "admin_actions"
        assert call_args[0][2] is True  # Preserve category enabled
        assert call_args[0][3] == {"user_created": False}  # New override

    async def test_update_action_config_merges_overrides(self, config_service, mock_repository, mock_redis):
        """Verify new overrides merge with existing ones."""
        tenant_id = uuid4()
        mock_repository.find_by_tenant_and_category.return_value = (
            "admin_actions",
            True,
            {"user_deleted": True},  # Existing override
        )
        mock_repository.find_all_by_tenant.return_value = []

        from intric.audit.schemas.audit_config_schemas import ActionUpdate

        updates = [ActionUpdate(action="user_created", enabled=False)]

        await config_service.update_action_config(tenant_id, updates)

        call_args = mock_repository.update.call_args
        expected_overrides = {"user_deleted": True, "user_created": False}
        assert call_args[0][3] == expected_overrides

    async def test_update_action_config_invalidates_cache(self, config_service, mock_repository, mock_redis):
        """Verify update_action_config invalidates action cache."""
        tenant_id = uuid4()
        mock_repository.find_by_tenant_and_category.return_value = ("admin_actions", True, {})
        mock_repository.find_all_by_tenant.return_value = []

        from intric.audit.schemas.audit_config_schemas import ActionUpdate

        updates = [ActionUpdate(action="user_created", enabled=False)]

        await config_service.update_action_config(tenant_id, updates)

        mock_redis.delete.assert_called_once()

    async def test_update_action_config_creates_category_if_missing(self, config_service, mock_repository, mock_redis):
        """Verify update_action_config creates category config if it doesn't exist."""
        tenant_id = uuid4()
        mock_repository.find_by_tenant_and_category.return_value = None  # No category config
        mock_repository.find_all_by_tenant.return_value = []

        from intric.audit.schemas.audit_config_schemas import ActionUpdate

        updates = [ActionUpdate(action="user_created", enabled=False)]

        await config_service.update_action_config(tenant_id, updates)

        call_args = mock_repository.update.call_args
        assert call_args[0][2] is True  # Default category enabled
        assert call_args[0][3] == {"user_created": False}


class TestAllCategoriesHaveCorrectActionCounts:
    """Verify each category has the expected number of actions mapped."""

    def test_admin_actions_has_13_actions(self):
        """Verify admin_actions has 13 action types."""
        count = sum(1 for cat in CATEGORY_MAPPINGS.values() if cat == "admin_actions")
        assert count == 13

    def test_user_actions_has_28_actions(self):
        """Verify user_actions has 28 action types."""
        count = sum(1 for cat in CATEGORY_MAPPINGS.values() if cat == "user_actions")
        assert count == 28

    def test_security_events_has_6_actions(self):
        """Verify security_events has 6 action types."""
        count = sum(1 for cat in CATEGORY_MAPPINGS.values() if cat == "security_events")
        assert count == 6

    def test_file_operations_has_2_actions(self):
        """Verify file_operations has 2 action types."""
        count = sum(1 for cat in CATEGORY_MAPPINGS.values() if cat == "file_operations")
        assert count == 2

    def test_integration_events_has_11_actions(self):
        """Verify integration_events has 11 action types."""
        count = sum(1 for cat in CATEGORY_MAPPINGS.values() if cat == "integration_events")
        assert count == 11

    def test_system_actions_has_3_actions(self):
        """Verify system_actions has 3 action types."""
        count = sum(1 for cat in CATEGORY_MAPPINGS.values() if cat == "system_actions")
        assert count == 3

    def test_audit_access_has_3_actions(self):
        """Verify audit_access has 3 action types (including AUDIT_SESSION_CREATED)."""
        count = sum(1 for cat in CATEGORY_MAPPINGS.values() if cat == "audit_access")
        assert count == 3, (
            "audit_access should have 3 actions: "
            "AUDIT_SESSION_CREATED, AUDIT_LOG_VIEWED, AUDIT_LOG_EXPORTED"
        )

    def test_total_actions_equals_action_type_count(self):
        """Verify total mapped actions equals ActionType enum count."""
        total_mapped = len(CATEGORY_MAPPINGS)
        total_action_types = len(ActionType)
        assert total_mapped == total_action_types


class TestAuditAccessCategory:
    """Specific tests for audit_access category (identified bug area)."""

    def test_audit_session_created_is_in_audit_access(self):
        """Verify AUDIT_SESSION_CREATED is mapped to audit_access."""
        assert ActionType.AUDIT_SESSION_CREATED.value in CATEGORY_MAPPINGS
        assert CATEGORY_MAPPINGS[ActionType.AUDIT_SESSION_CREATED.value] == "audit_access"

    def test_audit_log_viewed_is_in_audit_access(self):
        """Verify AUDIT_LOG_VIEWED is mapped to audit_access."""
        assert CATEGORY_MAPPINGS[ActionType.AUDIT_LOG_VIEWED.value] == "audit_access"

    def test_audit_log_exported_is_in_audit_access(self):
        """Verify AUDIT_LOG_EXPORTED is mapped to audit_access."""
        assert CATEGORY_MAPPINGS[ActionType.AUDIT_LOG_EXPORTED.value] == "audit_access"

    def test_all_audit_access_actions_list(self):
        """Verify complete list of audit_access actions."""
        expected_actions = {
            ActionType.AUDIT_SESSION_CREATED.value,
            ActionType.AUDIT_LOG_VIEWED.value,
            ActionType.AUDIT_LOG_EXPORTED.value,
        }
        actual_actions = {
            action for action, cat in CATEGORY_MAPPINGS.items()
            if cat == "audit_access"
        }
        assert actual_actions == expected_actions
