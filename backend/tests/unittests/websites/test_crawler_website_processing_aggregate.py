import pytest

from intric.websites.domain.crawler_website_processing_aggregate import (
    SCHEDULE_FREQUENCY_WEIGHTS,
    cost_pressure_score,
    retention_rate,
    schedule_frequency_weight,
)
from intric.websites.domain.website import UpdateInterval


def test_schedule_frequency_weights_cover_all_update_intervals():
    assert set(SCHEDULE_FREQUENCY_WEIGHTS) == set(UpdateInterval)


@pytest.mark.parametrize(
    ("update_interval", "expected_weight"),
    [
        (UpdateInterval.DAILY, 7.0),
        (UpdateInterval.EVERY_OTHER_DAY, 3.5),
        (UpdateInterval.WEEKLY, 1.0),
        (UpdateInterval.NEVER, 0.0),
        (None, 0.0),
    ],
)
def test_schedule_frequency_weight_is_defined_for_supported_intervals(
    update_interval: UpdateInterval | None,
    expected_weight: float,
):
    assert schedule_frequency_weight(update_interval) == expected_weight


def test_retention_rate_is_retained_share_of_indexed_content():
    assert retention_rate(retained_count=9, indexed_content_count=22) == pytest.approx(
        9 / 22
    )


def test_retention_rate_is_zero_when_there_is_no_indexed_content():
    assert retention_rate(retained_count=0, indexed_content_count=0) == 0.0


def test_cost_pressure_score_weights_changed_content_by_schedule_frequency():
    assert cost_pressure_score(
        schedule_weight=7.0,
        indexed_content_count=22,
        retained_count=9,
    ) == pytest.approx(91.0)


def test_cost_pressure_score_is_zero_when_there_is_no_indexed_content():
    assert (
        cost_pressure_score(
            schedule_weight=7.0,
            indexed_content_count=0,
            retained_count=0,
        )
        == 0.0
    )
