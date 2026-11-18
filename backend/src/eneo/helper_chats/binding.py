from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class HelperChatBinding:
    """The helper chat a hidden assistant's turn answers in: what it helps
    with and whether it is in edit mode."""

    target_type: str
    target_id: UUID
    editing: bool
