"""The levels at which a policy is chosen, and how a chain of choices resolves.

Pure and shared by every domain that lets an organisation, a space or an
Assistant choose a policy. A domain supplies what "stricter" means for its
values and which levels bound the levels inside them; authorization to write,
confirmation, persistence and SQL stay with the domain. Retention passes
"fewer days" with no bounding level, so the nearest choice wins. A
requirement passes "required" with every level bounding, which makes the
levels an OR that an inner level can raise but never lower.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

T = TypeVar("T")


class PolicyLevel(StrEnum):
    """Where a value is chosen. The strings are released API and audit values."""

    INSTALLATION = "installation"
    ORGANIZATION = "organization"
    SPACE = "space"
    ASSISTANT_OR_APP = "assistant_or_app"
    FLOW = "flow"


@dataclass(frozen=True, slots=True)
class LevelSetting(Generic[T]):
    level: PolicyLevel
    # None: nothing is chosen at this level. Any other value, False included,
    # is a choice.
    value: T | None


@dataclass(frozen=True, slots=True)
class Resolved(Generic[T]):
    # None: nothing is chosen anywhere in the chain.
    value: T | None
    origin: PolicyLevel | None
    # The strictest value chosen on a bounding level, and the outermost level
    # that chose it: the level an inner choice cannot loosen.
    bound: T | None
    bound_origin: PolicyLevel | None


def resolve(
    chain: Sequence[LevelSetting[T]],
    *,
    stricter: Callable[[T, T], bool],
    bounding: frozenset[PolicyLevel] = frozenset(),
) -> Resolved[T]:
    """Resolve a chain ordered from the outermost level to the innermost.

    The nearest chosen value is inherited. A value chosen on a bounding level
    is a bound that no inner value loosens, so the result is the stricter of
    the nearest value and the bound. On a tie the nearest level is the origin.
    """
    levels = [setting.level for setting in chain]
    if len(set(levels)) != len(levels):
        raise ValueError(f"A level appears more than once in {levels}.")

    nearest: tuple[PolicyLevel, T] | None = None
    bound: tuple[PolicyLevel, T] | None = None
    for setting in chain:
        if setting.value is None:
            continue
        nearest = (setting.level, setting.value)
        if setting.level in bounding and (
            bound is None or stricter(setting.value, bound[1])
        ):
            bound = nearest

    if nearest is None:
        return Resolved(None, None, None, None)
    if bound is None:
        return Resolved(nearest[1], nearest[0], None, None)
    level, value = bound if stricter(bound[1], nearest[1]) else nearest
    return Resolved(value, level, bound[1], bound[0])


def admits(
    parent: Resolved[T], proposed: T | None, *, stricter: Callable[[T, T], bool]
) -> bool:
    """Whether a level may choose `proposed` below `parent`, the resolution of
    the levels outside it: inheriting (None) or anything at least as strict as
    the parent's bound."""
    if proposed is None or parent.bound is None:
        return True
    return not stricter(parent.bound, proposed)
