from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.main.exceptions import NotFoundException
from eneo.modules.module import (
    ModuleCreate,
    ModuleInstallation,
    ModuleInstallationChange,
    ModuleInstallationConfig,
)
from eneo.modules.module_auth import ModuleAuthBroker
from eneo.modules.module_repo import ModuleRepository
from eneo.tenants.tenant_service import TenantService
from eneo.users.user import UserInDB


class ModuleInstallationService:
    """Canonical lifecycle owner for the current installation's modules.

    ``tenant_id`` is derived exclusively from the authenticated user. This
    preserves the database's isolation boundary without exposing tenancy in
    the admin contract.
    """

    def __init__(
        self,
        *,
        user: UserInDB,
        module_repo: ModuleRepository,
        tenant_service: TenantService,
        module_auth_broker: ModuleAuthBroker,
        audit_service: AuditService,
    ) -> None:
        self.user = user
        self.module_repo = module_repo
        self.tenant_service = tenant_service
        self.module_auth_broker = module_auth_broker
        self.audit_service = audit_service

    async def list_installations(self) -> list[ModuleInstallation]:
        return await self.module_repo.get_installations(self.user.tenant_id)

    async def install(
        self, *, module_key: str, config: ModuleInstallationConfig
    ) -> ModuleInstallation:
        module = await self.module_repo.get_or_add(ModuleCreate(name=module_key))
        assignment = await self.tenant_service.enable_module(
            tenant_id=self.user.tenant_id,
            module_id=module.id,
        )
        # A row created by this transaction has no pre-image; reading it back
        # would record a fabricated empty "before" in the audit trail.
        previous = (
            None
            if assignment.changed
            else await self.module_repo.get_module_client_config(
                tenant_id=self.user.tenant_id,
                module_id=module.id,
            )
        )
        if config.service_key_id is not None:
            # Validated last before the config write: the FOR UPDATE row lock
            # this takes is held until commit and contends with every
            # authentication touching the key, so the window is kept minimal.
            # A validation failure still rolls back the registry and
            # assignment writes with the function-scoped transaction.
            await self.module_auth_broker.validate_client_config_service_key(
                tenant_id=self.user.tenant_id,
                service_key_id=config.service_key_id,
            )
        updated = await self.module_repo.update_client_config(
            tenant_id=self.user.tenant_id,
            module_id=module.id,
            redirect_uris=config.redirect_uris,
            service_key_id=config.service_key_id,
        )
        if updated is None:
            raise RuntimeError("Enabled module lost its tenant assignment.")

        if assignment.changed:
            await self.audit_service.log(
                tenant_id=self.user.tenant_id,
                actor_id=self.user.id,
                actor_type=ActorType.USER,
                action=ActionType.MODULE_ADDED_TO_TENANT,
                entity_type=EntityType.MODULE,
                entity_id=module.id,
                description=f"Administrator installed module '{module.name}'",
                metadata={
                    "actor": {"type": "user", "via": "admin_session"},
                    "target": {
                        "module_id": str(module.id),
                        "module_name": module.name,
                    },
                },
            )

        before = previous.model_dump(mode="json") if previous is not None else None
        after = updated.model_dump(mode="json")
        if before != after:
            await self.audit_service.log(
                tenant_id=self.user.tenant_id,
                actor_id=self.user.id,
                actor_type=ActorType.USER,
                action=ActionType.MODULE_CLIENT_CONFIG_UPDATED,
                entity_type=EntityType.MODULE,
                entity_id=module.id,
                description=f"Administrator configured module '{module.name}'",
                metadata={
                    "actor": {"type": "user", "via": "admin_session"},
                    "target": {
                        "module_id": str(module.id),
                        "module_name": module.name,
                    },
                    "before": before,
                    "after": after,
                },
            )

        return ModuleInstallation(
            module_id=module.id,
            module_key=module.name,
            redirect_uris=updated.redirect_uris or [],
            service_key_id=updated.service_key_id,
        )

    async def uninstall(self, *, module_key: str) -> ModuleInstallationChange:
        # One uniform 404 for "unknown key" and "not installed here": the
        # global registry must not act as a cross-tenant existence oracle.
        module = await self.module_repo.get_module_by_key(module_key)
        if module is None or (
            await self.module_repo.get_module_client_config(
                tenant_id=self.user.tenant_id,
                module_id=module.id,
            )
            is None
        ):
            raise NotFoundException("Module is not installed for this organization.")

        assignment = await self.tenant_service.disable_module(
            tenant_id=self.user.tenant_id,
            module_id=module.id,
        )
        if assignment.changed:
            await self.audit_service.log(
                tenant_id=self.user.tenant_id,
                actor_id=self.user.id,
                actor_type=ActorType.USER,
                action=ActionType.MODULE_REMOVED_FROM_TENANT,
                entity_type=EntityType.MODULE,
                entity_id=module.id,
                description=f"Administrator uninstalled module '{module.name}'",
                metadata={
                    "actor": {"type": "user", "via": "admin_session"},
                    "target": {
                        "module_id": str(module.id),
                        "module_name": module.name,
                    },
                },
            )

        return ModuleInstallationChange(
            module_id=assignment.module_id,
            module_key=assignment.module_key,
            enabled=assignment.enabled,
            changed=assignment.changed,
        )
