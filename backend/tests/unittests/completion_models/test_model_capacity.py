import pytest

from eneo.completion_models.domain.model_capacity import (
    ModelCapacity,
    UnknownModelCapacityError,
)


@pytest.mark.parametrize("output,expected", [(40, 40), (100, 80), (120, 80)])
def test_output_cap_reserves_complete_input(output: int, expected: int) -> None:
    assert (
        ModelCapacity(100, output).resolve_output_cap(input_tokens=10, safety_tokens=10)
        == expected
    )


@pytest.mark.parametrize("input_tokens,expected", [(89, 1), (90, None), (100, None)])
def test_output_cap_exact_fit_and_overflow(input_tokens, expected) -> None:
    from eneo.completion_models.domain.model_capacity import ModelCapacityNoFit

    result = ModelCapacity(100, 80).resolve_output_cap(
        input_tokens=input_tokens, safety_tokens=10
    )
    if expected is None:
        assert isinstance(result, ModelCapacityNoFit)
    else:
        assert result == expected


@pytest.mark.parametrize("dimension", [0, 1])
def test_unknown_dimension_is_named_even_with_caller_cap(dimension: int) -> None:
    values = [100, 80]
    values[dimension] = None
    capacity = ModelCapacity(*values)
    names = ("max_input_tokens", "max_output_tokens")
    assert capacity.missing_dimensions() == (names[dimension],)
    with pytest.raises(UnknownModelCapacityError) as error:
        capacity.resolve_output_cap(input_tokens=20, safety_tokens=10, caller_cap=5)
    assert error.value.missing_dimensions == (names[dimension],)


def test_caller_cap_only_lowers_output() -> None:
    capacity = ModelCapacity(100, 80)
    assert (
        capacity.resolve_output_cap(input_tokens=10, safety_tokens=10, caller_cap=5)
        == 5
    )
    assert (
        capacity.resolve_output_cap(input_tokens=10, safety_tokens=10, caller_cap=90)
        == 80
    )


def test_rules_require_only_their_own_dimensions() -> None:
    capacity = ModelCapacity(None, None)
    for rule, expected in (
        (lambda: capacity.admits_input(1, safety_tokens=0), ("max_input_tokens",)),
        (lambda: capacity.output_reserve_fits(1), ("max_output_tokens",)),
        (
            lambda: capacity.input_allowance(output_reserve_tokens=1, safety_tokens=0),
            ("max_input_tokens",),
        ),
    ):
        with pytest.raises(UnknownModelCapacityError) as error:
            rule()
        assert error.value.missing_dimensions == expected
    assert ModelCapacity(100, None).admits_input(90, safety_tokens=10)
    assert not ModelCapacity(100, None).admits_input(91, safety_tokens=10)
    assert ModelCapacity(None, 80).output_reserve_fits(80)
    assert not ModelCapacity(None, 80).output_reserve_fits(81)


@pytest.mark.parametrize("reserve,expected", [(10, 80), (40, 50), (90, 0), (120, -30)])
def test_input_allowance_charges_safety_once(reserve: int, expected: int) -> None:
    assert (
        ModelCapacity(100, None).input_allowance(
            output_reserve_tokens=reserve, safety_tokens=10
        )
        == expected
    )


@pytest.mark.parametrize(
    "input_tokens,output_tokens,safety,status",
    [
        (12, 1, 10, "ready"),
        (11, 100, 10, "capacity_too_small"),
        (10, 100, 10, "capacity_too_small"),
        (2, 100, 0, "ready"),
        (1, 100, 0, "capacity_too_small"),
        (None, 100, 0, "capacity_undeclared"),
        (100, None, 0, "capacity_undeclared"),
    ],
)
def test_structural_availability(input_tokens, output_tokens, safety, status) -> None:
    assert (
        ModelCapacity(input_tokens, output_tokens).availability(safety_tokens=safety)
        == status
    )


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "10"])
@pytest.mark.parametrize("dimension", [0, 1])
def test_invalid_dimensions_are_rejected(value, dimension: int) -> None:
    values = [100, 80]
    values[dimension] = value
    with pytest.raises(ValueError):
        ModelCapacity(*values)
