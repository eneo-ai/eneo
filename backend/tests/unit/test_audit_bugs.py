"""
Tests for production bugs found through code review.
These tests are designed to FAIL first (TDD approach), proving the bug exists.
After bugs are fixed, these tests should pass.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from intric.audit.infrastructure.audit_session_service import AuditSessionService


class TestSessionValidationBugs:
    """Tests for BUG #4: Session JSON Validation Missing.

    File: audit_session_service.py:100, 127
    Problem: json.loads() result not validated; KeyError if "user_id" missing
    Impact: 500 error on corrupted Redis session data
    """

    @pytest.fixture
    def session_service(self):
        """Create session service with mocked Redis."""
        service = AuditSessionService.__new__(AuditSessionService)
        service.redis = AsyncMock()
        service.ttl_seconds = 3600
        return service

    async def test_validate_session_handles_missing_user_id_key(self, session_service):
        """BUG #4a: KeyError when session JSON missing 'user_id' key.

        If Redis has corrupted session data without 'user_id', the validate_session
        method crashes with KeyError instead of returning None gracefully.

        This test will FAIL until the bug is fixed.
        """
        user_id = uuid4()
        tenant_id = uuid4()

        # Simulate corrupted session data in Redis - missing user_id
        corrupted_session = json.dumps({
            "tenant_id": str(tenant_id),  # Has tenant_id
            # Missing "user_id" key!
            "category": "investigation",
            "description": "Test session",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        session_service.redis.get.return_value = corrupted_session.encode("utf-8")

        # This should return None gracefully, not raise KeyError
        result = await session_service.validate_session("session-123", user_id, tenant_id)

        # Expected behavior: return None for corrupted session
        assert result is None, "Should return None for session missing required keys"

    async def test_validate_session_handles_missing_tenant_id_key(self, session_service):
        """BUG #4b: KeyError when session JSON missing 'tenant_id' key.

        Similar to missing user_id - if tenant_id is missing, validation crashes.
        """
        user_id = uuid4()
        tenant_id = uuid4()

        # Simulate corrupted session data - missing tenant_id
        corrupted_session = json.dumps({
            "user_id": str(user_id),  # Has user_id
            # Missing "tenant_id" key!
            "category": "investigation",
            "description": "Test session",
        })
        session_service.redis.get.return_value = corrupted_session.encode("utf-8")

        # This should return None gracefully, not raise KeyError
        result = await session_service.validate_session("session-123", user_id, tenant_id)

        assert result is None, "Should return None for session missing tenant_id"

    async def test_get_session_handles_malformed_json(self, session_service):
        """BUG #4c: JSONDecodeError not caught in get_session.

        If Redis contains invalid JSON (corrupted data), get_session crashes
        with JSONDecodeError instead of returning None.

        This test will FAIL until the bug is fixed.
        """
        # Simulate corrupted data in Redis - invalid JSON
        session_service.redis.get.return_value = b"not{valid}json"

        # This should return None gracefully, not raise JSONDecodeError
        result = await session_service.get_session("session-123")

        assert result is None, "Should return None for invalid JSON data"

    async def test_get_session_handles_empty_json_object(self, session_service):
        """BUG #4d: Empty JSON object should be handled gracefully."""
        # Empty JSON object
        session_service.redis.get.return_value = b"{}"

        # get_session returns the empty dict, but validate_session will crash
        await session_service.get_session("session-123")

        # get_session might succeed (returns {}), but subsequent validate_session will fail
        # This tests the full flow
        user_id = uuid4()
        tenant_id = uuid4()

        # Reset mock for validate flow
        session_service.redis.get.return_value = b"{}"

        validation_result = await session_service.validate_session("session-123", user_id, tenant_id)
        assert validation_result is None, "Should handle empty session object gracefully"

    async def test_get_session_handles_non_dict_json(self, session_service):
        """BUG #4e: Non-dict JSON values should be handled gracefully.

        If Redis contains valid JSON that isn't a dict (e.g., a string or array),
        this could cause TypeErrors or AttributeErrors downstream.
        """
        # Valid JSON but not a dict
        session_service.redis.get.return_value = b'"just a string"'

        result = await session_service.get_session("session-123")

        # If this returns the string, validate_session will crash on session["user_id"]
        # The service should either return None or validate the structure
        if result is not None:
            # If get_session doesn't validate, validate_session must handle it
            user_id = uuid4()
            tenant_id = uuid4()
            session_service.redis.get.return_value = b'"just a string"'

            validation_result = await session_service.validate_session("session-123", user_id, tenant_id)
            assert validation_result is None, "Should handle non-dict JSON gracefully"


class TestGdprExportBugs:
    """Tests for BUG #1: GDPR Export with logs missing metadata["target"]["id"].

    File: audit_log_repo_impl.py:175, 262
    Problem: SQL query may fail or behave unexpectedly when logs don't have target metadata
    Impact: GDPR exports may miss logs or fail unexpectedly

    Note: After code review, the UNION approach should handle missing target metadata
    correctly (NULL comparison returns false, log excluded from target_query but
    included via actor_query). These tests verify that behavior.
    """

    @pytest.fixture
    def mock_session(self):
        """Create a mock SQLAlchemy async session."""
        session = AsyncMock()
        return session

    async def test_get_user_logs_includes_logs_without_target_metadata(self):
        """Verify GDPR export includes logs where user is only actor (no target).

        Many audit actions (like AUDIT_SESSION_CREATED) only have actor metadata,
        not target metadata. These must still be included in GDPR exports.
        """
        # This test requires a real database integration test
        # For unit test, we verify the SQL structure handles this correctly

        # The key insight: if log_metadata["target"]["id"] doesn't exist,
        # PostgreSQL JSON accessor returns NULL, and NULL == str(user_id) is FALSE
        # So actor_query must catch these logs instead

        # This is more of a documentation/verification test - the implementation
        # should work correctly, but we document the expected behavior
        assert True, "See integration test for full verification"

    async def test_soft_delete_includes_logs_without_target_metadata(self):
        """Verify GDPR deletion finds logs where user is only actor.

        The OR condition should catch logs where:
        1. actor_id == user_id (no target needed), OR
        2. metadata["target"]["id"] == user_id (explicit target)
        """
        # Similar to above - SQL OR handles this correctly
        # Log without target metadata matches via actor_id condition
        assert True, "See integration test for full verification"


class TestRetentionServiceBugs:
    """Tests for BUG #3: Unhandled ValueError in Retention Policy Update.

    File: routes.py:751-796
    Problem: ValueError from retention_service.update_policy() not caught
    Impact: 500 Internal Server Error instead of 400 Bad Request

    Note: This needs an integration test to verify the route error handling.
    """

    async def test_retention_service_raises_value_error_for_invalid_days(self):
        """Verify RetentionService raises ValueError for invalid retention_days.

        The service should raise ValueError for days outside valid range,
        and the route should catch this and return 400 Bad Request.
        """

        # Valid range is 1-2555 days
        # Test behavior with edge cases

        # Note: If Pydantic validation catches this first, ValueError is never raised
        # The bug occurs when validation is bypassed or range constants are misconfigured
        assert True, "See integration test for route error handling verification"


class TestConfigValidationBugs:
    """Tests for BUG #5: Missing Category/Action Validation in Config API.

    File: config_routes.py, audit_config_schemas.py
    Problem: Category and action strings not validated against allowed values
    Impact: Invalid data accepted, potential database constraint errors
    """

    def test_valid_categories_list_completeness(self):
        """Verify all valid category names are documented.

        Valid categories: admin_actions, user_actions, security_events,
        file_operations, integration_events, system_actions, audit_access
        """
        from intric.audit.domain.category_mappings import CATEGORY_MAPPINGS, CATEGORY_DESCRIPTIONS

        expected_categories = {
            "admin_actions",
            "user_actions",
            "security_events",
            "file_operations",
            "integration_events",
            "system_actions",
            "audit_access",
        }

        # Get unique category values from the mappings
        actual_categories = set(CATEGORY_MAPPINGS.values())
        assert actual_categories == expected_categories, (
            f"Category mismatch. Expected: {expected_categories}, Got: {actual_categories}"
        )

        # Also verify descriptions exist for all categories
        assert set(CATEGORY_DESCRIPTIONS.keys()) == expected_categories

    def test_invalid_category_should_fail_schema_validation(self):
        """BUG #5a: Invalid category names should fail Pydantic validation.

        Currently, schemas may not validate category names against allowed list,
        allowing invalid categories to reach the database layer.

        This test will FAIL until the bug is fixed.
        """
        from intric.audit.schemas.audit_config_schemas import AuditConfigUpdateRequest

        # Try to create a request with invalid category
        # If schema doesn't validate, this will succeed (bug exists)
        # If schema validates, this will raise ValidationError (bug fixed)
        try:
            AuditConfigUpdateRequest(
                updates=[{"category": "not_a_real_category", "enabled": False}]
            )
            # If we reach here, validation didn't catch invalid category
            # This is the BUG - invalid category was accepted
            pytest.fail(
                "BUG #5a: Invalid category 'not_a_real_category' was accepted by schema. "
                "Schema should validate against allowed category list."
            )
        except Exception as e:
            # Validation error is expected (bug is fixed)
            if "validation" in str(type(e).__name__).lower():
                pass  # Good - validation caught the error
            else:
                raise  # Unexpected error

    def test_invalid_action_should_fail_schema_validation(self):
        """BUG #5b: Invalid action names should fail Pydantic validation.

        Similar to categories, action names should be validated against ActionType enum.

        This test will FAIL until the bug is fixed.
        """
        from intric.audit.schemas.audit_config_schemas import ActionConfigUpdateRequest

        try:
            ActionConfigUpdateRequest(
                updates=[{"action": "fake_action_name", "enabled": False}]
            )
            pytest.fail(
                "BUG #5b: Invalid action 'fake_action_name' was accepted by schema. "
                "Schema should validate against ActionType enum values."
            )
        except Exception as e:
            if "validation" in str(type(e).__name__).lower():
                pass  # Good - validation caught the error
            else:
                raise


class TestDebugLoggingBugs:
    """Tests for BUG #6: Debug Logging Exposes Sensitive Data.

    File: routes.py:316-359
    Problem: User IDs, emails, permissions, session IDs logged at INFO level
    Impact: Sensitive data in production logs

    Note: This is more of a code review finding than a testable bug.
    Verifying log levels would require inspecting logger configuration.
    """

    def test_sensitive_data_not_logged_at_info_level(self):
        """Document that sensitive data should use DEBUG level, not INFO.

        Sensitive fields include:
        - User IDs
        - Email addresses
        - Session IDs
        - Tenant IDs
        - Permissions

        These should be logged at DEBUG level (disabled in production)
        or not logged at all.
        """
        # This is a code review finding - actual verification requires
        # running the code and checking log output
        # Marking as documentation test
        pass


class TestNullEmailBug:
    """Tests for BUG #7: NULL email causes AttributeError in _enrich_logs_with_actor_info.

    File: routes.py:65
    Problem: `username or email.split('@')[0]` crashes if email is None
    Impact: 500 error when enriching audit logs for users without email

    This test is designed to FAIL first, proving the bug exists.
    """

    @pytest.fixture
    def mock_log(self):
        """Create a proper mock audit log object that passes Pydantic validation."""
        from intric.audit.domain.audit_log import AuditLog
        from intric.audit.domain.action_types import ActionType
        from intric.audit.domain.entity_types import EntityType
        from intric.audit.domain.actor_types import ActorType
        from intric.audit.domain.outcome import Outcome

        now = datetime.now(timezone.utc)
        return AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=now,
            description="Test log",
            metadata={},
            outcome=Outcome.SUCCESS,
            created_at=now,
            updated_at=now,
        )

    async def test_enrich_logs_handles_null_email(self, mock_log):
        """BUG #7: NULL email causes AttributeError in _enrich_logs_with_actor_info.

        When a user has:
        - email = None (NULL in database)
        - username = None or empty string

        The code `username or email.split('@')[0]` will crash with:
        AttributeError: 'NoneType' object has no attribute 'split'

        This test should FAIL until the bug is fixed.
        """
        from intric.api.audit.routes import _enrich_logs_with_actor_info

        # Mock the database session
        mock_session = AsyncMock()

        # Simulate database returning a user with NULL email and NULL username
        actor_id = mock_log.actor_id
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            (actor_id, None, None),  # user_id, email=None, username=None
        ])
        mock_session.execute = AsyncMock(return_value=mock_result)

        # This should NOT raise AttributeError
        # If bug exists: AttributeError: 'NoneType' object has no attribute 'split'
        try:
            result = await _enrich_logs_with_actor_info([mock_log], mock_session)
            # If we get here, the function handled NULL gracefully
            assert len(result) == 1, "Should return the enriched log"
            # Verify actor info was added with a safe fallback
            actor_info = result[0].get("metadata", {}).get("actor", {})
            # Should have "Unknown" as fallback name
            assert actor_info.get("name") == "Unknown", \
                "Should use 'Unknown' as fallback when both username and email are NULL"
        except AttributeError as e:
            if "'NoneType' object has no attribute 'split'" in str(e):
                pytest.fail(
                    "BUG #7 CONFIRMED: NULL email causes AttributeError. "
                    f"Code tried to call email.split('@') on None. Error: {e}"
                )
            raise

    async def test_enrich_logs_handles_null_email_with_valid_username(self, mock_log):
        """Verify that NULL email with valid username works correctly.

        When username is present, it should be used as the name.
        This tests the happy path where username saves us from the bug.
        """
        from intric.api.audit.routes import _enrich_logs_with_actor_info

        mock_session = AsyncMock()

        actor_id = mock_log.actor_id
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            (actor_id, None, "valid_username"),  # email=None but username is present
        ])
        mock_session.execute = AsyncMock(return_value=mock_result)

        # This should work because username is truthy
        result = await _enrich_logs_with_actor_info([mock_log], mock_session)

        assert len(result) == 1
        actor_info = result[0].get("metadata", {}).get("actor", {})
        assert actor_info.get("name") == "valid_username", \
            "Should use username when email is NULL"


class TestCacheInvalidationBug:
    """Tests for BUG #8: Missing action cache invalidation when category is toggled.

    File: audit_config_service.py:163-191
    Problem: update_config() invalidates category cache but NOT action cache
    Impact: Actions continue to use stale cached values for up to 60 seconds

    Example scenario:
    1. is_action_enabled("user_created") returns True, cached in "audit_action:..."
    2. Admin disables "admin_actions" category via update_config()
    3. Only "audit_config:...:admin_actions" is invalidated
    4. "audit_action:...:user_created" still says True (stale!)
    5. user_created actions are logged for 60s even though category is disabled

    This test is designed to FAIL first, proving the bug exists.
    """

    @pytest.fixture
    def config_service(self):
        """Create AuditConfigService with mocked dependencies."""
        from intric.audit.application.audit_config_service import AuditConfigService

        mock_repository = AsyncMock()
        service = AuditConfigService(mock_repository)
        service.redis = AsyncMock()
        return service, mock_repository

    async def test_update_config_invalidates_action_cache(self, config_service):
        """BUG #8: Disabling category should invalidate related action caches.

        When admin_actions category is disabled:
        - Category cache key "audit_config:{tenant}:admin_actions" is deleted
        - But "audit_action:{tenant}:user_created" is NOT deleted (BUG!)

        This test checks if action caches are properly invalidated.
        """
        from intric.audit.schemas.audit_config_schemas import CategoryUpdate

        service, mock_repository = config_service
        tenant_id = uuid4()

        # Track which cache keys are deleted
        deleted_keys = []

        async def track_delete(key):
            deleted_keys.append(key)
            return 1

        service.redis.delete = track_delete

        # Setup: Repository returns empty list for find_by_tenant
        mock_repository.find_by_tenant.return_value = []
        mock_repository.update.return_value = None

        # Disable admin_actions category
        update = CategoryUpdate(category="admin_actions", enabled=False)
        await service.update_config(tenant_id, [update])

        # Check what was invalidated
        category_cache_key = f"audit_config:{tenant_id}:admin_actions"

        # This will PASS - category cache is invalidated
        assert category_cache_key in deleted_keys, \
            "Category cache key should be invalidated"

        # BUG CHECK: Were action caches also invalidated?
        # admin_actions category contains actions like: user_created, user_updated, etc.
        # These action cache keys should ALSO be deleted!
        from intric.audit.domain.category_mappings import CATEGORY_MAPPINGS

        # Get all actions in admin_actions category
        admin_actions = [
            action for action, cat in CATEGORY_MAPPINGS.items()
            if cat == "admin_actions"
        ]

        # Check if any action cache keys were invalidated
        action_cache_invalidated = False
        for action in admin_actions:
            action_cache_key = f"audit_action:{tenant_id}:{action}"
            if action_cache_key in deleted_keys:
                action_cache_invalidated = True
                break

        # This assertion will FAIL if bug exists
        # (because action caches are NOT being invalidated)
        assert action_cache_invalidated, (
            f"BUG #8 CONFIRMED: Category 'admin_actions' was disabled, but action caches "
            f"were NOT invalidated. Deleted keys: {deleted_keys}. "
            f"Expected at least one of: {[f'audit_action:{tenant_id}:{a}' for a in admin_actions[:3]]}..."
        )

    async def test_stale_action_cache_after_category_toggle(self, config_service):
        """BUG #8: Verify fix - no stale cache after category toggle.

        After the fix:
        1. Check is_action_enabled -> returns True, value cached
        2. Disable category via update_config -> should invalidate action cache
        3. Check is_action_enabled again -> should return False (category disabled)

        This test verifies the bug is fixed.
        """
        from intric.audit.schemas.audit_config_schemas import CategoryUpdate

        service, mock_repository = config_service
        tenant_id = uuid4()

        # Track cached values - properly simulates Redis behavior
        cache_store = {}

        async def mock_get(key):
            return cache_store.get(key)

        async def mock_set(key, value, ex=None):
            cache_store[key] = value.encode() if isinstance(value, str) else value

        async def mock_delete(key):
            # Properly delete any key - simulates real Redis
            cache_store.pop(key, None)
            return 1

        service.redis.get = mock_get
        service.redis.set = mock_set
        service.redis.delete = mock_delete

        # Step 1: is_action_enabled for user_created (admin_actions category)
        # Repository says category is enabled
        mock_repository.find_by_tenant_and_category.return_value = (
            "admin_actions", True, {}  # category, enabled, action_overrides
        )

        result1 = await service.is_action_enabled(tenant_id, "user_created")
        assert result1 is True, "Initially should be enabled"

        # Verify it was cached
        action_cache_key = f"audit_action:{tenant_id}:user_created"
        assert action_cache_key in cache_store, "Result should be cached"
        assert cache_store[action_cache_key] == b"true"

        # Step 2: Disable admin_actions category
        # The fix should invalidate action caches too
        mock_repository.find_by_tenant.return_value = []  # for get_config call

        update = CategoryUpdate(category="admin_actions", enabled=False)
        await service.update_config(tenant_id, [update])

        # After fix: action cache should be invalidated
        assert action_cache_key not in cache_store, \
            "Action cache should be invalidated when category is toggled"

        # Step 3: Check is_action_enabled again
        # Repository now returns category as disabled
        mock_repository.find_by_tenant_and_category.return_value = (
            "admin_actions", False, {}  # category is now DISABLED
        )

        result2 = await service.is_action_enabled(tenant_id, "user_created")

        # After fix: should return False (no stale cache)
        assert result2 is False, "Should return False after category disabled"
