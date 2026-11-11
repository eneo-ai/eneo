"""The shared level kernel: inheritance, bounds and where a value comes from.

Retention passes "fewer days is stricter" with no bounding level, so the
nearest chosen period wins. An access requirement passes "required is
stricter" with every level bounding, which makes the levels an OR that an
inner level can raise but never lower.
"""

import pytest

from eneo.policy_levels import LevelSetting, PolicyLevel, Resolved, admits, resolve

ORG = PolicyLevel.ORGANIZATION
SPACE = PolicyLevel.SPACE
OWN = PolicyLevel.ASSISTANT_OR_APP
EVERY_LEVEL = frozenset(PolicyLevel)


def fewer_days(candidate: int, current: int) -> bool:
    return candidate < current


def required(candidate: bool, current: bool) -> bool:
    return candidate and not current


def test_level_values_are_the_released_strings():
    """Mutant: a level is renamed, so the audit count keys and the API strings
    built from it change without a decision."""
    assert [level.value for level in PolicyLevel] == [
        "installation",
        "organization",
        "space",
        "assistant_or_app",
        "flow",
    ]


def test_an_empty_chain_and_a_chain_without_choices_resolve_to_nothing():
    """Mutant: no choice anywhere resolves to a value, so something is removed
    or required that nobody chose."""
    nothing: Resolved[int] = Resolved(None, None, None, None)
    assert resolve([], stricter=fewer_days) == nothing
    assert (
        resolve(
            [LevelSetting(ORG, None), LevelSetting(SPACE, None)], stricter=fewer_days
        )
        == nothing
    )


@pytest.mark.parametrize(
    "org,space,own,expected",
    [
        (90, None, None, (90, ORG)),
        (90, 60, None, (60, SPACE)),
        (90, 60, 30, (30, OWN)),
        (30, 60, None, (60, SPACE)),
        (30, None, 60, (60, OWN)),
        (None, None, 60, (60, OWN)),
    ],
)
def test_without_a_bound_the_nearest_choice_wins_also_when_longer(
    org: int | None,
    space: int | None,
    own: int | None,
    expected: tuple[int, PolicyLevel],
):
    """Mutants: the strictest value wins instead of the nearest; an unset inner
    level hides the outer choice; the origin names the wrong level."""
    resolved = resolve(
        [LevelSetting(ORG, org), LevelSetting(SPACE, space), LevelSetting(OWN, own)],
        stricter=fewer_days,
    )
    assert (resolved.value, resolved.origin) == expected
    assert (resolved.bound, resolved.bound_origin) == (None, None)


def test_a_bounding_level_caps_every_inner_choice():
    """Mutants: an inner value loosens the bound; the result names the inner
    level although the bound decided it; a stricter inner value is raised to
    the bound."""
    bounded = frozenset({ORG})
    looser = resolve(
        [LevelSetting(ORG, 30), LevelSetting(SPACE, 90)],
        stricter=fewer_days,
        bounding=bounded,
    )
    stricter = resolve(
        [LevelSetting(ORG, 30), LevelSetting(SPACE, 7)],
        stricter=fewer_days,
        bounding=bounded,
    )
    assert looser == Resolved(30, ORG, 30, ORG)
    assert stricter == Resolved(7, SPACE, 30, ORG)


def test_on_a_tie_the_nearest_level_is_the_origin_and_the_outermost_bound_binds():
    """Mutants: a tie credits the bound instead of the nearest choice; among
    equal bounds the inner one is reported, although the outer one is the
    level an inner change cannot loosen."""
    resolved = resolve(
        [LevelSetting(ORG, 30), LevelSetting(SPACE, 30), LevelSetting(OWN, 30)],
        stricter=fewer_days,
        bounding=frozenset({ORG, SPACE}),
    )
    assert resolved == Resolved(30, OWN, 30, ORG)


@pytest.mark.parametrize(
    "org,space,expected",
    [
        (None, None, Resolved(None, None, None, None)),
        (False, None, Resolved(False, ORG, False, ORG)),
        (True, None, Resolved(True, ORG, True, ORG)),
        (False, True, Resolved(True, SPACE, True, SPACE)),
        (True, False, Resolved(True, ORG, True, ORG)),
        (True, True, Resolved(True, SPACE, True, ORG)),
        (None, True, Resolved(True, SPACE, True, SPACE)),
    ],
)
def test_a_requirement_on_every_level_is_an_or_that_an_inner_level_cannot_lower(
    org: bool | None, space: bool | None, expected: Resolved[bool]
):
    """Mutants: an inner False lowers an outer requirement; False is read as no
    choice; the provenance hides which level requires it."""
    assert (
        resolve(
            [LevelSetting(ORG, org), LevelSetting(SPACE, space)],
            stricter=required,
            bounding=EVERY_LEVEL,
        )
        == expected
    )


def test_a_level_appears_once_in_a_chain():
    """Mutant: a repeated level is accepted, so the caller's order, not the
    level, decides which of the two values counts."""
    with pytest.raises(ValueError):
        resolve([LevelSetting(SPACE, 30), LevelSetting(SPACE, 60)], stricter=fewer_days)


def test_a_write_may_inherit_or_tighten_but_never_loosen_a_bound():
    """Mutants: a write looser than the parent's bound is admitted; clearing
    a value (inheriting) is refused; a parent without a bound refuses writes."""
    parent = resolve(
        [LevelSetting(ORG, 30)], stricter=fewer_days, bounding=frozenset({ORG})
    )
    unbounded = resolve([LevelSetting(ORG, 30)], stricter=fewer_days)

    assert admits(parent, None, stricter=fewer_days)
    assert admits(parent, 30, stricter=fewer_days)
    assert admits(parent, 7, stricter=fewer_days)
    assert not admits(parent, 31, stricter=fewer_days)
    assert admits(unbounded, 365, stricter=fewer_days)

    required_above = resolve(
        [LevelSetting(ORG, True)], stricter=required, bounding=EVERY_LEVEL
    )
    assert admits(required_above, True, stricter=required)
    assert not admits(required_above, False, stricter=required)
