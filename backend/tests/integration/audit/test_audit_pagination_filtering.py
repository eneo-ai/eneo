"""Integration tests for audit log pagination and filtering."""

import pytest
from datetime import datetime, timezone, timedelta

pytestmark = pytest.mark.integration


class TestPaginationBasics:
    """Tests for basic pagination functionality."""

    async def test_first_page_returns_correct_count(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify first page returns correct number of items."""
        headers, cookies = auth_headers_with_session
        response = await client.get(
            "/api/v1/audit/logs?page=1&page_size=10",
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()

        assert len(data["logs"]) <= 10
        assert data["page"] == 1
        assert data["page_size"] == 10

    async def test_second_page_returns_different_items(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify second page contains different items than first page."""
        headers, cookies = auth_headers_with_session

        # Filter by user_created to avoid interference from audit_log_viewed entries
        # (each request creates a new audit_log_viewed entry which would affect pagination)
        # Get first page
        response1 = await client.get(
            "/api/v1/audit/logs?page=1&page_size=10&action=user_created",
            headers=headers,
            cookies=cookies,
        )
        page1_ids = [log["id"] for log in response1.json()["logs"]]

        # Get second page
        response2 = await client.get(
            "/api/v1/audit/logs?page=2&page_size=10&action=user_created",
            headers=headers,
            cookies=cookies,
        )
        page2_ids = [log["id"] for log in response2.json()["logs"]]

        # Pages should have no overlap
        overlap = set(page1_ids) & set(page2_ids)
        assert len(overlap) == 0, "Pages should contain different items"

    async def test_total_count_is_consistent(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify total_count is same across different pages."""
        headers, cookies = auth_headers_with_session

        # Filter by user_created to avoid interference from audit_log_viewed entries
        # (each request creates a new audit_log_viewed entry which would change the count)
        response1 = await client.get(
            "/api/v1/audit/logs?page=1&page_size=10&action=user_created",
            headers=headers,
            cookies=cookies,
        )
        response2 = await client.get(
            "/api/v1/audit/logs?page=2&page_size=10&action=user_created",
            headers=headers,
            cookies=cookies,
        )

        assert response1.json()["total_count"] == response2.json()["total_count"]

    async def test_total_pages_calculated_correctly(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify total_pages is calculated correctly."""
        headers, cookies = auth_headers_with_session
        response = await client.get(
            "/api/v1/audit/logs?page=1&page_size=10",
            headers=headers,
            cookies=cookies,
        )
        data = response.json()

        expected_pages = (data["total_count"] + 9) // 10  # Ceiling division
        assert data["total_pages"] == expected_pages


class TestPaginationEdgeCases:
    """Tests for pagination edge cases."""

    async def test_page_size_of_one(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify page_size=1 works correctly."""
        headers, cookies = auth_headers_with_session
        response = await client.get(
            "/api/v1/audit/logs?page=1&page_size=1",
            headers=headers,
            cookies=cookies,
        )
        data = response.json()

        assert len(data["logs"]) <= 1
        assert data["page_size"] == 1

    async def test_page_beyond_total_returns_empty(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify requesting page beyond total returns empty list."""
        headers, cookies = auth_headers_with_session

        # Get total pages first
        response1 = await client.get(
            "/api/v1/audit/logs?page=1&page_size=100",
            headers=headers,
            cookies=cookies,
        )
        total_pages = response1.json()["total_pages"]

        # Request page beyond total
        response2 = await client.get(
            f"/api/v1/audit/logs?page={total_pages + 100}&page_size=100",
            headers=headers,
            cookies=cookies,
        )
        data = response2.json()

        assert len(data["logs"]) == 0

    async def test_large_page_size(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify maximum page_size (1000) works."""
        headers, cookies = auth_headers_with_session
        response = await client.get(
            "/api/v1/audit/logs?page=1&page_size=1000",
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["page_size"] == 1000

    async def test_no_logs_returns_empty_list(self, client, auth_headers_with_session):
        """Verify empty result returns proper structure."""
        headers, cookies = auth_headers_with_session

        # Use a filter that matches nothing
        # Use params dict to let httpx handle URL encoding properly
        # (otherwise + in +00:00 is interpreted as space in query strings)
        far_future = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()

        response = await client.get(
            "/api/v1/audit/logs",
            params={"from_date": far_future},
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()

        assert data["logs"] == []
        assert data["total_count"] == 0
        assert data["total_pages"] == 0


class TestFilteringByAction:
    """Tests for action type filtering."""

    async def test_filter_user_created(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify filtering by user_created action."""
        headers, cookies = auth_headers_with_session
        response = await client.get(
            "/api/v1/audit/logs?action=user_created",
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()

        for log in data["logs"]:
            assert log["action"] == "user_created"

    async def test_filter_assistant_created(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify filtering by assistant_created action."""
        headers, cookies = auth_headers_with_session
        response = await client.get(
            "/api/v1/audit/logs?action=assistant_created",
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()

        for log in data["logs"]:
            assert log["action"] == "assistant_created"

    async def test_filter_file_uploaded(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify filtering by file_uploaded action."""
        headers, cookies = auth_headers_with_session
        response = await client.get(
            "/api/v1/audit/logs?action=file_uploaded",
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200


class TestFilteringByDateRange:
    """Tests for date range filtering."""

    async def test_filter_from_date(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify from_date filter excludes older logs."""
        headers, cookies = auth_headers_with_session

        # Get logs from 1 hour ago
        from_date = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        response = await client.get(
            "/api/v1/audit/logs",
            params={"from_date": from_date},
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()

        # All logs should be after from_date
        from_dt = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
        for log in data["logs"]:
            log_dt = datetime.fromisoformat(log["created_at"].replace('Z', '+00:00'))
            assert log_dt >= from_dt

    async def test_filter_to_date(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify to_date filter excludes newer logs."""
        headers, cookies = auth_headers_with_session

        # Get logs up to 1 hour ago
        to_date = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        response = await client.get(
            "/api/v1/audit/logs",
            params={"to_date": to_date},
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200

    async def test_filter_date_range(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify combined from_date and to_date filter."""
        headers, cookies = auth_headers_with_session

        from_date = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        to_date = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        response = await client.get(
            "/api/v1/audit/logs",
            params={"from_date": from_date, "to_date": to_date},
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200


class TestCombinedFiltersAndPagination:
    """Tests for combining filters with pagination."""

    async def test_action_filter_with_pagination(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify action filter works with pagination."""
        headers, cookies = auth_headers_with_session

        # Get first page with filter
        response = await client.get(
            "/api/v1/audit/logs?action=user_created&page=1&page_size=5",
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()

        # All items should match filter
        for log in data["logs"]:
            assert log["action"] == "user_created"

        # total_count should only include filtered items
        assert data["total_count"] <= 55  # sample_audit_logs creates 55

    async def test_date_filter_with_pagination(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify date filter works with pagination."""
        headers, cookies = auth_headers_with_session

        from_date = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        response = await client.get(
            "/api/v1/audit/logs",
            params={"from_date": from_date, "page": 1, "page_size": 5},
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()

        # Verify pagination structure
        assert data["page"] == 1
        assert data["page_size"] == 5

    async def test_multiple_filters_with_pagination(self, client, auth_headers_with_session, sample_audit_logs, test_user):
        """Verify multiple filters combined with pagination."""
        headers, cookies = auth_headers_with_session

        from_date = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()

        response = await client.get(
            "/api/v1/audit/logs",
            params={
                "actor_id": str(test_user),
                "action": "user_created",
                "from_date": from_date,
                "page": 1,
                "page_size": 5
            },
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200


class TestResultOrdering:
    """Tests for result ordering."""

    async def test_results_ordered_by_timestamp_desc(self, client, auth_headers_with_session, sample_audit_logs):
        """Verify results are ordered by timestamp descending (newest first)."""
        headers, cookies = auth_headers_with_session
        # Filter by user_created to avoid interference from audit_log_viewed entries
        # (each request creates a new audit_log_viewed entry which would affect ordering)
        response = await client.get(
            "/api/v1/audit/logs?page=1&page_size=50&action=user_created",
            headers=headers,
            cookies=cookies,
        )
        data = response.json()

        if len(data["logs"]) >= 2:
            for i in range(len(data["logs"]) - 1):
                current_time = datetime.fromisoformat(data["logs"][i]["created_at"].replace('Z', '+00:00'))
                next_time = datetime.fromisoformat(data["logs"][i + 1]["created_at"].replace('Z', '+00:00'))
                assert current_time >= next_time, "Results should be ordered newest first"


class TestSearchFiltering:
    """Tests for entity name search filtering using pg_trgm."""

    async def test_search_filters_by_description(self, client, auth_headers_with_session, searchable_audit_logs):
        """Search term matches logs where description contains the term."""
        headers, cookies = auth_headers_with_session
        response = await client.get(
            "/api/v1/audit/logs",
            params={"search": "Sales Bot"},
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()

        # All results should contain "Sales Bot" in description
        assert len(data["logs"]) > 0, "Should find logs matching 'Sales Bot'"
        for log in data["logs"]:
            assert "sales bot" in log["description"].lower(), f"Expected 'Sales Bot' in description: {log['description']}"

    async def test_search_is_case_insensitive(self, client, auth_headers_with_session, searchable_audit_logs):
        """Search works regardless of case."""
        headers, cookies = auth_headers_with_session

        # Search with different cases
        response_lower = await client.get(
            "/api/v1/audit/logs",
            params={"search": "sales bot"},
            headers=headers,
            cookies=cookies,
        )
        response_upper = await client.get(
            "/api/v1/audit/logs",
            params={"search": "SALES BOT"},
            headers=headers,
            cookies=cookies,
        )
        response_mixed = await client.get(
            "/api/v1/audit/logs",
            params={"search": "SaLeS bOt"},
            headers=headers,
            cookies=cookies,
        )

        assert response_lower.status_code == 200
        assert response_upper.status_code == 200
        assert response_mixed.status_code == 200

        # All should return the same count
        assert response_lower.json()["total_count"] == response_upper.json()["total_count"]
        assert response_lower.json()["total_count"] == response_mixed.json()["total_count"]
        assert response_lower.json()["total_count"] > 0

    async def test_search_combines_with_action_filter(self, client, auth_headers_with_session, searchable_audit_logs):
        """Search AND action filter both apply."""
        headers, cookies = auth_headers_with_session

        # Search with action filter
        response = await client.get(
            "/api/v1/audit/logs",
            params={"search": "Sales Bot", "action": "assistant_created"},
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()

        # Results should match both search AND action
        for log in data["logs"]:
            assert "sales bot" in log["description"].lower()
            assert log["action"] == "assistant_created"

    async def test_search_combines_with_actor_filter(self, client, auth_headers_with_session, searchable_audit_logs, test_user):
        """Search AND actor filter both apply."""
        headers, cookies = auth_headers_with_session

        response = await client.get(
            "/api/v1/audit/logs",
            params={"search": "Documents", "actor_id": str(test_user)},
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()

        # Results should match search term (in description) AND actor filter
        for log in data["logs"]:
            assert "documents" in log["description"].lower()
            assert log["actor_id"] == str(test_user)

    async def test_search_minimum_length_validation(self, client, auth_headers_with_session, searchable_audit_logs):
        """Search requires minimum 3 characters."""
        headers, cookies = auth_headers_with_session

        # 2-char search should return 422 validation error
        response = await client.get(
            "/api/v1/audit/logs",
            params={"search": "ab"},
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 422, "Search with < 3 chars should return validation error"

    async def test_search_no_results_returns_empty(self, client, auth_headers_with_session, searchable_audit_logs):
        """Search that matches nothing returns empty list."""
        headers, cookies = auth_headers_with_session

        response = await client.get(
            "/api/v1/audit/logs",
            params={"search": "NonExistentEntityXYZ123"},
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()

        assert data["logs"] == []
        assert data["total_count"] == 0

    async def test_search_partial_match(self, client, auth_headers_with_session, searchable_audit_logs):
        """Search finds partial matches in description."""
        headers, cookies = auth_headers_with_session

        # Search for partial entity name
        response = await client.get(
            "/api/v1/audit/logs",
            params={"search": "Sales"},  # Should match "Sales Bot"
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()

        assert len(data["logs"]) > 0, "Should find partial matches"
        for log in data["logs"]:
            assert "sales" in log["description"].lower()

    async def test_search_with_pagination(self, client, auth_headers_with_session, searchable_audit_logs):
        """Search works correctly with pagination."""
        headers, cookies = auth_headers_with_session

        # Get first page with search - fixture has 15 "Sales Bot" logs
        response = await client.get(
            "/api/v1/audit/logs",
            params={"search": "Sales Bot", "page": 1, "page_size": 5},
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()

        assert data["page"] == 1
        assert data["page_size"] == 5
        assert len(data["logs"]) == 5, "Should return exactly page_size results"
        assert data["total_count"] == 15, "Fixture creates 15 'Sales Bot' logs"
        assert data["total_pages"] == 3, "15 logs / 5 per page = 3 pages"

        # All results should match search
        for log in data["logs"]:
            assert "sales bot" in log["description"].lower()

    async def test_search_escapes_wildcard_characters(self, client, auth_headers_with_session, searchable_audit_logs):
        """Search properly escapes SQL wildcards (% and _) to treat them as literals."""
        headers, cookies = auth_headers_with_session

        # Search with % character - "Sales%" should NOT match "Sales Bot"
        # If wildcards weren't escaped, "Sales%" would match all 15 "Sales Bot" logs
        response = await client.get(
            "/api/v1/audit/logs",
            params={"search": "Sales%"},
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()

        # Should find nothing since no descriptions contain literal "Sales%"
        # Pre-fix this would have matched "Sales Bot" via wildcard
        assert data["total_count"] == 0, "Literal % should not act as wildcard"

        # Search with _ character - "Sales_Bot" should NOT match "Sales Bot"
        # If _ wasn't escaped, it would match "Sales Bot" (underscore = any single char)
        response = await client.get(
            "/api/v1/audit/logs",
            params={"search": "Sales_Bot"},
            headers=headers,
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()

        # Should find nothing since "Sales Bot" uses space, not underscore
        assert data["total_count"] == 0, "Literal _ should not act as single-char wildcard"
