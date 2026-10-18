import pytest

from eneo.main.ai_builder_timing_order import ai_builder_timing_order_violation


@pytest.mark.parametrize(
    ("deadlines", "expected"),
    [
        # Each row names the mutant it kills.
        # Mutant: equality is refused (the request budget allows ceiling == silence).
        ((300.0, 300.0), None),
        # Mutant: the silence / call ceiling comparison is dropped or reversed.
        ((301.0, 300.0), (301.0, 300.0)),
        # Mutant: NaN passes as in order.
        ((float("nan"), 300.0), (float("nan"), 300.0)),
    ],
)
def test_timing_order_names_the_deadlines_that_break_it(
    deadlines: tuple[float, float],
    expected: tuple[float, float] | None,
) -> None:
    silence, ceiling = deadlines

    violation = ai_builder_timing_order_violation(
        silence_seconds=silence, call_ceiling_seconds=ceiling
    )

    if expected is None:
        assert violation is None
        return
    assert violation is not None
    # repr, because NaN never equals itself.
    assert (repr(violation.value), repr(violation.bound)) == (
        repr(expected[0]),
        repr(expected[1]),
    )
