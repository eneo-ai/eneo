"""Helper-assistant kind enum.

Canonical home for ``HelperKind``. Other modules (defaults registry, repos,
services, API models) import from here. The defaults registry re-exports the
same symbol so existing import sites keep working.

A new kind is added by:

1. extending this enum, and
2. registering a ``HelperAssistantTemplate`` for it in
   ``eneo.help_assistants.templates``.

The string value must match the column value used in the migrations
(``org_space_assistant_roles.kind``, ``help_assistant_assignment_history.kind``,
``help_assistant_runs.kind`` — all ``VARCHAR(50)``).
"""

from enum import Enum


class HelperKind(str, Enum):
    """Kinds of Help Assistants shipped with Eneo."""

    PROMPT_GUIDE = "prompt_guide"
