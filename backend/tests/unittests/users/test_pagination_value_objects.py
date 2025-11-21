"""
Unit tests for pagination domain value objects.

Tests follow TDD RED-GREEN-REFACTOR cycle:
- RED phase: Write tests that fail (domain objects don't exist yet)
- GREEN phase: Implement minimum code to make tests pass
- REFACTOR phase: Improve code quality

These tests validate:
- PaginationParams validation and offset calculation
- SearchFilters filter detection logic
- SortOptions default values
- PaginatedResult metadata calculations
"""
import pytest

from intric.users.user import (
    PaginationParams,
    PaginatedResult,
    SearchFilters,
    SortField,
    SortOptions,
    SortOrder,
)


class TestPaginationParams:
    """Test PaginationParams validation and offset calculation"""

    def test_valid_pagination(self):
        """Valid page and page_size should initialize without error"""
        params = PaginationParams(page=1, page_size=50)
        assert params.page == 1
        assert params.page_size == 50

    def test_offset_calculation(self):
        """Offset should be calculated as (page - 1) * page_size"""
        # First page offset is 0
        params = PaginationParams(page=1, page_size=100)
        assert params.offset == 0

        # Second page offset is 100
        params = PaginationParams(page=2, page_size=100)
        assert params.offset == 100

        # Third page with page_size=50 offset is 100
        params = PaginationParams(page=3, page_size=50)
        assert params.offset == 100

        # Page 10 with page_size=25 offset is 225
        params = PaginationParams(page=10, page_size=25)
        assert params.offset == 225

    def test_page_too_low_raises_error(self):
        """page < 1 should raise ValueError"""
        with pytest.raises(ValueError, match="page must be >= 1"):
            PaginationParams(page=0, page_size=50)

        with pytest.raises(ValueError, match="page must be >= 1"):
            PaginationParams(page=-1, page_size=50)

    def test_page_exceeds_max_depth_raises_error(self):
        """page > 100 should raise ValueError (max depth limit)"""
        with pytest.raises(ValueError, match="page must be <= 100"):
            PaginationParams(page=101, page_size=50)

        with pytest.raises(ValueError, match="page must be <= 100"):
            PaginationParams(page=200, page_size=50)

    def test_page_size_too_low_raises_error(self):
        """page_size < 1 should raise ValueError"""
        with pytest.raises(ValueError, match="page_size must be >= 1"):
            PaginationParams(page=1, page_size=0)

        with pytest.raises(ValueError, match="page_size must be >= 1"):
            PaginationParams(page=1, page_size=-5)

    def test_page_size_exceeds_max_raises_error(self):
        """page_size > 100 should raise ValueError"""
        with pytest.raises(ValueError, match="page_size must be <= 100"):
            PaginationParams(page=1, page_size=101)

        with pytest.raises(ValueError, match="page_size must be <= 100"):
            PaginationParams(page=1, page_size=1000)

    def test_default_values(self):
        """Default values should be page=1, page_size=100"""
        params = PaginationParams()
        assert params.page == 1
        assert params.page_size == 100
        assert params.offset == 0


class TestSearchFilters:
    """Test SearchFilters filter detection logic"""

    def test_has_filters_email_only(self):
        """has_filters() should return True when email filter is set"""
        filters = SearchFilters(email="john")
        assert filters.has_filters() is True

    def test_has_filters_name_only(self):
        """has_filters() should return True when name filter is set"""
        filters = SearchFilters(name="emma")
        assert filters.has_filters() is True

    def test_has_filters_both(self):
        """has_filters() should return True when both filters are set"""
        filters = SearchFilters(email="john", name="doe")
        assert filters.has_filters() is True

    def test_has_filters_none(self):
        """has_filters() should return False when no filters are set"""
        filters = SearchFilters()
        assert filters.has_filters() is False

        filters = SearchFilters(email=None, name=None)
        assert filters.has_filters() is False


class TestSortOptions:
    """Test SortOptions default values and enum usage"""

    def test_default_sort(self):
        """Default sort should be created_at DESC"""
        sort = SortOptions()
        assert sort.field == SortField.CREATED_AT
        assert sort.order == SortOrder.DESC

    def test_custom_sort(self):
        """Custom sort options should be stored correctly"""
        sort = SortOptions(field=SortField.EMAIL, order=SortOrder.ASC)
        assert sort.field == SortField.EMAIL
        assert sort.order == SortOrder.ASC

    def test_sort_field_enum_values(self):
        """SortField enum should have correct values"""
        assert SortField.EMAIL.value == "email"
        assert SortField.USERNAME.value == "username"
        assert SortField.CREATED_AT.value == "created_at"

    def test_sort_order_enum_values(self):
        """SortOrder enum should have correct values"""
        assert SortOrder.ASC.value == "asc"
        assert SortOrder.DESC.value == "desc"


class TestPaginatedResult:
    """Test PaginatedResult metadata calculations"""

    def test_total_pages_calculation(self):
        """total_pages should be calculated correctly"""
        # Exact multiple: 100 items / 25 per page = 4 pages
        result = PaginatedResult(items=[], total_count=100, page=1, page_size=25)
        assert result.total_pages == 4

        # With remainder: 105 items / 25 per page = 5 pages (ceil division)
        result = PaginatedResult(items=[], total_count=105, page=1, page_size=25)
        assert result.total_pages == 5

        # Single item: 1 item / 100 per page = 1 page
        result = PaginatedResult(items=[], total_count=1, page=1, page_size=100)
        assert result.total_pages == 1

        # Empty result: 0 items = 0 pages
        result = PaginatedResult(items=[], total_count=0, page=1, page_size=100)
        assert result.total_pages == 0

    def test_has_next_calculation(self):
        """has_next should be True when more pages exist"""
        # Page 1 of 4: has next
        result = PaginatedResult(items=[], total_count=100, page=1, page_size=25)
        assert result.has_next is True

        # Page 3 of 4: has next
        result = PaginatedResult(items=[], total_count=100, page=3, page_size=25)
        assert result.has_next is True

        # Page 4 of 4: no next
        result = PaginatedResult(items=[], total_count=100, page=4, page_size=25)
        assert result.has_next is False

        # Single page: no next
        result = PaginatedResult(items=[], total_count=50, page=1, page_size=100)
        assert result.has_next is False

        # Empty result: no next
        result = PaginatedResult(items=[], total_count=0, page=1, page_size=100)
        assert result.has_next is False

    def test_has_previous_calculation(self):
        """has_previous should be True when not on first page"""
        # Page 1: no previous
        result = PaginatedResult(items=[], total_count=100, page=1, page_size=25)
        assert result.has_previous is False

        # Page 2: has previous
        result = PaginatedResult(items=[], total_count=100, page=2, page_size=25)
        assert result.has_previous is True

        # Page 4: has previous
        result = PaginatedResult(items=[], total_count=100, page=4, page_size=25)
        assert result.has_previous is True

    def test_generic_type_handling(self):
        """PaginatedResult should work with any item type"""
        # String items
        result = PaginatedResult(items=["a", "b", "c"], total_count=3, page=1, page_size=100)
        assert len(result.items) == 3
        assert result.items[0] == "a"

        # Dict items (simulating user objects)
        users = [{"id": 1, "name": "John"}, {"id": 2, "name": "Jane"}]
        result = PaginatedResult(items=users, total_count=2, page=1, page_size=100)
        assert len(result.items) == 2
        assert result.items[0]["name"] == "John"

    def test_edge_case_large_page_size(self):
        """PaginatedResult should handle page_size larger than total_count"""
        result = PaginatedResult(items=[], total_count=50, page=1, page_size=100)
        assert result.total_pages == 1
        assert result.has_next is False
        assert result.has_previous is False
