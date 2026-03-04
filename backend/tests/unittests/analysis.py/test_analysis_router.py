from datetime import datetime, timedelta, timezone

import pytest

from intric.analysis.analysis_router import _normalize_datetime_range
from intric.main.exceptions import BadRequestException


def test_both_dates_none_falls_back_to_days_since():
    """When both dates are None, falls back to days_since default range."""
    from_date, to_date = _normalize_datetime_range(
        from_date=None, to_date=None, days_since=30
    )

    assert to_date.tzinfo == timezone.utc
    assert from_date.tzinfo == timezone.utc
    assert (to_date - from_date).days == 30


def test_only_from_date_provided():
    """When only from_date is provided, to_date defaults to now."""
    explicit_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
    from_date, to_date = _normalize_datetime_range(
        from_date=explicit_from, to_date=None, days_since=30
    )

    assert from_date == explicit_from
    assert to_date.tzinfo == timezone.utc
    # to_date should be approximately now
    assert abs((datetime.now(timezone.utc) - to_date).total_seconds()) < 5


def test_only_to_date_provided():
    """When only to_date is provided, from_date defaults to now - days_since."""
    # Use a future date so from_date (now - 7 days) is still before to_date
    explicit_to = datetime.now(timezone.utc) + timedelta(days=1)
    from_date, to_date = _normalize_datetime_range(
        from_date=None, to_date=explicit_to, days_since=7
    )

    assert to_date == explicit_to
    assert from_date.tzinfo == timezone.utc
    # from_date should be approximately 7 days before now
    expected_from = datetime.now(timezone.utc) - timedelta(days=7)
    assert abs((from_date - expected_from).total_seconds()) < 5


def test_from_date_after_to_date_raises():
    """When from_date > to_date, raises BadRequestException."""
    with pytest.raises(BadRequestException, match="from_date must be before to_date"):
        _normalize_datetime_range(
            from_date=datetime(2026, 2, 10, tzinfo=timezone.utc),
            to_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            days_since=30,
        )


def test_naive_datetimes_get_utc():
    """Naive datetimes get UTC tzinfo attached."""
    from_date, to_date = _normalize_datetime_range(
        from_date=datetime(2026, 1, 1),
        to_date=datetime(2026, 2, 1),
        days_since=30,
    )

    assert from_date.tzinfo == timezone.utc
    assert to_date.tzinfo == timezone.utc
    assert from_date == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert to_date == datetime(2026, 2, 1, tzinfo=timezone.utc)


def test_both_dates_provided_passthrough():
    """When both dates are provided, they pass through with tz normalization."""
    explicit_from = datetime(2026, 1, 15, tzinfo=timezone.utc)
    explicit_to = datetime(2026, 2, 15, tzinfo=timezone.utc)
    from_date, to_date = _normalize_datetime_range(
        from_date=explicit_from, to_date=explicit_to, days_since=30
    )

    assert from_date == explicit_from
    assert to_date == explicit_to
