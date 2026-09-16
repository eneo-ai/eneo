import pytest

from eneo.completion_models.domain.model_capacity import (
    ModelCapacity,
    UnknownModelCapacityError,
)


@pytest.mark.parametrize("dimension", [0, 1, 2])
def test_unknown_dimension_is_named(dimension: int) -> None:
    values = [100, 80, 120]
    values[dimension] = None
    capacity = ModelCapacity(*values)
    names = ("max_input_tokens", "max_output_tokens", "context_window_tokens")
    assert capacity.missing_dimensions() == (names[dimension],)
    with pytest.raises(UnknownModelCapacityError) as error:
        capacity.admits_request(20, safety_tokens=10, output_reserve_tokens=40)
    assert error.value.missing_dimensions == (names[dimension],)


def test_rules_require_only_their_own_dimensions() -> None:
    capacity = ModelCapacity(None, None, None)
    for rule, expected in (
        (lambda: capacity.admits_input(1, safety_tokens=0), ("max_input_tokens",)),
        (lambda: capacity.output_reserve_fits(1), ("max_output_tokens",)),
        (
            lambda: capacity.builder_input_allowance(
                output_reserve_tokens=1, safety_tokens=0
            ),
            ("max_input_tokens", "context_window_tokens"),
        ),
        (
            lambda: capacity.admits_request(
                1, safety_tokens=0, output_reserve_tokens=1
            ),
            ("max_input_tokens", "max_output_tokens", "context_window_tokens"),
        ),
    ):
        with pytest.raises(UnknownModelCapacityError) as error:
            rule()
        assert error.value.missing_dimensions == expected
    assert ModelCapacity(100, None, None).admits_input(90, safety_tokens=10)
    assert ModelCapacity(None, 80, None).output_reserve_fits(80)
    assert (
        ModelCapacity(100, None, 120).builder_input_allowance(
            output_reserve_tokens=40, safety_tokens=10
        )
        == 70
    )


def test_independent_ceilings_and_equality_boundaries() -> None:
    capacity = ModelCapacity(100, 80, 120)
    assert capacity.admits_input(90, safety_tokens=10)
    assert not capacity.admits_input(91, safety_tokens=10)
    assert capacity.output_reserve_fits(80)
    assert not capacity.output_reserve_fits(81)
    assert capacity.admits_request(30, safety_tokens=10, output_reserve_tokens=80)
    assert not capacity.admits_request(31, safety_tokens=10, output_reserve_tokens=80)
    assert not capacity.admits_request(91, safety_tokens=10, output_reserve_tokens=1)
    assert not capacity.admits_request(1, safety_tokens=10, output_reserve_tokens=81)


@pytest.mark.parametrize(("reserve", "expected"), [(10, 90), (40, 70), (120, -10)])
def test_builder_allowance_charges_safety_once(reserve: int, expected: int) -> None:
    assert (
        ModelCapacity(100, 80, 120).builder_input_allowance(
            output_reserve_tokens=reserve, safety_tokens=10
        )
        == expected
    )


@pytest.mark.parametrize("value", [0, -1])
@pytest.mark.parametrize("dimension", [0, 1, 2])
def test_nonpositive_dimensions_are_rejected(value: int, dimension: int) -> None:
    values = [100, 80, 120]
    values[dimension] = value
    with pytest.raises(ValueError):
        ModelCapacity(*values)
