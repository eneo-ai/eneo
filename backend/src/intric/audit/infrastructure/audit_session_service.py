"""
Service for managing audit access sessions using Redis.

Audit access sessions store justification data server-side to prevent
sensitive information from appearing in URLs, browser history, or server logs.
"""

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

import redis.exceptions
from fastapi import HTTPException

from intric.worker.redis import get_redis

logger = logging.getLogger(__name__)


class AuditSessionService:
    """Manages audit access sessions in Redis with automatic expiration."""

    def __init__(self):
        self.redis = get_redis()
        self.ttl_seconds = 3600  # 1 hour session lifetime

    async def create_session(
        self,
        user_id: UUID,
        tenant_id: UUID,
        category: str,
        description: str,
    ) -> str:
        """
        Create a new audit access session.

        Args:
            user_id: The user requesting audit access
            tenant_id: The tenant the user belongs to
            category: Justification category (e.g., "investigation", "compliance")
            description: Detailed reason for accessing audit logs (10-500 chars)

        Returns:
            session_id: UUID string to be stored in HTTP-only cookie

        Raises:
            HTTPException: 503 Service Unavailable if Redis is down

        Note:
            Session data is stored in Redis with automatic 1-hour expiration.
            Data is stored as plaintext JSON within the trusted Redis boundary,
            consistent with other session/cache data in the system.
        """
        session_id = str(uuid4())
        session_data = {
            "user_id": str(user_id),
            "tenant_id": str(tenant_id),
            "category": category,
            "description": description,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # Store in Redis with automatic expiration
            await self.redis.setex(
                f"audit_session:{session_id}",
                self.ttl_seconds,
                json.dumps(session_data),
            )
        except redis.exceptions.RedisError as e:
            logger.error(f"Redis error creating audit session: {e}", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="Audit session service temporarily unavailable. Please try again."
            )

        return session_id

    async def get_session(self, session_id: str) -> Optional[dict]:
        """
        Retrieve session data from Redis.

        Args:
            session_id: The session UUID

        Returns:
            Session data dict or None if session doesn't exist or expired

        Raises:
            HTTPException: 503 Service Unavailable if Redis is down
        """
        try:
            data = await self.redis.get(f"audit_session:{session_id}")
            if not data:
                return None

            return json.loads(data.decode("utf-8"))
        except redis.exceptions.RedisError as e:
            logger.error(f"Redis error retrieving audit session: {e}", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="Audit session service temporarily unavailable. Please try again."
            )

    async def validate_session(
        self, session_id: str, user_id: UUID, tenant_id: UUID
    ) -> Optional[dict]:
        """
        Validate that session belongs to the specified user and tenant.

        Args:
            session_id: The session UUID
            user_id: Expected user ID
            tenant_id: Expected tenant ID

        Returns:
            Session data if valid, None otherwise

        Security:
            Ensures tenant isolation and prevents session hijacking by
            validating both user_id and tenant_id match the session.
            Uses constant-time comparison to prevent timing attacks.
        """
        session = await self.get_session(session_id)
        if not session:
            return None

        # Verify user owns this session (constant-time comparison for defense-in-depth)
        if not secrets.compare_digest(session["user_id"], str(user_id)):
            return None

        # Verify tenant isolation (constant-time comparison for defense-in-depth)
        if not secrets.compare_digest(session["tenant_id"], str(tenant_id)):
            return None

        return session

    async def revoke_session(self, session_id: str) -> None:
        """
        Immediately invalidate a session.

        Args:
            session_id: The session UUID to revoke

        Raises:
            HTTPException: 503 Service Unavailable if Redis is down

        Use case:
            Manual logout, security incident response, compliance requirements
        """
        try:
            await self.redis.delete(f"audit_session:{session_id}")
        except redis.exceptions.RedisError as e:
            logger.error(f"Redis error revoking audit session: {e}", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="Audit session service temporarily unavailable. Please try again."
            )

    async def extend_session(self, session_id: str) -> bool:
        """
        Extend session TTL by another hour.

        Args:
            session_id: The session UUID

        Returns:
            True if session was extended, False if session doesn't exist

        Raises:
            HTTPException: 503 Service Unavailable if Redis is down

        Note:
            Can be called on each audit log access to keep active sessions alive.
            Uses atomic EXPIRE operation to avoid race conditions.
        """
        try:
            key = f"audit_session:{session_id}"
            # EXPIRE returns 1 if key exists and was updated, 0 if key doesn't exist
            # This is atomic and avoids the race condition of exists-then-expire
            result = await self.redis.expire(key, self.ttl_seconds)
            return bool(result)
        except redis.exceptions.RedisError as e:
            logger.error(f"Redis error extending audit session: {e}", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="Audit session service temporarily unavailable. Please try again."
            )
