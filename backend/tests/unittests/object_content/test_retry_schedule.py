import pytest

from eneo.object_content.content_service import retry_delay_seconds


def test_retry_delay_is_exponential_and_capped() -> None:
    assert retry_delay_seconds(1, base_seconds=30, maximum_seconds=300) == 30
    assert retry_delay_seconds(2, base_seconds=30, maximum_seconds=300) == 60
    assert retry_delay_seconds(5, base_seconds=30, maximum_seconds=300) == 300
    assert retry_delay_seconds(10_000, base_seconds=30, maximum_seconds=300) == 300


@pytest.mark.parametrize(
    ("attempt", "base", "maximum"),
    [(0, 1, 1), (1, 0, 1), (1, 2, 1)],
)
def test_retry_delay_rejects_invalid_bounds(
    attempt: int,
    base: int,
    maximum: int,
) -> None:
    with pytest.raises(ValueError, match="retry bounds"):
        retry_delay_seconds(
            attempt,
            base_seconds=base,
            maximum_seconds=maximum,
        )
