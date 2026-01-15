"""Standardized metadata builders for audit logging.

This module provides utilities for creating consistent, well-structured metadata
for audit logs. Using these helpers ensures:
- Consistent field naming across all audit logs
- Proper handling of sensitive data
- Type safety and validation
- GDPR compliance by design

Example usage:
    from intric.audit.application.audit_metadata import AuditMetadata

    # Standard entity audit
    metadata = AuditMetadata.standard(
        actor=current_user,
        target=space,
        changes={"name": {"old": "Old Name", "new": "New Name"}}
    )

    # Multi-target operations (bulk updates, member additions)
    metadata = AuditMetadata.multi_target(
        actor=current_user,
        targets=[user1, user2, user3],
        operation="added_to_space",
        extra={"space_id": str(space.id)}
    )

Security considerations:
- Do NOT include passwords, API keys, or secrets in metadata
- Do NOT include full prompt text or user input that might contain sensitive data
- Be mindful of PII (personally identifiable information) requirements
- Use IDs instead of names where possible for data minimization
"""

from typing import Any, Optional
from uuid import UUID


class AuditMetadata:
    """Factory for standardized audit metadata structures."""

    @staticmethod
    def standard(
        actor: Any,
        target: Any,
        changes: Optional[dict] = None,
        extra: Optional[dict] = None,
        space: Optional[Any] = None,
        tenant: Optional[Any] = None,
    ) -> dict:
        """
        Create standard audit metadata with actor and target snapshots.

        This is the most common metadata pattern for audit logs. It captures:
        - WHO performed the action (actor snapshot with id, name, email)
        - WHAT was affected (target snapshot with id, name)
        - WHERE it happened (space and tenant context if available)
        - HOW it changed (optional changes dictionary)
        - Additional context (optional extra data)

        Args:
            actor: User performing the action (must have id, username, email attributes)
            target: Entity being acted upon (must have id attribute, optional name)
            changes: Dictionary of field changes for update operations, e.g.:
                     {"name": {"old": "OldName", "new": "NewName"}}
            extra: Additional context-specific metadata (use for domain-specific fields
                   like member_id, member_email, model names, URLs, etc.)
            space: Optional space object to include space context (id and name)
            tenant: Optional tenant object to include tenant context (id and name)

        Returns:
            Standardized metadata dictionary with human-readable names

        Example:
            metadata = AuditMetadata.standard(
                actor=current_user,
                target=assistant,
                changes={"name": {"old": "Assistant v1", "new": "Assistant v2"}},
                space=space,  # Includes space_id and space_name automatically
                tenant=tenant,  # Includes tenant_id and tenant_name automatically
            )
        """
        # Safe actor name: prefer username, fallback to email prefix, then "unknown"
        actor_name = (
            getattr(actor, "username", None)
            or getattr(actor, "name", None)
            or (getattr(actor, "email", "") or "").split("@")[0]
            or "unknown"
        )

        # Build target snapshot with all available context
        target_snapshot = {
            "id": str(target.id),
            "name": getattr(target, "name", getattr(target, "title", None)),
        }

        # Auto-include space_id from target if it exists
        target_space_id = getattr(target, "space_id", None)
        if target_space_id:
            target_snapshot["space_id"] = str(target_space_id)

        # Include space name if space object is provided
        if space:
            target_snapshot["space_id"] = str(space.id)
            target_snapshot["space_name"] = getattr(space, "name", None)

        # Include tenant context if provided
        if tenant:
            target_snapshot["tenant_id"] = str(tenant.id)
            target_snapshot["tenant_name"] = getattr(tenant, "name", None)

        metadata = {
            "actor": {
                "id": str(actor.id),
                "name": actor_name,
                "email": getattr(actor, "email", None),
            },
            "target": target_snapshot,
        }

        if changes:
            metadata["changes"] = changes

        if extra:
            metadata["extra"] = extra

        return metadata

    @staticmethod
    def multi_target(
        actor: Any,
        targets: list[Any],
        operation: str,
        extra: Optional[dict] = None,
    ) -> dict:
        """
        Create metadata for operations affecting multiple entities.

        Use this for bulk operations like:
        - Adding multiple users to a space
        - Deleting multiple files
        - Bulk permission updates
        - Multi-entity exports

        Args:
            actor: User performing the action
            targets: List of entities affected
            operation: Description of the operation (e.g., "added_to_space", "bulk_delete")
            extra: Additional context

        Returns:
            Metadata with multiple targets

        Example:
            metadata = AuditMetadata.multi_target(
                actor=current_user,
                targets=[user1, user2, user3],
                operation="added_to_space",
                extra={"space_id": str(space.id), "space_name": space.name}
            )
        """
        # Safe actor name: prefer username, fallback to email prefix, then "unknown"
        actor_name = (
            getattr(actor, "username", None)
            or getattr(actor, "name", None)
            or (getattr(actor, "email", "") or "").split("@")[0]
            or "unknown"
        )

        metadata = {
            "actor": {
                "id": str(actor.id),
                "name": actor_name,
                "email": getattr(actor, "email", None),
            },
            "operation": operation,
            "targets": [
                {
                    "id": str(target.id),
                    "name": getattr(target, "name", getattr(target, "title", None)),
                }
                for target in targets
            ],
            "target_count": len(targets),
        }

        if extra:
            metadata["extra"] = extra

        return metadata

    @staticmethod
    def system_action(
        description: str,
        target: Optional[Any] = None,
        affected_count: Optional[int] = None,
        extra: Optional[dict] = None,
    ) -> dict:
        """
        Create metadata for system-initiated actions.

        Use this for automated operations like:
        - Retention policy purges
        - Scheduled cleanups
        - Background migrations
        - Automated notifications

        Args:
            description: Human-readable description of the system action
            target: Optional entity affected (e.g., tenant for retention purge)
            affected_count: Number of entities affected (e.g., logs purged)
            extra: Additional context

        Returns:
            Metadata for system actions

        Example:
            metadata = AuditMetadata.system_action(
                description="Retention policy applied",
                target=tenant,
                affected_count=1250,
                extra={"retention_days": 365, "policy_id": str(policy.id)}
            )
        """
        metadata = {
            "system_action": description,
        }

        if target:
            metadata["target"] = {
                "id": str(target.id),
                "name": getattr(target, "name", getattr(target, "title", None)),
            }

        if affected_count is not None:
            metadata["affected_count"] = affected_count

        if extra:
            metadata["extra"] = extra

        return metadata

    @staticmethod
    def authentication(
        actor: Any,
        method: str,
        success: bool,
        failure_reason: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> dict:
        """
        Create metadata for authentication events.

        Use this for:
        - Login attempts
        - API key usage
        - Token generation/validation
        - Password changes
        - MFA events

        Args:
            actor: User attempting authentication
            method: Authentication method (e.g., "password", "api_key", "oauth")
            success: Whether authentication succeeded
            failure_reason: Reason for failure (if applicable)
            extra: Additional context (e.g., IP address, user agent)

        Returns:
            Metadata for authentication events

        Example:
            metadata = AuditMetadata.authentication(
                actor=user,
                method="password",
                success=False,
                failure_reason="Invalid password",
                extra={"ip_address": request.client.host, "attempts": 3}
            )
        """
        # Safe actor name: prefer username, fallback to email prefix, then "unknown"
        actor_name = (
            getattr(actor, "username", None)
            or getattr(actor, "name", None)
            or (getattr(actor, "email", "") or "").split("@")[0]
            or "unknown"
        )

        metadata = {
            "actor": {
                "id": str(actor.id),
                "name": actor_name,
                "email": getattr(actor, "email", None),
            },
            "authentication_method": method,
            "success": success,
        }

        if failure_reason:
            metadata["failure_reason"] = failure_reason

        if extra:
            metadata["extra"] = extra

        return metadata

    @staticmethod
    def minimal(
        actor_id: UUID,
        target_id: UUID,
        extra: Optional[dict] = None,
    ) -> dict:
        """
        Create minimal metadata with just IDs (data minimization).

        Use this when you need to reduce PII exposure or for high-volume operations
        where detailed snapshots are unnecessary.

        Args:
            actor_id: ID of the actor
            target_id: ID of the target entity
            extra: Additional context (use sparingly)

        Returns:
            Minimal metadata with IDs only

        Example:
            metadata = AuditMetadata.minimal(
                actor_id=user.id,
                target_id=file.id,
                extra={"size_bytes": file.size}
            )
        """
        metadata = {
            "actor": {"id": str(actor_id)},
            "target": {"id": str(target_id)},
        }

        if extra:
            metadata["extra"] = extra

        return metadata
