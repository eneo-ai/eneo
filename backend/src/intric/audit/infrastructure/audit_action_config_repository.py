"""Repository for managing per-action audit logging configuration."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intric.audit.domain.action_metadata import get_all_actions
from intric.database.tables.audit_action_config_table import AuditActionConfig
from intric.main.logging import get_logger

logger = get_logger(__name__)


class AuditActionConfigRepository:
    """Repository for per-action audit logging configuration."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_actions_for_tenant(self, tenant_id: UUID) -> list[AuditActionConfig]:
        """Get all action configurations for a tenant.

        Args:
            tenant_id: The tenant ID

        Returns:
            List of AuditActionConfig objects
        """
        stmt = (
            select(AuditActionConfig)
            .where(AuditActionConfig.tenant_id == tenant_id)
            .order_by(AuditActionConfig.action)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_enabled_actions(self, tenant_id: UUID) -> set[str]:
        """Get set of enabled action types for a tenant.

        Args:
            tenant_id: The tenant ID

        Returns:
            Set of enabled action type values (e.g., {"user_created", "file_uploaded"})
        """
        stmt = (
            select(AuditActionConfig.action)
            .where(
                AuditActionConfig.tenant_id == tenant_id,
                AuditActionConfig.enabled == True  # noqa: E712
            )
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def is_action_enabled(self, tenant_id: UUID, action: str) -> bool:
        """Check if a specific action is enabled for a tenant.

        Args:
            tenant_id: The tenant ID
            action: The action type value (e.g., "user_created")

        Returns:
            True if enabled, False if disabled or not configured (defaults to True)
        """
        stmt = (
            select(AuditActionConfig.enabled)
            .where(
                AuditActionConfig.tenant_id == tenant_id,
                AuditActionConfig.action == action
            )
        )
        result = await self.session.execute(stmt)
        enabled = result.scalar_one_or_none()

        # Default to True if not configured (backward compatibility)
        return enabled if enabled is not None else True

    async def update_action(self, tenant_id: UUID, action: str, enabled: bool) -> AuditActionConfig:
        """Update or create a single action configuration.

        Args:
            tenant_id: The tenant ID
            action: The action type value
            enabled: Whether the action should be logged

        Returns:
            The updated or created AuditActionConfig
        """
        # Try to find existing config
        stmt = select(AuditActionConfig).where(
            AuditActionConfig.tenant_id == tenant_id,
            AuditActionConfig.action == action
        )
        result = await self.session.execute(stmt)
        config = result.scalar_one_or_none()

        if config:
            # Update existing
            config.enabled = enabled
        else:
            # Create new
            config = AuditActionConfig(
                tenant_id=tenant_id,
                action=action,
                enabled=enabled
            )
            self.session.add(config)

        await self.session.commit()
        await self.session.refresh(config)

        logger.info(
            f"Updated action config for tenant {tenant_id}: {action} = {enabled}"
        )

        return config

    async def update_actions_batch(
        self, tenant_id: UUID, updates: dict[str, bool]
    ) -> list[AuditActionConfig]:
        """Batch update multiple action configurations.

        Args:
            tenant_id: The tenant ID
            updates: Dictionary mapping action type values to enabled status
                    e.g., {"user_created": True, "file_deleted": False}

        Returns:
            List of updated AuditActionConfig objects
        """
        configs = []

        for action, enabled in updates.items():
            # Try to find existing config
            stmt = select(AuditActionConfig).where(
                AuditActionConfig.tenant_id == tenant_id,
                AuditActionConfig.action == action
            )
            result = await self.session.execute(stmt)
            config = result.scalar_one_or_none()

            if config:
                # Update existing
                config.enabled = enabled
            else:
                # Create new
                config = AuditActionConfig(
                    tenant_id=tenant_id,
                    action=action,
                    enabled=enabled
                )
                self.session.add(config)

            configs.append(config)

        await self.session.commit()

        logger.info(
            f"Batch updated {len(updates)} action configs for tenant {tenant_id}"
        )

        return configs

    async def ensure_all_actions_configured(self, tenant_id: UUID) -> None:
        """Ensure all known actions have configuration records for a tenant.

        Creates missing action configs with enabled=True (default).
        This is useful for new tenants or when new actions are added.

        Args:
            tenant_id: The tenant ID
        """
        # Get currently configured actions
        existing = await self.get_actions_for_tenant(tenant_id)
        existing_actions = {config.action for config in existing}

        # Get all known actions from metadata
        all_actions = set(get_all_actions())

        # Find missing actions
        missing_actions = all_actions - existing_actions

        if missing_actions:
            # Create configs for missing actions (default enabled=True)
            for action in missing_actions:
                config = AuditActionConfig(
                    tenant_id=tenant_id,
                    action=action,
                    enabled=True
                )
                self.session.add(config)

            await self.session.commit()

            logger.info(
                f"Created {len(missing_actions)} missing action configs for tenant {tenant_id}"
            )
