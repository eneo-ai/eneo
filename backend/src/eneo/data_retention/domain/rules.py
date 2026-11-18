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


@dataclass(frozen=True, slots=True)
class RuleTask:
    """Removed by the registered task `task`, by the period chosen on `levels`
    (outermost first); a bounding level caps every level inside it."""

    task: str
    levels: tuple[PolicyLevel, ...]
    bounding: frozenset[PolicyLevel] = frozenset()


@dataclass(frozen=True, slots=True)
class RuleExemption:
    """Declared, and removed by no registered task, for this reason."""

    reason: str


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
    }
)


def rule_task(rule: RetentionRule) -> RuleTask:
    disposition = RETENTION_RULES[rule]
    if not isinstance(disposition, RuleTask):
        raise ValueError(f"No registered task removes {rule.value}.")
    return disposition


def fewer_days(candidate: int, current: int) -> bool:
    return candidate < current


def resolve_period(
    rule: RetentionRule, chosen: Mapping[PolicyLevel, int | None]
) -> Resolved[int]:
    """The period in days that applies, and the level that chose it."""
    task = rule_task(rule)
    return resolve(
        [LevelSetting(level, chosen.get(level)) for level in task.levels],
        stricter=fewer_days,
        bounding=task.bounding,
    )
