"""The shared level kernel: inheritance, bounds and where a value comes from.

Retention passes "fewer days is stricter" with no bounding level, so the
nearest chosen period wins. An access requirement passes "required is
stricter" with every level bounding, which makes the levels an OR that an
inner level can raise but never lower. Retention in flows will pass "fewer
days" over organisation, space, flow and step, with the space and the flow
bounding: neither is ever exceeded inside it, and the organisation is a
default that a space inherits, not a cap.
"""

import pytest

from eneo.policy_levels import LevelSetting, PolicyLevel, Resolved, admits, resolve

ORG = PolicyLevel.ORGANIZATION
SPACE = PolicyLevel.SPACE
OWN = PolicyLevel.ASSISTANT_OR_APP
FLOW = PolicyLevel.FLOW
STEP = PolicyLevel.FLOW_STEP
EVERY_LEVEL = frozenset(PolicyLevel)
FLOW_RETENTION_CAPS = frozenset({SPACE, FLOW})


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
        "flow_step",
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
    "org,space,own,expected",
    [
        pytest.param(30, None, 90, Resolved(30, ORG, 30, ORG), id="inherited cap"),
        pytest.param(30, 7, 90, Resolved(7, SPACE, 7, SPACE), id="chosen cap"),
        pytest.param(30, None, 7, Resolved(7, OWN, 30, ORG), id="inner tightens"),
        pytest.param(30, None, 30, Resolved(30, OWN, 30, ORG), id="tie"),
        pytest.param(None, None, 90, Resolved(90, OWN, None, None), id="no cap"),
        pytest.param(None, None, None, Resolved(None, None, None, None), id="none"),
    ],
)
def test_a_bounding_level_caps_with_the_value_it_inherits(
    org: int | None, space: int | None, own: int | None, expected: Resolved[int]
):
    """Mutants: only a value chosen on the bounding level caps, so a space
    that inherits its organisation's period lets an inner level lengthen it;
    the bound names the bounding level instead of the level that chose the
    value."""
    assert (
        resolve(
            [
                LevelSetting(ORG, org),
                LevelSetting(SPACE, space),
                LevelSetting(OWN, own),
            ],
            stricter=fewer_days,
            bounding=frozenset({SPACE}),
        )
        == expected
    )


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


# Retention in flows. The numbers are periods in one unit for the whole chain;
# a step chosen in hours is converted by its caller before it is compared, and
# these tests do not exercise that conversion.


def flow_retention(*periods: int | None) -> Resolved[int]:
    """Organisation, space, flow and step, cut after the periods given: two
    periods resolve the levels outside a flow, three the levels outside a
    step."""
    levels = (ORG, SPACE, FLOW, STEP)
    return resolve(
        [LevelSetting(level, period) for level, period in zip(levels, periods)],
        stricter=fewer_days,
        bounding=FLOW_RETENTION_CAPS,
    )


def test_a_step_keeps_its_own_shorter_period_under_its_flow_and_space():
    """Space 30, flow 7, step 1: the step keeps 1 and the flow keeps 7.
    Mutants: the flow is not a cap, so the bound a step is held to is the
    space's 30; the shortest period in the chain names the wrong level."""
    assert flow_retention(None, 30, 7, 1) == Resolved(1, STEP, 7, FLOW)
    assert flow_retention(None, 30, 7) == Resolved(7, FLOW, 7, FLOW)


@pytest.mark.parametrize(
    "org,space,flow,step,expected",
    [
        pytest.param(None, 30, 7, 10, Resolved(7, FLOW, 7, FLOW), id="flow caps"),
        pytest.param(
            None, 30, None, 40, Resolved(30, SPACE, 30, SPACE), id="space caps"
        ),
        pytest.param(None, None, 7, 10, Resolved(7, FLOW, 7, FLOW), id="no space"),
    ],
)
def test_a_step_never_outlives_the_flow_or_the_space_that_caps_it(
    org: int | None,
    space: int | None,
    flow: int | None,
    step: int | None,
    expected: Resolved[int],
):
    """Mutants: the flow is not a cap, so a step resolves to a longer period
    than its flow's; a step longer than its caps keeps its own period."""
    assert flow_retention(org, space, flow, step) == expected


@pytest.mark.parametrize(
    "org,space,flow,step,expected",
    [
        pytest.param(
            None, 30, None, None, Resolved(30, SPACE, 30, SPACE), id="from space"
        ),
        pytest.param(None, 30, 7, None, Resolved(7, FLOW, 7, FLOW), id="from flow"),
        pytest.param(
            None, None, None, 2, Resolved(2, STEP, None, None), id="step alone"
        ),
        pytest.param(
            None, None, None, None, Resolved(None, None, None, None), id="nothing"
        ),
    ],
)
def test_an_empty_level_in_a_flow_inherits_the_nearest_choice_outside_it(
    org: int | None,
    space: int | None,
    flow: int | None,
    step: int | None,
    expected: Resolved[int],
):
    """Mutants: an empty step or flow is read as no retention although a level
    outside it chose one; nothing chosen anywhere still removes something; the
    flow is not a cap, so the bound names the space."""
    assert flow_retention(org, space, flow, step) == expected


def test_a_flow_or_a_step_may_choose_its_cap_but_nothing_longer():
    """A write is to be checked against the levels outside the one written;
    this test shows what `admits` gives for those periods. The write path that
    will use it is built later.
    Mutants: a period equal to the cap is refused; a longer one is admitted;
    the flow is not a cap, so a step may choose up to the space's period."""
    outside_a_step = flow_retention(None, 30, 7)
    assert admits(outside_a_step, 7, stricter=fewer_days)
    assert admits(outside_a_step, 1, stricter=fewer_days)
    assert admits(outside_a_step, None, stricter=fewer_days)
    assert not admits(outside_a_step, 8, stricter=fewer_days)

    outside_a_flow = flow_retention(None, 30)
    assert admits(outside_a_flow, 30, stricter=fewer_days)
    assert not admits(outside_a_flow, 31, stricter=fewer_days)


def test_the_organization_is_a_default_a_space_inherits_not_a_cap():
    """Organisation 30 and space 60 give 60, also for what is inside the space.
    Mutant: the organisation caps, so a space cannot choose a longer period
    than its organisation's default."""
    assert flow_retention(30, 60) == Resolved(60, SPACE, 60, SPACE)
    assert flow_retention(30, 60, None, 45) == Resolved(45, STEP, 60, SPACE)
    assert admits(flow_retention(30), 60, stricter=fewer_days)


def test_a_space_that_inherits_its_organizations_period_caps_from_the_organization():
    """The cap a refused write is to report comes from the level that chose
    it; `resolve` names the organisation as the bound's origin here. The write
    path that will report it is built later.
    Mutant: the bound names the space that only inherits, so a client sends the
    administrator to a space setting that is empty."""
    outside_a_flow = flow_retention(30, None)
    assert (outside_a_flow.bound, outside_a_flow.bound_origin) == (30, ORG)
    assert not admits(outside_a_flow, 31, stricter=fewer_days)
    assert flow_retention(30, None, 90) == Resolved(30, ORG, 30, ORG)


def test_a_lowered_cap_applies_over_a_longer_period_stored_inside_it():
    """The space goes down to 5 after the flow stored 7 and a step 6. A save
    is to check only the periods it writes, so the stored periods stay; this
    test shows what `resolve` gives: the shorter cap over the longer stored
    periods. The write path is built later.
    Mutants: the stored period still applies; a stored step that is shorter
    than the new cap is lifted to it."""
    assert flow_retention(None, 5, 7) == Resolved(5, SPACE, 5, SPACE)
    assert flow_retention(None, 5, 7, 6) == Resolved(5, SPACE, 5, SPACE)
    assert flow_retention(None, 5, 7, 1) == Resolved(1, STEP, 5, SPACE)
