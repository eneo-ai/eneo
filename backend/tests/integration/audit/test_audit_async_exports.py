"""Integration tests for async audit log export endpoints."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest


pytestmark = pytest.mark.integration


class TestAsyncExportAuthentication:
    """Tests for async export endpoint authentication."""

    async def test_request_async_export_requires_authentication(self, client):
        """Verify POST /logs/export/async requires authentication."""
        response = await client.post(
            "/api/v1/audit/logs/export/async",
            json={"format": "csv"},
        )
        assert response.status_code == 401

    async def test_export_status_requires_authentication(self, client):
        """Verify GET /logs/export/{job_id}/status requires authentication."""
        job_id = str(uuid4())
        response = await client.get(f"/api/v1/audit/logs/export/{job_id}/status")
        assert response.status_code == 401

    async def test_export_download_requires_authentication(self, client):
        """Verify GET /logs/export/{job_id}/download requires authentication."""
        job_id = str(uuid4())
        response = await client.get(f"/api/v1/audit/logs/export/{job_id}/download")
        assert response.status_code == 401

    async def test_export_cancel_requires_authentication(self, client):
        """Verify POST /logs/export/{job_id}/cancel requires authentication."""
        job_id = str(uuid4())
        response = await client.post(f"/api/v1/audit/logs/export/{job_id}/cancel")
        assert response.status_code == 401


class TestAsyncExportJobCreation:
    """Tests for async export job creation."""

    async def test_request_export_returns_job_id(self, client, auth_headers, sample_audit_logs, redis_client):
        """Verify async export request returns job_id immediately."""
        response = await client.post(
            "/api/v1/audit/logs/export/async",
            json={"format": "csv"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "job_id" in data
        assert data["status"] == "pending"
        assert "message" in data

        # Clean up Redis
        # Find and delete the job key
        keys = []
        cursor = 0
        while True:
            cursor, batch = await redis_client.scan(cursor, match="audit_export:*", count=100)
            keys.extend(batch)
            if cursor == 0:
                break
        for key in keys:
            await redis_client.delete(key)

    async def test_request_export_with_filters(self, client, auth_headers, sample_audit_logs, redis_client):
        """Verify async export accepts filter parameters."""
        from_date = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        response = await client.post(
            "/api/v1/audit/logs/export/async",
            json={
                "format": "json",
                "from_date": from_date,
                "action": "user_created",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data

        # Clean up
        keys = []
        cursor = 0
        while True:
            cursor, batch = await redis_client.scan(cursor, match="audit_export:*", count=100)
            keys.extend(batch)
            if cursor == 0:
                break
        for key in keys:
            await redis_client.delete(key)

    async def test_request_export_rejects_invalid_format(self, client, auth_headers):
        """Verify invalid format is rejected."""
        response = await client.post(
            "/api/v1/audit/logs/export/async",
            json={"format": "xml"},  # Invalid format
            headers=auth_headers,
        )

        assert response.status_code == 422


class TestAsyncExportJobStatus:
    """Tests for export job status endpoint."""

    async def test_status_returns_404_for_unknown_job(self, client, auth_headers):
        """Verify 404 for non-existent job ID."""
        fake_job_id = str(uuid4())

        response = await client.get(
            f"/api/v1/audit/logs/export/{fake_job_id}/status",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_status_returns_job_details(self, client, auth_headers, redis_client, db_container):
        """Verify status endpoint returns job details."""
        # Create a job directly in Redis
        async with db_container() as container:
            user = container.user()
            tenant_id = user.tenant_id

        job_id = uuid4()
        now = datetime.now(timezone.utc)

        job_data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "processing",
            "progress": 50,
            "total_records": 1000,
            "processed_records": 500,
            "format": "csv",
            "file_path": None,
            "file_size_bytes": None,
            "error_message": None,
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": None,
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }

        key = f"audit_export:{tenant_id}:{job_id}"
        await redis_client.setex(key, 86400, json.dumps(job_data))

        try:
            response = await client.get(
                f"/api/v1/audit/logs/export/{job_id}/status",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()

            assert data["job_id"] == str(job_id)
            assert data["status"] == "processing"
            assert data["progress"] == 50
            assert data["processed_records"] == 500
            assert data["total_records"] == 1000
        finally:
            await redis_client.delete(key)

    async def test_status_returns_download_url_when_complete(self, client, auth_headers, redis_client, db_container):
        """Verify download_url is included when job is complete."""
        async with db_container() as container:
            user = container.user()
            tenant_id = user.tenant_id

        job_id = uuid4()
        now = datetime.now(timezone.utc)

        job_data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "completed",
            "progress": 100,
            "total_records": 1000,
            "processed_records": 1000,
            "format": "csv",
            "file_path": f"/app/exports/{tenant_id}/{job_id}.csv",
            "file_size_bytes": 102400,
            "error_message": None,
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }

        key = f"audit_export:{tenant_id}:{job_id}"
        await redis_client.setex(key, 86400, json.dumps(job_data))

        try:
            response = await client.get(
                f"/api/v1/audit/logs/export/{job_id}/status",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "completed"
            assert data["download_url"] is not None
            assert str(job_id) in data["download_url"]
        finally:
            await redis_client.delete(key)


class TestAsyncExportJobCancellation:
    """Tests for export job cancellation."""

    async def test_cancel_returns_404_for_unknown_job(self, client, auth_headers):
        """Verify 404 for non-existent job ID."""
        fake_job_id = str(uuid4())

        response = await client.post(
            f"/api/v1/audit/logs/export/{fake_job_id}/cancel",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_cancel_processing_job(self, client, auth_headers, redis_client, db_container):
        """Verify cancellation of processing job."""
        async with db_container() as container:
            user = container.user()
            tenant_id = user.tenant_id

        job_id = uuid4()
        now = datetime.now(timezone.utc)

        job_data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "processing",
            "progress": 25,
            "total_records": 10000,
            "processed_records": 2500,
            "format": "csv",
            "file_path": None,
            "file_size_bytes": None,
            "error_message": None,
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": None,
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }

        key = f"audit_export:{tenant_id}:{job_id}"
        await redis_client.setex(key, 86400, json.dumps(job_data))

        try:
            response = await client.post(
                f"/api/v1/audit/logs/export/{job_id}/cancel",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "cancellation_requested"

            # Verify Redis was updated
            updated_data = json.loads(await redis_client.get(key))
            assert updated_data["cancelled"] is True
        finally:
            await redis_client.delete(key)

    async def test_cancel_completed_job_fails(self, client, auth_headers, redis_client, db_container):
        """Verify completed jobs cannot be cancelled."""
        async with db_container() as container:
            user = container.user()
            tenant_id = user.tenant_id

        job_id = uuid4()
        now = datetime.now(timezone.utc)

        job_data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "completed",
            "progress": 100,
            "total_records": 1000,
            "processed_records": 1000,
            "format": "csv",
            "file_path": f"/app/exports/{tenant_id}/{job_id}.csv",
            "file_size_bytes": 102400,
            "error_message": None,
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }

        key = f"audit_export:{tenant_id}:{job_id}"
        await redis_client.setex(key, 86400, json.dumps(job_data))

        try:
            response = await client.post(
                f"/api/v1/audit/logs/export/{job_id}/cancel",
                headers=auth_headers,
            )

            assert response.status_code == 400
            assert "cannot be cancelled" in response.json()["detail"].lower()
        finally:
            await redis_client.delete(key)


class TestAsyncExportDownload:
    """Tests for export file download."""

    async def test_download_returns_404_for_unknown_job(self, client, auth_headers):
        """Verify 404 for non-existent job ID."""
        fake_job_id = str(uuid4())

        response = await client.get(
            f"/api/v1/audit/logs/export/{fake_job_id}/download",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_download_fails_for_incomplete_job(self, client, auth_headers, redis_client, db_container):
        """Verify download fails for non-completed jobs."""
        async with db_container() as container:
            user = container.user()
            tenant_id = user.tenant_id

        job_id = uuid4()
        now = datetime.now(timezone.utc)

        job_data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "processing",
            "progress": 50,
            "total_records": 1000,
            "processed_records": 500,
            "format": "csv",
            "file_path": None,
            "file_size_bytes": None,
            "error_message": None,
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": None,
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }

        key = f"audit_export:{tenant_id}:{job_id}"
        await redis_client.setex(key, 86400, json.dumps(job_data))

        try:
            response = await client.get(
                f"/api/v1/audit/logs/export/{job_id}/download",
                headers=auth_headers,
            )

            assert response.status_code == 400
            assert "not completed" in response.json()["detail"].lower()
        finally:
            await redis_client.delete(key)

    async def test_download_fails_for_missing_file(self, client, auth_headers, redis_client, db_container):
        """Verify download fails when file doesn't exist."""
        async with db_container() as container:
            user = container.user()
            tenant_id = user.tenant_id

        job_id = uuid4()
        now = datetime.now(timezone.utc)

        # Job is complete but file path doesn't exist
        job_data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "completed",
            "progress": 100,
            "total_records": 1000,
            "processed_records": 1000,
            "format": "csv",
            "file_path": f"/nonexistent/path/{job_id}.csv",
            "file_size_bytes": 102400,
            "error_message": None,
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }

        key = f"audit_export:{tenant_id}:{job_id}"
        await redis_client.setex(key, 86400, json.dumps(job_data))

        try:
            response = await client.get(
                f"/api/v1/audit/logs/export/{job_id}/download",
                headers=auth_headers,
            )

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()
        finally:
            await redis_client.delete(key)


class TestAsyncExportConcurrencyLimit:
    """Tests for concurrent export limiting."""

    async def test_concurrent_export_limit_enforcement(
        self, client, auth_headers, redis_client, db_container, sample_audit_logs
    ):
        """Verify concurrent export limit is enforced."""
        async with db_container() as container:
            user = container.user()
            tenant_id = user.tenant_id

        now = datetime.now(timezone.utc)

        # Create 2 active jobs in Redis (max allowed)
        active_job_ids = []
        for i in range(2):
            job_id = uuid4()
            active_job_ids.append(job_id)
            job_data = {
                "job_id": str(job_id),
                "tenant_id": str(tenant_id),
                "status": "processing",
                "progress": 25 * (i + 1),
                "total_records": 10000,
                "processed_records": 2500 * (i + 1),
                "format": "csv",
                "file_path": None,
                "file_size_bytes": None,
                "error_message": None,
                "cancelled": False,
                "created_at": now.isoformat(),
                "started_at": now.isoformat(),
                "completed_at": None,
                "expires_at": (now + timedelta(hours=24)).isoformat(),
            }
            key = f"audit_export:{tenant_id}:{job_id}"
            await redis_client.setex(key, 86400, json.dumps(job_data))

        try:
            # Try to create a 3rd export - should fail
            response = await client.post(
                "/api/v1/audit/logs/export/async",
                json={"format": "csv"},
                headers=auth_headers,
            )

            assert response.status_code == 429
            assert "concurrent" in response.json()["detail"].lower()
        finally:
            # Clean up
            for job_id in active_job_ids:
                await redis_client.delete(f"audit_export:{tenant_id}:{job_id}")


class TestAsyncExportMultiTenantIsolation:
    """Tests for multi-tenant isolation in async exports."""

    async def test_cannot_access_other_tenant_job_status(
        self, client, auth_headers, redis_client, test_user_2
    ):
        """Verify tenant cannot access another tenant's job status."""
        # Create a job for tenant 2
        other_tenant_id = test_user_2.tenant_id
        job_id = uuid4()
        now = datetime.now(timezone.utc)

        job_data = {
            "job_id": str(job_id),
            "tenant_id": other_tenant_id,  # Different tenant
            "status": "processing",
            "progress": 50,
            "total_records": 1000,
            "processed_records": 500,
            "format": "csv",
            "file_path": None,
            "file_size_bytes": None,
            "error_message": None,
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": None,
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }

        key = f"audit_export:{other_tenant_id}:{job_id}"
        await redis_client.setex(key, 86400, json.dumps(job_data))

        try:
            # Try to access with tenant 1's auth
            response = await client.get(
                f"/api/v1/audit/logs/export/{job_id}/status",
                headers=auth_headers,  # Tenant 1's auth
            )

            # Should return 404 (job not found for this tenant)
            assert response.status_code == 404
        finally:
            await redis_client.delete(key)

    async def test_cannot_cancel_other_tenant_job(
        self, client, auth_headers, redis_client, test_user_2
    ):
        """Verify tenant cannot cancel another tenant's job."""
        other_tenant_id = test_user_2.tenant_id
        job_id = uuid4()
        now = datetime.now(timezone.utc)

        job_data = {
            "job_id": str(job_id),
            "tenant_id": other_tenant_id,
            "status": "processing",
            "progress": 25,
            "total_records": 10000,
            "processed_records": 2500,
            "format": "csv",
            "file_path": None,
            "file_size_bytes": None,
            "error_message": None,
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": None,
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }

        key = f"audit_export:{other_tenant_id}:{job_id}"
        await redis_client.setex(key, 86400, json.dumps(job_data))

        try:
            response = await client.post(
                f"/api/v1/audit/logs/export/{job_id}/cancel",
                headers=auth_headers,  # Tenant 1's auth
            )

            # Should return 404
            assert response.status_code == 404
        finally:
            await redis_client.delete(key)


class TestAsyncExportErrorStates:
    """Tests for export error handling."""

    async def test_status_shows_error_for_failed_job(
        self, client, auth_headers, redis_client, db_container
    ):
        """Verify failed job shows error message in status."""
        async with db_container() as container:
            user = container.user()
            tenant_id = user.tenant_id

        job_id = uuid4()
        now = datetime.now(timezone.utc)

        job_data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "failed",
            "progress": 45,
            "total_records": 10000,
            "processed_records": 4500,
            "format": "csv",
            "file_path": None,
            "file_size_bytes": None,
            "error_message": "Database connection lost during export",
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }

        key = f"audit_export:{tenant_id}:{job_id}"
        await redis_client.setex(key, 86400, json.dumps(job_data))

        try:
            response = await client.get(
                f"/api/v1/audit/logs/export/{job_id}/status",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "failed"
            assert data["error_message"] == "Database connection lost during export"
            assert data["download_url"] is None
        finally:
            await redis_client.delete(key)

    async def test_download_fails_for_failed_job(
        self, client, auth_headers, redis_client, db_container
    ):
        """Verify download endpoint rejects failed jobs."""
        async with db_container() as container:
            user = container.user()
            tenant_id = user.tenant_id

        job_id = uuid4()
        now = datetime.now(timezone.utc)

        job_data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "failed",
            "progress": 45,
            "total_records": 10000,
            "processed_records": 4500,
            "format": "csv",
            "file_path": None,
            "file_size_bytes": None,
            "error_message": "Database connection lost",
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }

        key = f"audit_export:{tenant_id}:{job_id}"
        await redis_client.setex(key, 86400, json.dumps(job_data))

        try:
            response = await client.get(
                f"/api/v1/audit/logs/export/{job_id}/download",
                headers=auth_headers,
            )

            assert response.status_code == 400
            assert "not completed" in response.json()["detail"].lower()
        finally:
            await redis_client.delete(key)


class TestAsyncExportProgressTracking:
    """Tests for progress tracking accuracy."""

    async def test_progress_percentage_calculation(
        self, client, auth_headers, redis_client, db_container
    ):
        """Verify progress percentage is calculated correctly."""
        async with db_container() as container:
            user = container.user()
            tenant_id = user.tenant_id

        job_id = uuid4()
        now = datetime.now(timezone.utc)

        # Create job with specific progress
        job_data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "processing",
            "progress": 33,  # 3333 / 10000 = 33.33%
            "total_records": 10000,
            "processed_records": 3333,
            "format": "csv",
            "file_path": None,
            "file_size_bytes": None,
            "error_message": None,
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": None,
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }

        key = f"audit_export:{tenant_id}:{job_id}"
        await redis_client.setex(key, 86400, json.dumps(job_data))

        try:
            response = await client.get(
                f"/api/v1/audit/logs/export/{job_id}/status",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()

            assert data["progress"] == 33
            assert data["processed_records"] == 3333
            assert data["total_records"] == 10000
        finally:
            await redis_client.delete(key)
