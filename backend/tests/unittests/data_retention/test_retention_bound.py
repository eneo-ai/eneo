"""The one bound every retention period is validated against."""

import pytest

from eneo.data_retention.constants import (
    MAX_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
    validate_retention_days,
)


def test_a_period_inside_the_bound_is_returned_and_one_outside_is_refused():
    """Mutants: the validator is removed although Flows settings call it, or it
    lets a period outside 1 to 2555 days through."""
    assert validate_retention_days(MIN_RETENTION_DAYS) == 1
    assert validate_retention_days(MAX_RETENTION_DAYS) == 2555

    with pytest.raises(ValueError, match="Minimum flow retention period is 1 day"):
        validate_retention_days(0, context="flow")
    with pytest.raises(ValueError, match="Maximum flow retention period is 2555 days"):
        validate_retention_days(2556, context="flow")
