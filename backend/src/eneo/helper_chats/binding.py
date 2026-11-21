from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class HelperChatBinding:
    """The helper chat a hidden assistant's turn answers in: what it helps
    with and whether the turn runs in edit mode
    (``helper_chat_service.turn_in_edit_mode``)."""

    target_type: str
    target_id: UUID
    editing: bool
