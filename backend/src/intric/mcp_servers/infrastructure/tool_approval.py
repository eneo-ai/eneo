"""Tool approval manager for human-in-the-loop tool execution."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from time import monotonic
from typing import Any, Literal, Optional
from uuid import UUID

import redis.asyncio as aioredis
from pydantic import BaseModel, Field, field_validator, model_validator

from intric.main.config import get_settings
from intric.main.logging import get_logger

logger = get_logger(__name__)

_settings = get_settings()
APPROVAL_TTL_SECONDS = _settings.mcp_tool_approval_ttl_seconds
APPROVAL_TIMEOUT_SECONDS = float(_settings.mcp_tool_approval_timeout_seconds)
MAX_DENIAL_REASON_LENGTH = _settings.mcp_tool_approval_denial_reason_max_length
CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
MARKUP_RE = re.compile(r"[`*_<>{}\[\]]")


class ToolApprovalDecision(BaseModel):
    """Decision for a single tool call."""

    tool_call_id: str
    approved: bool
    reason: Optional[str] = Field(default=None, max_length=MAX_DENIAL_REASON_LENGTH)

    @field_validator("reason")
    @classmethod
    def _sanitize_reason(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = CONTROL_CHAR_RE.sub("", value).strip()
        text = MARKUP_RE.sub("", text)
        return text[:MAX_DENIAL_REASON_LENGTH]

    @model_validator(mode="after")
    def _validate_reason(self) -> "ToolApprovalDecision":
        if self.approved and self.reason is not None:
            raise ValueError("reason is only allowed when approved=false")
        return self


class ToolApprovalRequest(BaseModel):
    """Pending approval request with tools waiting for user decision."""

    approval_id: str
    tool_call_ids: list[str]


class ToolApprovalWaitResult(BaseModel):
    """Result returned to the streaming coroutine waiting for approval."""

    decisions: list[ToolApprovalDecision]
    timed_out: bool = False
    cancelled: bool = False


class ToolApprovalSubmitResult(BaseModel):
    """Result returned by submit_decision to the API endpoint."""

    status: Literal["accepted", "not_found", "forbidden", "conflict"]
    response_status: Optional[Literal["accepted", "already_processed"]] = None
    decisions_received: int = 0
    decisions_remaining: int = 0
    unrecognized_tool_call_ids: list[str] = []
    existing_status: Optional[str] = None


class ToolApprovalContext(BaseModel):
    """Actor/scope context for a pending approval request."""

    approval_id: str
    tenant_id: UUID
    user_id: UUID
    session_id: UUID
    assistant_id: UUID | None = None


class ToolApprovalContextLookupResult(BaseModel):
    """Result returned by get_approval_context()."""

    status: Literal["ok", "not_found", "forbidden"]
    context: ToolApprovalContext | None = None


@dataclass
class _ApprovalActorContext:
    tenant_id: str
    user_id: str
    session_id: str
    assistant_id: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "assistant_id": self.assistant_id,
        }


class ToolApprovalManager:
    """Manages pending tool approvals across streaming requests."""

    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self._redis = redis_client
        self._pending_events: dict[str, asyncio.Event] = {}
        self._memory_state: dict[str, dict[str, Any]] = {}
        self._cancelled_results: dict[str, ToolApprovalWaitResult] = {}
        self._namespace = f"intric:{get_settings().environment}:mcp:approval"

    def _key(self, approval_id: str) -> str:
        return f"{self._namespace}:{approval_id}"

    async def _save_state(self, approval_id: str, payload: dict[str, Any]) -> None:
        if self._redis is None:
            self._memory_state[approval_id] = payload
            return

        await self._redis.set(
            self._key(approval_id),
            json.dumps(payload),
            ex=APPROVAL_TTL_SECONDS,
        )

    async def _load_state(self, approval_id: str) -> Optional[dict[str, Any]]:
        if self._redis is None:
            return self._memory_state.get(approval_id)

        raw = await self._redis.get(self._key(approval_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    async def _delete_state(self, approval_id: str) -> None:
        if self._redis is None:
            self._memory_state.pop(approval_id, None)
            return

        await self._redis.delete(self._key(approval_id))

    @staticmethod
    def _context_matches(
        payload: dict[str, Any],
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> bool:
        context = payload.get("context", {})
        return context.get("tenant_id") == str(tenant_id) and context.get("user_id") == str(
            user_id
        )

    @staticmethod
    def _build_decisions(
        payload: dict[str, Any],
    ) -> list[ToolApprovalDecision]:
        decisions = payload.get("decisions", {})
        tool_call_ids = payload.get("tool_call_ids", [])
        out: list[ToolApprovalDecision] = []
        for tool_call_id in tool_call_ids:
            decision = decisions.get(tool_call_id, {"approved": False, "reason": None})
            out.append(
                ToolApprovalDecision(
                    tool_call_id=tool_call_id,
                    approved=bool(decision.get("approved", False)),
                    reason=decision.get("reason"),
                )
            )
        return out

    @staticmethod
    def _finalize_payload(
        payload: dict[str, Any],
        *,
        final_status: str,
    ) -> dict[str, Any]:
        payload["finalized"] = True
        payload["final_status"] = final_status
        return payload

    @staticmethod
    def _all_decided(payload: dict[str, Any]) -> bool:
        required = set(payload.get("tool_call_ids", []))
        decided = set(payload.get("decisions", {}).keys())
        return required <= decided

    async def request_approval(
        self,
        approval_id: str,
        tool_call_ids: list[str],
        tenant_id: UUID,
        user_id: UUID,
        session_id: UUID,
        assistant_id: UUID | None = None,
    ) -> None:
        """Register a new pending approval request."""
        self._pending_events[approval_id] = asyncio.Event()

        context = _ApprovalActorContext(
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            session_id=str(session_id),
            assistant_id=str(assistant_id) if assistant_id is not None else None,
        )
        payload: dict[str, Any] = {
            "approval_id": approval_id,
            "tool_call_ids": tool_call_ids,
            "context": context.to_dict(),
            "decisions": {},
            "finalized": False,
            "final_status": None,
        }
        await self._save_state(approval_id, payload)

    async def wait_for_approval(
        self,
        approval_id: str,
        timeout: float | None = None,
        poll_interval: float = 0.25,
    ) -> ToolApprovalWaitResult:
        """
        Block until user submits approval decisions or timeout occurs.

        On timeout, all tool calls are denied and a timeout result is returned.
        """
        effective_timeout = APPROVAL_TIMEOUT_SECONDS if timeout is None else timeout

        event = self._pending_events.get(approval_id)
        if event is None:
            event = asyncio.Event()
            self._pending_events[approval_id] = event

        started = monotonic()

        try:
            while True:
                if approval_id in self._cancelled_results:
                    return self._cancelled_results[approval_id]

                payload = await self._load_state(approval_id)
                if payload is None:
                    if approval_id in self._cancelled_results:
                        return self._cancelled_results[approval_id]
                    raise ValueError(f"No pending approval request for {approval_id}")

                if payload.get("finalized") or self._all_decided(payload):
                    return ToolApprovalWaitResult(
                        decisions=self._build_decisions(payload),
                        timed_out=payload.get("final_status") == "timeout",
                        cancelled=payload.get("final_status") == "cancelled",
                    )

                elapsed = monotonic() - started
                if elapsed >= effective_timeout:
                    decisions = payload.setdefault("decisions", {})
                    for tool_call_id in payload.get("tool_call_ids", []):
                        decisions.setdefault(
                            tool_call_id,
                            {"approved": False, "reason": "timeout"},
                        )
                    payload = self._finalize_payload(payload, final_status="timeout")
                    await self._save_state(approval_id, payload)
                    return ToolApprovalWaitResult(
                        decisions=self._build_decisions(payload),
                        timed_out=True,
                    )

                wait_timeout = min(poll_interval, effective_timeout - elapsed)
                try:
                    await asyncio.wait_for(event.wait(), timeout=wait_timeout)
                    event.clear()
                except asyncio.TimeoutError:
                    continue
        finally:
            self._pending_events.pop(approval_id, None)
            self._cancelled_results.pop(approval_id, None)
            await self._delete_state(approval_id)

    async def submit_decision(
        self,
        approval_id: str,
        decisions: list[ToolApprovalDecision],
        actor_tenant_id: UUID,
        actor_user_id: UUID,
    ) -> ToolApprovalSubmitResult:
        """
        Submit user's approval/rejection decisions.

        Supports incremental submissions and idempotent retries.
        """
        payload = await self._load_state(approval_id)
        if payload is None:
            return ToolApprovalSubmitResult(status="not_found")

        if not self._context_matches(
            payload, tenant_id=actor_tenant_id, user_id=actor_user_id
        ):
            return ToolApprovalSubmitResult(status="forbidden")

        required_tool_ids = set(payload.get("tool_call_ids", []))
        normalized_incoming: dict[str, ToolApprovalDecision] = {}
        unrecognized: list[str] = []
        for decision in decisions:
            if decision.tool_call_id not in required_tool_ids:
                unrecognized.append(decision.tool_call_id)
                continue
            normalized_incoming[decision.tool_call_id] = decision

        existing_decisions: dict[str, dict[str, Any]] = payload.setdefault("decisions", {})

        if payload.get("finalized"):
            conflict = False
            for tool_call_id, incoming in normalized_incoming.items():
                existing = existing_decisions.get(tool_call_id, {})
                if bool(existing.get("approved", False)) != incoming.approved:
                    conflict = True
                    break
                if (existing.get("reason") or None) != incoming.reason:
                    conflict = True
                    break

            if conflict:
                return ToolApprovalSubmitResult(
                    status="conflict",
                    existing_status=payload.get("final_status") or "processed",
                )

            return ToolApprovalSubmitResult(
                status="accepted",
                response_status="already_processed",
                decisions_received=len(existing_decisions),
                decisions_remaining=max(0, len(required_tool_ids) - len(existing_decisions)),
                unrecognized_tool_call_ids=unrecognized,
            )

        for tool_call_id, decision in normalized_incoming.items():
            existing_decisions[tool_call_id] = {
                "approved": decision.approved,
                "reason": decision.reason if not decision.approved else None,
            }

        if self._all_decided(payload):
            payload = self._finalize_payload(payload, final_status="accepted")

        await self._save_state(approval_id, payload)

        event = self._pending_events.get(approval_id)
        if event is not None:
            event.set()

        return ToolApprovalSubmitResult(
            status="accepted",
            response_status="accepted",
            decisions_received=len(existing_decisions),
            decisions_remaining=max(0, len(required_tool_ids) - len(existing_decisions)),
            unrecognized_tool_call_ids=unrecognized,
        )

    async def get_approval_context(
        self,
        approval_id: str,
        actor_tenant_id: UUID,
        actor_user_id: UUID,
    ) -> ToolApprovalContextLookupResult:
        """Get approval context for a validated actor."""
        payload = await self._load_state(approval_id)
        if payload is None:
            return ToolApprovalContextLookupResult(status="not_found")

        if not self._context_matches(
            payload,
            tenant_id=actor_tenant_id,
            user_id=actor_user_id,
        ):
            return ToolApprovalContextLookupResult(status="forbidden")

        try:
            context_data = payload.get("context", {})
            context = ToolApprovalContext(
                approval_id=approval_id,
                tenant_id=UUID(str(context_data["tenant_id"])),
                user_id=UUID(str(context_data["user_id"])),
                session_id=UUID(str(context_data["session_id"])),
                assistant_id=(
                    UUID(str(context_data["assistant_id"]))
                    if context_data.get("assistant_id")
                    else None
                ),
            )
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            logger.warning(
                "Malformed approval context payload",
                extra={"approval_id": approval_id, "error_type": type(exc).__name__},
                exc_info=True,
            )
            return ToolApprovalContextLookupResult(status="not_found")

        return ToolApprovalContextLookupResult(status="ok", context=context)

    async def cancel_approval(self, approval_id: str) -> bool:
        """
        Cancel a pending approval request.

        Used on stream disconnect. Produces a local denied result and releases
        backing Redis state immediately.
        """
        payload = await self._load_state(approval_id)
        if payload is None:
            return False

        decisions = payload.setdefault("decisions", {})
        for tool_call_id in payload.get("tool_call_ids", []):
            decisions.setdefault(
                tool_call_id, {"approved": False, "reason": "cancelled"}
            )
        payload = self._finalize_payload(payload, final_status="cancelled")

        self._cancelled_results[approval_id] = ToolApprovalWaitResult(
            decisions=self._build_decisions(payload),
            cancelled=True,
        )

        event = self._pending_events.get(approval_id)
        if event is not None:
            event.set()

        await self._delete_state(approval_id)
        return True

    def get_pending_count(self) -> int:
        """Return the number of pending approval requests in this process."""
        return len(self._pending_events)


# Global singleton instance
_approval_manager: Optional[ToolApprovalManager] = None


def get_approval_manager(
    redis_client: Optional[aioredis.Redis] = None,
) -> ToolApprovalManager:
    """Get the global approval manager instance."""
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ToolApprovalManager(redis_client=redis_client)
    elif redis_client is not None and _approval_manager._redis is None:
        _approval_manager._redis = redis_client
    return _approval_manager
