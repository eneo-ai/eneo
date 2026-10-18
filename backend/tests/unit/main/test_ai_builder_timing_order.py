import pytest

from eneo.main.ai_builder_timing_order import ai_builder_timing_order_violation


@pytest.mark.parametrize(
    ("deadlines", "expected"),
    [
        # Each row names the mutant it kills.
        # Mutant: equality is refused (the request budget allows ceiling == silence).
        ((300.0, 300.0, None, None), None),
        # Mutant: the silence / call ceiling comparison is dropped or reversed.
        ((301.0, 300.0, None, None), ("silence_above_call_ceiling", 301.0, 300.0)),
        # Mutant: an explicit classification silence is not held to the ceiling.
        (
            (100.0, 300.0, 400.0, None),
            ("classification_silence_above_call_ceiling", 400.0, 300.0),
        ),
        # Mutant: the classification ceiling's upper bound is dropped.
        (
            (100.0, 300.0, None, 301.0),
            ("classification_ceiling_above_call_ceiling", 301.0, 300.0),
        ),
        # Mutant: the lower bound is dropped; it is the inherited silence here.
        (
            (200.0, 300.0, None, 150.0),
            ("classification_ceiling_below_classification_silence", 150.0, 200.0),
        ),
        # Mutant: the lower bound uses the silence deadline although the
        # classification has its own.
        (
            (200.0, 300.0, 100.0, 150.0),
            None,
        ),
        # A bound is inclusive on both sides.
        ((200.0, 300.0, 100.0, 100.0), None),
        ((200.0, 300.0, 100.0, 300.0), None),
        # Mutant: NaN passes as in order.
        (
            (float("nan"), 300.0, None, None),
            ("silence_above_call_ceiling", float("nan"), 300.0),
        ),
    ],
)
def test_timing_order_names_the_first_rule_the_deadlines_break(
    deadlines: tuple[float, float, float | None, float | None],
    expected: tuple[str, float, float] | None,
) -> None:
    silence, ceiling, classification_silence, classification_ceiling = deadlines

    violation = ai_builder_timing_order_violation(
        silence_seconds=silence,
        call_ceiling_seconds=ceiling,
        classification_silence_seconds=classification_silence,
        classification_ceiling_seconds=classification_ceiling,
    )

    if expected is None:
        assert violation is None
        return
    assert violation is not None
    # repr, because NaN never equals itself.
    assert (violation.rule, repr(violation.value), repr(violation.bound)) == (
        expected[0],
        repr(expected[1]),
        repr(expected[2]),
    )
