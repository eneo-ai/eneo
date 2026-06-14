"""Reason enum for role-assignment history rows.

Mirrors the ``reason`` column on ``help_assistant_assignment_history``
(``VARCHAR(50)``). A history row is appended whenever the assistant
filling a role slot is reset to the shipped default, reassigned to a
different assistant, or unassigned entirely.
"""

from enum import Enum


class AssignmentHistoryReason(str, Enum):
    RESET_TO_DEFAULT = "reset_to_default"
    REASSIGNED = "reassigned"
    UNASSIGNED = "unassigned"
