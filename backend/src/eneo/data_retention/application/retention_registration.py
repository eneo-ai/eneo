"""The composition root supplies explicit task instances and execution policy."""

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_runner import RetentionTask
from eneo.data_retention.domain.retention import RetentionBudget
from eneo.data_retention.domain.rules import RuleExemption, RuleTask


@dataclass(frozen=True, slots=True)
class RetentionTaskRegistration:
    name: str
    enabled: bool
    budget: RetentionBudget
    build: Callable[[AsyncSession], RetentionTask]
    limited_by: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict[str, tuple[str, ...]]
    )
    """A blocked reason, without its step, mapped to the deployment settings
    whose limits can keep a root for that reason."""


def retention_registration_violations(
    *,
    vocabulary: Iterable[str],
    rules: Mapping[str, RuleTask | RuleExemption],
    registered: Iterable[str],
    existing_without_choice: Mapping[str, str],
    follows_a_removal: Mapping[str, str],
    settings: Collection[str],
) -> list[str]:
    """Every way the declared removals and the registered tasks disagree.

    Each rule has a task or an exemption; each registered task removes a rule's
    roots or is listed, with a setting that switches it off, among the removals
    that run without a choice or those that follow a removal already made.
    Empty when the declaration is complete.
    """
    rule_names = set(vocabulary)
    declared = set(rules)
    tasks = set(registered)
    rule_tasks = {
        disposition.task
        for disposition in rules.values()
        if isinstance(disposition, RuleTask)
    }
    without_choice = set(existing_without_choice)
    following = set(follows_a_removal)
    listed = without_choice | following
    switches = {**existing_without_choice, **follows_a_removal}
    return [
        *(
            f"Rule {rule} has no task or exemption."
            for rule in sorted(rule_names - declared)
        ),
        *(
            f"{rule} has a disposition but is not a rule."
            for rule in sorted(declared - rule_names)
        ),
        *(
            f"Task {task} removes a rule's roots but is not registered."
            for task in sorted(rule_tasks - tasks)
        ),
        *(
            f"Task {task} removes without a rule and is not listed with a switch."
            for task in sorted(tasks - rule_tasks - listed)
        ),
        *(
            f"Task {task} is listed but not registered."
            for task in sorted(listed - tasks)
        ),
        *(
            f"Task {task} removes a rule's roots and is also listed as running "
            "without a choice."
            for task in sorted(rule_tasks & listed)
        ),
        *(
            f"Task {task} is listed both as existing and as following a removal."
            for task in sorted(without_choice & following)
        ),
        *(
            f"The switch {switch} of {task} is not a setting."
            for task, switch in sorted(switches.items())
            if switch not in settings
        ),
    ]
