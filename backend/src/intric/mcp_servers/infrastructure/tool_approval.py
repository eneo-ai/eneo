"""Tool approval manager for human-in-the-loop tool execution."""

import asyncio
from typing import Optional

from pydantic import BaseModel


class ToolApprovalDecision(BaseModel):
    """Decision for a single tool call."""

    tool_call_id: str
    approved: bool


class ToolApprovalRequest(BaseModel):
    """Pending approval request with tools waiting for user decision."""

    approval_id: str
    tool_call_ids: list[str]


class ToolApprovalManager:
    """
    Manages pending tool approvals across streaming requests.

    When tool approval is required, the streaming coroutine will:
    1. Call request_approval() to register a pending approval
    2. Yield an SSE event to the frontend with the approval_id
    3. Call wait_for_approval() which blocks until user responds

    The frontend will:
    1. Display the approval UI
    2. Call the /approve-tools endpoint with decisions (can be called multiple times for partial approval)
    3. Once all tools are decided, the endpoint calls complete the request which unblocks the coroutine
    """

    def __init__(self):
        self._pending_events: dict[str, asyncio.Event] = {}
        self._decisions: dict[
            str, dict[str, ToolApprovalDecision]
        ] = {}  # approval_id -> {tool_call_id -> decision}
        self._tool_call_ids: dict[str, list[str]] = {}

    def request_approval(self, approval_id: str, tool_call_ids: list[str]) -> None:
        """
        Register a new pending approval request.

        Args:
            approval_id: Unique identifier for this approval request
            tool_call_ids: List of tool call IDs pending approval
        """
        self._pending_events[approval_id] = asyncio.Event()
        self._tool_call_ids[approval_id] = tool_call_ids
        self._decisions[approval_id] = {}  # Start with empty decisions dict

    async def wait_for_approval(
        self,
        approval_id: str,
        timeout: float = 300.0,
    ) -> list[ToolApprovalDecision]:
        """
        Block until user submits approval decisions or timeout occurs.

        Args:
            approval_id: The approval request to wait for
            timeout: Maximum time to wait in seconds (default 5 minutes)

        Returns:
            List of approval decisions for each tool call.
            On timeout, returns all tools as rejected.
        """
        event = self._pending_events.get(approval_id)
        if event is None:
            raise ValueError(f"No pending approval request for {approval_id}")

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            decisions_dict = self._decisions.get(approval_id, {})
            return list(decisions_dict.values())
        except asyncio.TimeoutError:
            # On timeout, reject all tools
            tool_call_ids = self._tool_call_ids.get(approval_id, [])
            return [
                ToolApprovalDecision(tool_call_id=tc_id, approved=False)
                for tc_id in tool_call_ids
            ]
        finally:
            self._cleanup(approval_id)

    def submit_decision(
        self,
        approval_id: str,
        decisions: list[ToolApprovalDecision],
    ) -> bool:
        """
        Submit user's approval/rejection decisions (supports partial/incremental submission).

        Called by the approval endpoint when user submits their choices.
        Can be called multiple times - once all tools have decisions, the event is triggered.

        Args:
            approval_id: The approval request ID
            decisions: List of approval decisions for one or more tool calls

        Returns:
            True if the approval was found and processed, False otherwise
        """
        event = self._pending_events.get(approval_id)
        if event is None:
            return False

        # Add/update decisions for the provided tool calls
        if approval_id not in self._decisions:
            self._decisions[approval_id] = {}

        for decision in decisions:
            self._decisions[approval_id][decision.tool_call_id] = decision

        # Check if all tools have been decided
        required_ids = set(self._tool_call_ids.get(approval_id, []))
        decided_ids = set(self._decisions[approval_id].keys())

        if required_ids <= decided_ids:
            # All tools have decisions, trigger the event
            event.set()

        return True

    def cancel_approval(self, approval_id: str) -> bool:
        """
        Cancel a pending approval request (treats all as rejected).

        Args:
            approval_id: The approval request to cancel

        Returns:
            True if the approval was found and cancelled
        """
        event = self._pending_events.get(approval_id)
        if event is None:
            return False

        # Set all tools as rejected
        tool_call_ids = self._tool_call_ids.get(approval_id, [])
        self._decisions[approval_id] = {
            tc_id: ToolApprovalDecision(tool_call_id=tc_id, approved=False)
            for tc_id in tool_call_ids
        }
        event.set()
        return True

    def _cleanup(self, approval_id: str) -> None:
        """Remove all state for an approval request."""
        self._pending_events.pop(approval_id, None)
        self._decisions.pop(approval_id, None)
        self._tool_call_ids.pop(approval_id, None)

    def get_pending_count(self) -> int:
        """Return the number of pending approval requests."""
        return len(self._pending_events)


# Global singleton instance
_approval_manager: Optional[ToolApprovalManager] = None


def get_approval_manager() -> ToolApprovalManager:
    """Get the global approval manager instance."""
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ToolApprovalManager()
    return _approval_manager
