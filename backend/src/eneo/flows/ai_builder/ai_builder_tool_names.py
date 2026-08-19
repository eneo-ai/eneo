"""AI Builder tool names persisted on assistant/tool turns."""

from __future__ import annotations

from typing import Final

ASK_STRUCTURED_QUESTION_TOOL_NAME: Final[str] = "ask_structured_question"
DECLINE_FLOW_CHANGE_TOOL_NAME: Final[str] = "decline_flow_change"
PROPOSE_FLOW_TOOL_NAME: Final[str] = "propose_flow"

__all__ = [
    "ASK_STRUCTURED_QUESTION_TOOL_NAME",
    "DECLINE_FLOW_CHANGE_TOOL_NAME",
    "PROPOSE_FLOW_TOOL_NAME",
]
