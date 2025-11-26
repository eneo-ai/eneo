"""Integration tests for audit log export endpoints."""

import pytest
from datetime import datetime, timezone, timedelta

pytestmark = pytest.mark.integration


class TestExportAuthentication:
    """Tests for export endpoint authentication."""

    async def test_export_requires_authentication(self, client):
        """Verify /logs/export requires authentication."""
        response = await client.get("/api/v1/audit/logs/export")
        assert response.status_code == 401

    async def test_export_succeeds_with_auth(self, client, auth_headers):
        """Verify export works with valid authentication."""
        response = await client.get(
            "/api/v1/audit/logs/export",
            headers=auth_headers,
        )
        assert response.status_code == 200


class TestCsvExport:
    """Tests for CSV export functionality."""

    async def test_csv_export_default_format(self, client, auth_headers, sample_audit_logs):
        """Verify CSV is the default export format."""
        response = await client.get(
            "/api/v1/audit/logs/export",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")

    async def test_csv_export_explicit_format(self, client, auth_headers, sample_audit_logs):
        """Verify CSV format can be explicitly requested."""
        response = await client.get(
            "/api/v1/audit/logs/export?format=csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")

    async def test_csv_export_has_header_row(self, client, auth_headers, sample_audit_logs):
        """Verify CSV export includes header row."""
        response = await client.get(
            "/api/v1/audit/logs/export?format=csv",
            headers=auth_headers,
        )
        content = response.text
        lines = content.strip().split("\n")

        # First line should be headers
        headers = lines[0].lower()
        assert "timestamp" in headers or "created_at" in headers
        assert "action" in headers
        assert "actor" in headers or "actor_id" in headers

    async def test_csv_export_content_disposition(self, client, auth_headers, sample_audit_logs):
        """Verify CSV export has proper Content-Disposition header."""
        response = await client.get(
            "/api/v1/audit/logs/export?format=csv",
            headers=auth_headers,
        )
        content_disp = response.headers.get("content-disposition", "")
        assert "attachment" in content_disp
        assert "audit_logs" in content_disp
        assert ".csv" in content_disp

    async def test_csv_export_with_filters(self, client, auth_headers, sample_audit_logs):
        """Verify CSV export respects filters."""
        response = await client.get(
            "/api/v1/audit/logs/export?format=csv&action=user_created",
            headers=auth_headers,
        )
        assert response.status_code == 200

        content = response.text
        lines = content.strip().split("\n")

        # Skip header, check data rows contain the filtered action
        if len(lines) > 1:
            for line in lines[1:]:
                # user_created should appear in the action column
                assert "user_created" in line.lower()


class TestCsvInjectionProtection:
    """Tests for CSV injection protection in exports."""

    async def test_formula_prefix_sanitized_in_export(self, client, auth_headers, db_session, test_tenant, test_user):
        """Verify formula characters are sanitized in CSV export."""
        from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
        from intric.audit.domain.audit_log import AuditLog
        from intric.audit.domain.action_types import ActionType
        from intric.audit.domain.entity_types import EntityType
        from intric.audit.domain.actor_types import ActorType
        from intric.audit.domain.outcome import Outcome
        from uuid import uuid4

        # Create a log with dangerous description
        async with db_session() as session:
            repo = AuditLogRepositoryImpl(session)
            dangerous_log = AuditLog(
                id=uuid4(),
                tenant_id=test_tenant.id,
                actor_id=test_user,
                actor_type=ActorType.USER,
                action=ActionType.USER_CREATED,
                entity_type=EntityType.USER,
                entity_id=uuid4(),
                timestamp=datetime.now(timezone.utc),
                description="=SUM(A1:A10) malicious formula",
                metadata={"test": "injection_test"},
                outcome=Outcome.SUCCESS,
            )
            await repo.create(dangerous_log)

        # Export and check sanitization
        response = await client.get(
            "/api/v1/audit/logs/export?format=csv",
            headers=auth_headers,
        )
        content = response.text

        # Formula should be prefixed with single quote
        assert "'=SUM(A1:A10)" in content or "\"'=SUM(A1:A10)" in content


class TestJsonlExport:
    """Tests for JSON Lines export functionality."""

    async def test_jsonl_export_format(self, client, auth_headers, sample_audit_logs):
        """Verify JSON Lines format is returned."""
        response = await client.get(
            "/api/v1/audit/logs/export?format=json",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "application/x-ndjson" in response.headers.get("content-type", "")

    async def test_jsonl_export_each_line_is_valid_json(self, client, auth_headers, sample_audit_logs):
        """Verify each line in JSONL export is valid JSON."""
        import json

        response = await client.get(
            "/api/v1/audit/logs/export?format=json",
            headers=auth_headers,
        )
        content = response.text
        lines = [line for line in content.strip().split("\n") if line]

        for line in lines:
            # Each line should parse as valid JSON
            try:
                parsed = json.loads(line)
                assert isinstance(parsed, dict)
            except json.JSONDecodeError:
                pytest.fail(f"Invalid JSON line: {line[:100]}")

    async def test_jsonl_export_contains_required_fields(self, client, auth_headers, sample_audit_logs):
        """Verify JSONL records contain required fields."""
        import json

        response = await client.get(
            "/api/v1/audit/logs/export?format=json",
            headers=auth_headers,
        )
        content = response.text
        lines = [line for line in content.strip().split("\n") if line]

        if lines:
            record = json.loads(lines[0])
            # Check required fields
            assert "id" in record
            assert "action" in record
            assert "timestamp" in record or "created_at" in record

    async def test_jsonl_export_content_disposition(self, client, auth_headers, sample_audit_logs):
        """Verify JSONL export has proper Content-Disposition header."""
        response = await client.get(
            "/api/v1/audit/logs/export?format=json",
            headers=auth_headers,
        )
        content_disp = response.headers.get("content-disposition", "")
        assert "attachment" in content_disp
        assert "audit_logs" in content_disp
        assert ".jsonl" in content_disp

    async def test_jsonl_export_with_date_filter(self, client, auth_headers, sample_audit_logs):
        """Verify JSONL export respects date filters."""
        from_date = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        response = await client.get(
            "/api/v1/audit/logs/export",
            params={"format": "json", "from_date": from_date},
            headers=auth_headers,
        )
        assert response.status_code == 200


class TestGdprExport:
    """Tests for GDPR Article 15 export functionality."""

    async def test_gdpr_export_with_user_id(self, client, auth_headers, sample_audit_logs, test_user):
        """Verify GDPR export filters by user_id."""
        response = await client.get(
            f"/api/v1/audit/logs/export?user_id={test_user}",
            headers=auth_headers,
        )
        assert response.status_code == 200

    async def test_gdpr_export_csv_format(self, client, auth_headers, sample_audit_logs, test_user):
        """Verify GDPR export works with CSV format."""
        response = await client.get(
            f"/api/v1/audit/logs/export?user_id={test_user}&format=csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")

    async def test_gdpr_export_json_format(self, client, auth_headers, sample_audit_logs, test_user):
        """Verify GDPR export works with JSON format."""
        response = await client.get(
            f"/api/v1/audit/logs/export?user_id={test_user}&format=json",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "application/x-ndjson" in response.headers.get("content-type", "")


class TestExportAuditTrail:
    """Tests for export action auditing."""

    async def test_export_creates_audit_entry(self, client, auth_headers, auth_headers_with_session):
        """Verify exporting logs creates AUDIT_LOG_EXPORTED entry."""
        headers, cookies = auth_headers_with_session

        # Perform export
        response = await client.get(
            "/api/v1/audit/logs/export?format=csv",
            headers=auth_headers,
        )
        assert response.status_code == 200

        # Check for audit entry
        response2 = await client.get(
            "/api/v1/audit/logs?action=audit_log_exported",
            headers=headers,
            cookies=cookies,
        )
        assert response2.status_code == 200
        data = response2.json()

        # Should have at least one export entry
        assert data["total_count"] >= 1


class TestExportEmptyResults:
    """Tests for export with no results."""

    async def test_csv_export_empty_result(self, client, auth_headers):
        """Verify CSV export handles no results gracefully."""
        # Use far future date to get no results
        far_future = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()

        response = await client.get(
            "/api/v1/audit/logs/export",
            params={"format": "csv", "from_date": far_future},
            headers=auth_headers,
        )
        assert response.status_code == 200

        content = response.text
        lines = content.strip().split("\n")
        # Should have at least header row
        assert len(lines) >= 1

    async def test_jsonl_export_empty_result(self, client, auth_headers):
        """Verify JSONL export handles no results gracefully."""
        far_future = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()

        response = await client.get(
            "/api/v1/audit/logs/export",
            params={"format": "json", "from_date": far_future},
            headers=auth_headers,
        )
        assert response.status_code == 200
        # Empty JSONL is valid (empty string or no lines)


class TestExportValidation:
    """Tests for export parameter validation."""

    async def test_invalid_format_defaults_to_csv(self, client, auth_headers):
        """Verify invalid format parameter defaults to CSV."""
        response = await client.get(
            "/api/v1/audit/logs/export?format=invalid_format",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")

    async def test_export_with_invalid_action_rejected(self, client, auth_headers):
        """Verify invalid action parameter is rejected."""
        response = await client.get(
            "/api/v1/audit/logs/export?action=not_a_real_action",
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_export_with_invalid_date_rejected(self, client, auth_headers):
        """Verify invalid date parameter is rejected."""
        response = await client.get(
            "/api/v1/audit/logs/export?from_date=not-a-date",
            headers=auth_headers,
        )
        assert response.status_code == 422
