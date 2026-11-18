"""Refusals shared by every caller that reads or changes an assistant by id."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException

from eneo.assistants.assistant import AssistantOrigin
from eneo.main.exceptions import NotFoundException

if TYPE_CHECKING:
    from eneo.assistants.assistant import Assistant
    from eneo.main.container.container import Container


def raise_if_flow_managed(assistant: Assistant, assistant_id: UUID) -> None:
    """A flow-managed assistant is changed only through its flow."""
    if assistant.origin == AssistantOrigin.FLOW_MANAGED:
        flow_id = assistant.managing_flow_id
        message = (
            "This assistant is flow-managed and must be modified through "
            f"/api/v1/flows/{flow_id}/assistants/{assistant_id}/"
            if flow_id is not None
            else "This assistant is flow-managed and must be modified through flow endpoints."
        )
        raise HTTPException(
            status_code=400,
            detail={
                "code": "flow_managed_assistant",
                "message": message,
                "context": {
                    "assistant_id": str(assistant_id),
                    "flow_id": str(flow_id) if flow_id is not None else None,
                },
            },
        )


async def raise_if_helper_chat(
    container: Container, assistant_id: UUID, *, owner_may_read: bool = False
) -> None:
    """A helper chat's assistant is configured only through its chat. Here it
    answers as an assistant that does not exist, so another person does not
    learn of it either. With ``owner_may_read`` the chat's own person reads
    it, as the chat panel does."""
    owner_id = await container.assistant_service().helper_chat_owner_id(assistant_id)
    if owner_id is None or (owner_may_read and owner_id == container.user().id):
        return
    raise NotFoundException()
