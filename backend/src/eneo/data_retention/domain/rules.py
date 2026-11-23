"""What an organisation can choose to remove, and what removes it.

Every rule has one disposition: a registered task that removes the roots the
rule selects, by the period chosen on the rule's levels, or an exemption that
says why no task removes them. The registration check compares this
vocabulary with the registered tasks.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from eneo.policy_levels import LevelSetting, PolicyLevel, Resolved, resolve


class RetentionRule(StrEnum):
    CONVERSATION_HISTORY = "conversation_history"
    WIDGET_CONVERSATIONS = "widget_conversations"
    FLOW_RUN_HISTORY = "flow_run_history"


@dataclass(frozen=True, slots=True)
class RuleTask:
    """Removed by the registered task `task`, by the period chosen on `levels`
    (outermost first); a bounding level caps every level inside it."""

    task: str
    levels: tuple[PolicyLevel, ...]
    bounding: frozenset[PolicyLevel] = frozenset()


@dataclass(frozen=True, slots=True)
class RuleExemption:
    """Declared, and removed by no registered task, for this reason. An
    exemption that something else removes by a chosen period declares the
    levels and caps of that period, like a task."""

    reason: str
    levels: tuple[PolicyLevel, ...] = ()
    bounding: frozenset[PolicyLevel] = frozenset()


RETENTION_RULES: Mapping[str, RuleTask | RuleExemption] = MappingProxyType(
    {
        # Questions with an owner Assistant, and App runs, by their creation.
        RetentionRule.CONVERSATION_HISTORY: RuleTask(
            task="conversations.history",
            levels=(
                PolicyLevel.ORGANIZATION,
                PolicyLevel.SPACE,
                PolicyLevel.ASSISTANT_OR_APP,
            ),
        ),
        RetentionRule.WIDGET_CONVERSATIONS: RuleExemption(
            "Each widget's own nightly job removes its conversations, held to "
            "the organisation's widget policy."
        ),
        # Terminal Flow runs, by their end (or their creation). The space's
        # time is the cap; a flow may choose a shorter one. The organisation
        # is no level here: an empty space gives its flows no time, even when
        # the organisation keeps a conversation time, so no conversation
        # setting makes a run removable without a space administrator's
        # choice. A personal space has no writer for its time, so its flows in
        # practice have only the flow level; a value stored outside the API
        # caps them, as it caps conversations. Nothing removes a run
        # automatically yet.
        RetentionRule.FLOW_RUN_HISTORY: RuleExemption(
            "No task removes Flow run history; an administrator's explicit "
            "purge selects runs by this period.",
            levels=(PolicyLevel.SPACE, PolicyLevel.FLOW),
            bounding=frozenset({PolicyLevel.SPACE, PolicyLevel.FLOW}),
        ),
    }
)


def rule_task(rule: RetentionRule) -> RuleTask:
    disposition = RETENTION_RULES[rule]
    if not isinstance(disposition, RuleTask):
        raise ValueError(f"No registered task removes {rule.value}.")
    return disposition


def rule_chain(rule: RetentionRule) -> RuleTask | RuleExemption:
    """The rule's levels and caps, whether a task or an explicit action removes
    by them. Refuses a rule that declares no period."""
    disposition = RETENTION_RULES[rule]
    if not disposition.levels:
        raise ValueError(f"No period is chosen for {rule.value}.")
    return disposition


class RetentionExceedsSpaceError(Exception):
    """A period longer than the cap where it is written.

    The cap is in days. `cap_origin` is the level that chose it, also when an
    inner level inherits it: a space without its own period passes on its
    organisation's, so the origin is the organisation (`Resolved.bound_origin`).
    """

    code = "retention_exceeds_space"
    CAP_ORIGINS = frozenset(
        {PolicyLevel.ORGANIZATION, PolicyLevel.SPACE, PolicyLevel.FLOW}
    )

    def __init__(self, *, cap_days: int, cap_origin: PolicyLevel) -> None:
        if cap_origin not in self.CAP_ORIGINS:
            raise ValueError(f"No retention cap comes from {cap_origin.value}.")
        super().__init__(
            "The retention period is longer than the limit that applies here."
        )
        self.context: dict[str, object] = {
            "cap_days": cap_days,
            "cap_origin": cap_origin.value,
        }


def fewer_days(candidate: int, current: int) -> bool:
    return candidate < current


def resolve_period(
    rule: RetentionRule, chosen: Mapping[PolicyLevel, int | None]
) -> Resolved[int]:
    """The period in days that applies, and the level that chose it."""
    chain = rule_chain(rule)
    return resolve(
        [LevelSetting(level, chosen.get(level)) for level in chain.levels],
        stricter=fewer_days,
        bounding=chain.bounding,
    )
