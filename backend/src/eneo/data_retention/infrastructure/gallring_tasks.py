"""The registered gallring tasks (a code list), in run order."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.gallring_runner import GallringTask
from eneo.main.config import Settings


@dataclass(frozen=True, slots=True)
class GallringTaskRegistration:
    name: str
    enabled: Callable[[Settings], bool]
    build: Callable[[AsyncSession], GallringTask]


# The registered tasks, in run order; each owning area adds its own.
GALLRING_TASKS: tuple[GallringTaskRegistration, ...] = ()


def enabled_gallring_tasks(settings: Settings) -> tuple[str, ...]:
    return tuple(task.name for task in GALLRING_TASKS if task.enabled(settings))


def disabled_gallring_tasks(settings: Settings) -> tuple[str, ...]:
    """Tasks the deployment's emergency switch turns off."""
    return tuple(task.name for task in GALLRING_TASKS if not task.enabled(settings))
