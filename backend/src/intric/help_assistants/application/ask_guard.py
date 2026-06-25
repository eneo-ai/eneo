"""Defense-in-depth guard for ``assistant_service.ask``.

PRD §6 calls out a "separate service" because the regular ``ask`` path
must never run a Help Assistant. Routing alone is not enough — a stale
client, an API-key holder, or a future refactor could still target a
helper through ``POST /assistants/{id}/sessions[/{session_id}]/``. This
guard short-circuits those calls before any session row is created.

A helper assistant is identified two ways:

* **Active.** Has a current row in ``org_space_assistant_roles`` (the
  admin has assigned it to a Help Assistant slot — :pep:`8` PRD §3).
* **Former.** Has any row in ``help_assistant_assignment_history`` —
  either ``assistant_id`` (it was the previous helper for a slot) or
  ``replaced_by_assistant_id`` (it replaced an earlier helper at some
  point). Even after an admin unassigns the role, the assistant has
  been a helper, so we keep the door closed.

Legitimate Help Assistant invocations flow through
:class:`intric.help_assistants.application.helper_run_service.HelperRunService`
and the dedicated router (step 022).
"""

from __future__ import annotations

from uuid import UUID

from intric.help_assistants.infrastructure.help_assistant_assignment_history_repo import (  # noqa: E501
    HelpAssistantAssignmentHistoryRepo,
)
from intric.help_assistants.infrastructure.org_space_assistant_role_repo import (
    OrgSpaceAssistantRoleRepo,
)
from intric.main.exceptions import UnauthorizedException


async def assert_not_helper_assistant(
    assistant_id: UUID,
    role_repo: OrgSpaceAssistantRoleRepo,
    history_repo: HelpAssistantAssignmentHistoryRepo,
) -> None:
    """Raise ``UnauthorizedException`` (HTTP 403) if ``assistant_id`` is a
    Help Assistant — either currently assigned or ever assigned before.
    """
    if await role_repo.exists_active_for_assistant(assistant_id):
        raise UnauthorizedException(
            "This assistant is a helper and cannot be asked via the normal endpoint.",
            code="forbidden_action",
            context={
                "resource_type": "assistant",
                "action": "ask",
                "auth_layer": "helper_assistant_guard",
                "helper_state": "active",
            },
        )

    if await history_repo.exists_for_assistant(assistant_id):
        raise UnauthorizedException(
            "This assistant is a former helper and cannot be asked.",
            code="forbidden_action",
            context={
                "resource_type": "assistant",
                "action": "ask",
                "auth_layer": "helper_assistant_guard",
                "helper_state": "former",
            },
        )
