"""The composition root supplies explicit task instances and execution policy."""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_runner import RetentionTask
from eneo.data_retention.domain.retention import RetentionBudget


@dataclass(frozen=True, slots=True)
class RetentionTaskRegistration:
    name: str
    enabled: bool
    budget: RetentionBudget
    build: Callable[[AsyncSession], RetentionTask]
