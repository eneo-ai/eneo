"""
Integration tests for production bugs found through code review.
These tests verify API-level behavior and error handling.
"""

from datetime import datetime, timezone, timedelta
from uuid import uuid4


class TestRetentionPolicyValidation:
    """Tests for BUG #3: Unhandled ValueError in Retention Policy Update.

    VERDICT: NOT A BUG - Pydantic schema validates retention_days with ge=1, le=2555.
    Invalid values return 422 (validation error), not 500.

    These tests verify the expected behavior is correct.
    """

    async def test_retention_update_rejects_zero_days(self, client, auth_headers):
        """Verify retention_days=0 is rejected with 422, not 500."""
        response = await client.put(
            "/api/v1/audit/retention-policy",
            json={"retention_days": 0},
            headers=auth_headers,
        )
        # Should be 422 (Pydantic validation), NOT 500 (unhandled ValueError)
        assert response.status_code == 422, (
            f"Expected 422 for invalid retention_days=0, got {response.status_code}"
        )

    async def test_retention_update_rejects_negative_days(self, client, auth_headers):
        """Verify negative retention_days is rejected with 422."""
        response = await client.put(
            "/api/v1/audit/retention-policy",
            json={"retention_days": -10},
            headers=auth_headers,
        )
        assert response.status_code == 422, (
            f"Expected 422 for negative retention_days, got {response.status_code}"
        )

    async def test_retention_update_rejects_over_maximum(self, client, auth_headers):
        """Verify retention_days > 2555 is rejected with 422."""
        response = await client.put(
            "/api/v1/audit/retention-policy",
            json={"retention_days": 3000},
            headers=auth_headers,
        )
        assert response.status_code == 422, (
            f"Expected 422 for retention_days > 2555, got {response.status_code}"
        )

    async def test_retention_update_accepts_minimum(self, client, auth_headers):
        """Verify retention_days=1 (minimum) is accepted."""
        response = await client.put(
            "/api/v1/audit/retention-policy",
            json={"retention_days": 1},
            headers=auth_headers,
        )
        # Should succeed or require admin permission (403)
        assert response.status_code in (200, 403), (
            f"Expected 200 or 403 for valid retention_days=1, got {response.status_code}"
        )

    async def test_retention_update_accepts_maximum(self, client, auth_headers):
        """Verify retention_days=2555 (maximum) is accepted."""
        response = await client.put(
            "/api/v1/audit/retention-policy",
            json={"retention_days": 2555},
            headers=auth_headers,
        )
        assert response.status_code in (200, 403), (
            f"Expected 200 or 403 for valid retention_days=2555, got {response.status_code}"
        )


class TestConfigApiValidation:
    """Tests for BUG #5: Missing Category/Action Validation in Config API.

    These tests verify that invalid categories and actions are rejected at the API level.
    """

    async def test_config_update_rejects_invalid_category(self, client, auth_headers):
        """BUG #5a: Verify invalid category is rejected by API.

        The API should return 422 for invalid category names.
        If it returns 200, the bug exists (invalid data reaches database).
        """
        response = await client.patch(
            "/api/v1/audit/config",
            json={"updates": [{"category": "fake_category_name", "enabled": False}]},
            headers=auth_headers,
        )
        # Should be 422 (validation error)
        # If this is 200 or another success code, BUG #5 exists at API level
        assert response.status_code == 422, (
            f"BUG #5a: Invalid category 'fake_category_name' was accepted. "
            f"Expected 422, got {response.status_code}. "
            f"Response: {response.json() if response.status_code != 500 else 'Server Error'}"
        )

    async def test_config_update_rejects_invalid_action(self, client, auth_headers):
        """BUG #5b: Verify invalid action is rejected by API.

        The API should return 422 for invalid action names.
        """
        response = await client.patch(
            "/api/v1/audit/config/actions",
            json={"updates": [{"action": "fake_action_name", "enabled": False}]},
            headers=auth_headers,
        )
        assert response.status_code == 422, (
            f"BUG #5b: Invalid action 'fake_action_name' was accepted. "
            f"Expected 422, got {response.status_code}. "
            f"Response: {response.json() if response.status_code != 500 else 'Server Error'}"
        )

    async def test_config_update_accepts_valid_category(self, client, auth_headers):
        """Verify valid category is accepted."""
        response = await client.patch(
            "/api/v1/audit/config",
            json={"updates": [{"category": "admin_actions", "enabled": True}]},
            headers=auth_headers,
        )
        # Should succeed or require admin permission (403)
        assert response.status_code in (200, 403), (
            f"Expected 200 or 403 for valid category, got {response.status_code}"
        )

    async def test_config_update_accepts_valid_action(self, client, auth_headers):
        """Verify valid action is accepted."""
        response = await client.patch(
            "/api/v1/audit/config/actions",
            json={"updates": [{"action": "user_created", "enabled": True}]},
            headers=auth_headers,
        )
        assert response.status_code in (200, 403), (
            f"Expected 200 or 403 for valid action, got {response.status_code}"
        )


class TestGdprExportWithMixedMetadata:
    """Tests for BUG #1: GDPR Export with logs missing metadata["target"]["id"].

    These tests verify that GDPR exports work correctly when logs have
    different metadata structures (some with target, some without).
    """

    async def test_gdpr_export_succeeds_with_mixed_log_types(
        self, client, auth_headers, db_session, test_tenant, test_user
    ):
        """Verify GDPR export handles logs with and without target metadata."""
        from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
        from intric.audit.domain.audit_log import AuditLog
        from intric.audit.domain.action_types import ActionType
        from intric.audit.domain.entity_types import EntityType
        from intric.audit.domain.actor_types import ActorType
        from intric.audit.domain.outcome import Outcome

        # Create logs with different metadata structures
        async with db_session() as session:
            repo = AuditLogRepositoryImpl(session)

            # Log 1: Has actor only (no target) - like AUDIT_SESSION_CREATED
            log_actor_only = AuditLog(
                id=uuid4(),
                tenant_id=test_tenant.id,
                actor_id=test_user,
                actor_type=ActorType.USER,
                action=ActionType.AUDIT_SESSION_CREATED,
                entity_type=EntityType.AUDIT_LOG,
                entity_id=uuid4(),
                timestamp=datetime.now(timezone.utc),
                description="Created audit session",
                metadata={
                    "session_id": str(uuid4()),
                    "justification": {"category": "test", "description": "Testing"},
                    # NO "target" key!
                },
                outcome=Outcome.SUCCESS,
            )
            await repo.create(log_actor_only)

            # Log 2: Has both actor and target
            target_user_id = uuid4()
            log_with_target = AuditLog(
                id=uuid4(),
                tenant_id=test_tenant.id,
                actor_id=test_user,
                actor_type=ActorType.USER,
                action=ActionType.USER_UPDATED,
                entity_type=EntityType.USER,
                entity_id=target_user_id,
                timestamp=datetime.now(timezone.utc),
                description="Updated user settings",
                metadata={
                    "actor": {"id": str(test_user), "name": "Test Actor"},
                    "target": {"id": str(target_user_id), "name": "Target User"},
                },
                outcome=Outcome.SUCCESS,
            )
            await repo.create(log_with_target)

        # Request GDPR export for the test user
        response = await client.get(
            f"/api/v1/audit/logs/user/{test_user}",
            headers=auth_headers,
        )

        # Should succeed without 500 error
        assert response.status_code == 200, (
            f"GDPR export failed with status {response.status_code}. "
            f"This might indicate BUG #1 - query fails on logs without target metadata."
        )

        # Verify we got the logs
        data = response.json()
        assert "logs" in data
        # Should include at least the actor-only log (where test_user is actor)
        assert data["total_count"] >= 1


class TestSessionValidationApi:
    """Integration tests for session validation edge cases."""

    async def test_logs_endpoint_handles_invalid_session_gracefully(
        self, client, auth_headers
    ):
        """Verify /logs endpoint returns proper error for invalid session.

        This tests the full flow: if session JSON is corrupted in Redis,
        the API should return 401 (session invalid), not 500 (server error).
        """
        # Set an invalid session cookie
        response = await client.get(
            "/api/v1/audit/logs",
            headers=auth_headers,
            cookies={"audit_session_id": "not-a-valid-session-uuid"},
        )

        # Should be 401 (authentication failure), not 500
        # The session validation should gracefully handle invalid sessions
        assert response.status_code in (401, 403), (
            f"Expected 401/403 for invalid session, got {response.status_code}"
        )

    async def test_logs_endpoint_handles_missing_session(self, client, auth_headers):
        """Verify /logs endpoint returns 401 when session cookie is missing."""
        response = await client.get(
            "/api/v1/audit/logs",
            headers=auth_headers,
            # No session cookie
        )

        # Should require audit session
        assert response.status_code == 401
        assert "AUDIT_SESSION_REQUIRED" in response.headers.get("X-Error-Code", "")


class TestCsvExportMemoryLimit:
    """Tests for BUG #2: CSV Export Memory Accumulation.

    The CSV export route handler should:
    1. Have a default max_records limit (50,000) to prevent memory issues
    2. Accept max_records query parameter to override
    3. Return X-Records-Truncated header if records were truncated
    4. Return X-Total-Records header with actual count
    """

    async def test_csv_export_respects_max_records_limit(self, client, auth_headers, db_session, test_tenant, test_user):
        """Verify CSV export respects max_records limit and returns truncation headers.

        Expected behavior:
        - Export returns at most max_records records
        - Response includes X-Records-Truncated: true when limit is hit
        - Response includes X-Total-Records header with actual count
        """
        from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
        from intric.audit.domain.audit_log import AuditLog
        from intric.audit.domain.action_types import ActionType
        from intric.audit.domain.entity_types import EntityType
        from intric.audit.domain.actor_types import ActorType
        from intric.audit.domain.outcome import Outcome

        # Create more logs than the test limit
        test_limit = 50  # Use explicit limit for testing (default is 50,000)
        logs_to_create = test_limit + 10

        async with db_session() as session:
            repo = AuditLogRepositoryImpl(session)

            for i in range(logs_to_create):
                log = AuditLog(
                    id=uuid4(),
                    tenant_id=test_tenant.id,
                    actor_id=test_user,
                    actor_type=ActorType.USER,
                    action=ActionType.USER_CREATED,
                    entity_type=EntityType.USER,
                    entity_id=uuid4(),
                    timestamp=datetime.now(timezone.utc) - timedelta(minutes=i),
                    description=f"Test log {i} for memory limit test",
                    metadata={"test_index": i},
                    outcome=Outcome.SUCCESS,
                )
                await repo.create(log)

        # Export with explicit max_records limit to test truncation
        response = await client.get(
            "/api/v1/audit/logs/export",
            params={"format": "csv", "max_records": str(test_limit)},
            headers=auth_headers,
        )
        assert response.status_code == 200

        # Parse CSV to count records
        content = response.text
        lines = content.strip().split("\n")
        data_lines = len(lines) - 1  # Exclude header row

        # Verify truncation headers
        truncation_header = response.headers.get("X-Records-Truncated", "false")
        total_records_header = response.headers.get("X-Total-Records")

        # Export should be truncated to test_limit
        assert data_lines <= test_limit, (
            f"Export returned {data_lines} records, expected <= {test_limit}. "
            f"max_records parameter not respected."
        )

        # Truncation header should be true since we created more logs than limit
        assert truncation_header.lower() == "true", (
            f"Expected 'X-Records-Truncated: true' header when exceeding limit. "
            f"Got: {truncation_header}"
        )

        # Total records header should indicate actual count
        assert total_records_header is not None, (
            "Missing X-Total-Records header. "
            "This header should indicate total matching records (before truncation)."
        )
        assert int(total_records_header) >= logs_to_create, (
            f"X-Total-Records={total_records_header} should be >= {logs_to_create}"
        )

    async def test_csv_export_accepts_max_records_parameter(self, client, auth_headers):
        """Verify export endpoint accepts max_records query parameter.

        Expected behavior:
        - max_records query param is accepted
        - Response respects the limit
        - Response includes truncation headers
        """
        # This test verifies the max_records parameter is supported
        response = await client.get(
            "/api/v1/audit/logs/export",
            params={"format": "csv", "max_records": "10"},
            headers=auth_headers,
        )

        # Should accept max_records parameter
        assert response.status_code == 200, (
            f"Expected 200 for max_records param, got {response.status_code}"
        )

        # Count actual rows returned
        lines = response.text.strip().split("\n")
        data_lines = len(lines) - 1  # Exclude header

        # Should respect max_records=10
        assert data_lines <= 10, (
            f"max_records=10 was ignored, got {data_lines} records. "
            f"The route handler doesn't pass max_records to export_csv()."
        )

        # Verify truncation headers are present
        assert "X-Total-Records" in response.headers, (
            "Missing X-Total-Records header in export response"
        )
        assert "X-Records-Truncated" in response.headers, (
            "Missing X-Records-Truncated header in export response"
        )

    async def test_csv_export_default_limit_prevents_unbounded_export(self, client, auth_headers):
        """Verify export has a default max_records limit (50,000).

        The default limit prevents memory exhaustion with large exports.
        """
        response = await client.get(
            "/api/v1/audit/logs/export",
            params={"format": "csv"},
            headers=auth_headers,
        )
        assert response.status_code == 200

        # Verify max records limit header is present and shows default
        max_limit_header = response.headers.get("X-Max-Records-Limit")
        assert max_limit_header is not None, (
            "Missing X-Max-Records-Limit header. "
            "Export should indicate the applied limit."
        )
        assert int(max_limit_header) == 50000, (
            f"Expected default limit of 50000, got {max_limit_header}"
        )
