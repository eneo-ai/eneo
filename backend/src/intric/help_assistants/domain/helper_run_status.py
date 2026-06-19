"""Status enum for a single Help-Assistant run.

Mirrors the ``status`` column on ``help_assistant_runs`` (``VARCHAR(20)``,
server default ``'in_progress'``). Terminal statuses (COMPLETED, ABANDONED,
FAILED) accompany a non-NULL ``completed_at``; ``IN_PROGRESS`` leaves it
NULL.
"""

from enum import Enum


class HelperRunStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    FAILED = "failed"
