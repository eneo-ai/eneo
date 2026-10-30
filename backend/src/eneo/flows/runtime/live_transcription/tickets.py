"""Single-use tickets that hand an admitted live session to its WebSocket.

The HTTP route admits the session on the normal flows stack (authentication,
route guards, permission checks, audit) and issues a ticket; the WebSocket
only redeems it. Tickets live 30 seconds, are consumed atomically with GETDEL,
and Redis stores only their digest, the pattern module-login tickets use.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Final
from uuid import UUID

import redis.asyncio as aioredis

LIVE_TRANSCRIPTION_TICKET_TTL_SECONDS: Final = 30
_KEY_PREFIX: Final = "flow_live_transcription_ticket:"


@dataclass(frozen=True)
class LiveTranscriptionGrant:
    """What an admitted session may do; the WebSocket trusts nothing else."""

    tenant_id: UUID
    user_id: UUID
    flow_id: UUID
    flow_version: int
    step_id: UUID
    model_id: UUID
    max_seconds: int
    recording_id: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                key: str(value) if isinstance(value, UUID) else value
                for key, value in asdict(self).items()
            }
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> LiveTranscriptionGrant:
        data = json.loads(raw)
        return cls(
            tenant_id=UUID(data["tenant_id"]),
            user_id=UUID(data["user_id"]),
            flow_id=UUID(data["flow_id"]),
            flow_version=int(data["flow_version"]),
            step_id=UUID(data["step_id"]),
            model_id=UUID(data["model_id"]),
            max_seconds=int(data["max_seconds"]),
            recording_id=data.get("recording_id"),
        )


def _redis_key(ticket: str) -> str:
    return _KEY_PREFIX + hashlib.sha256(ticket.encode()).hexdigest()


class LiveTranscriptionTicketStore:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    async def issue(self, grant: LiveTranscriptionGrant) -> tuple[str, datetime]:
        ticket = secrets.token_urlsafe(32)
        await self._redis.setex(
            _redis_key(ticket), LIVE_TRANSCRIPTION_TICKET_TTL_SECONDS, grant.to_json()
        )
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=LIVE_TRANSCRIPTION_TICKET_TTL_SECONDS
        )
        return ticket, expires_at

    async def redeem(self, ticket: str) -> LiveTranscriptionGrant | None:
        raw = await self._redis.getdel(_redis_key(ticket))
        return None if raw is None else LiveTranscriptionGrant.from_json(raw)
