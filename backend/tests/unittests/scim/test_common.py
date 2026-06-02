import pytest

from intric.scim.constants import SCIM_FILTER_MAX_RESULTS
from intric.scim.schemas.common import clamp_count


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
