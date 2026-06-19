from unittest.mock import AsyncMock

import pytest

from intric.scim.constants import SCIM_FILTER_MAX_RESULTS
from intric.scim.schemas.common import ScimFilter, clamp_count


class TestClampCount:
    @pytest.mark.parametrize(
        "given,expected",
        [
            (None, SCIM_FILTER_MAX_RESULTS),  # omitted → bounded, not unbounded
            (0, 0),  # RFC 7644 §3.4.2.4: 0 → totalResults only
            (-5, 0),  # negative interpreted as 0
            (1, 1),
            (SCIM_FILTER_MAX_RESULTS, SCIM_FILTER_MAX_RESULTS),
            (SCIM_FILTER_MAX_RESULTS + 1, SCIM_FILTER_MAX_RESULTS),  # clamped down
            (10_000, SCIM_FILTER_MAX_RESULTS),
        ],
    )
    def test_clamp_count(self, given, expected):
        assert clamp_count(given) == expected


class TestScimFilterParse:
    @pytest.mark.parametrize(
        "expr,attribute,operator,value",
        [
            ('userName eq "jane@example.com"', "userName", "eq", "jane@example.com"),
            ('userName co "jane"', "userName", "co", "jane"),
            ('externalId eq "aad-guid"', "externalId", "eq", "aad-guid"),
            ("userName pr", "userName", "pr", None),  # presence: valueless
            ('  userName eq "x"  ', "userName", "eq", "x"),  # surrounding ws ok
        ],
    )
    def test_valid_single_expression(self, expr, attribute, operator, value):
        result = ScimFilter.parse(expr)
        assert result == ScimFilter(attribute, operator, value)

    @pytest.mark.parametrize(
        "expr",
        [
            # Composite filters are unsupported — must NOT silently match the
            # first clause and drop the rest (the core of this bug).
            'userName eq "a" and active eq true',
            'userName eq "a" or userName eq "b"',
            'userName eq "a" and emails.value co "x"',
            # Trailing garbage after a valid expression.
            'userName eq "a" extrastuff',
            # Non-pr operator without a value (incl. unquoted boolean forms).
            "userName eq",
            "active eq true",
            # Not a comparison expression at all.
            "garbage",
            "",
        ],
    )
    def test_rejects_invalid_or_partial(self, expr):
        assert ScimFilter.parse(expr) is None


class TestCompositeFilterRejectedByService:
    async def test_list_users_raises_invalid_filter_on_composite(self):
        from uuid import uuid4

        from intric.scim.domain.errors import ScimInvalidFilterError
        from intric.scim.services.user_service import ScimUserService

        service = ScimUserService(repository=AsyncMock(), tenant_id=uuid4())
        with pytest.raises(ScimInvalidFilterError):
            await service.list_users(filter_str='userName eq "a" and active eq true')
