from typing import Optional
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.base_class import BaseCrossReference, BasePublic
from eneo.database.tables.mcp_server_table import MCPServers, MCPServerTools
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.prompt_library_table import PromptLibrary
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class GovernancePolicies(BasePublic):
    # __tablename__ auto-generated as "governance_policies".

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))

    # Which set of assistants this policy governs. Stored as the PolicyScope
    # enum value; set explicitly by the app on create (no DB default). Part of
    # the composite unique below so future scopes don't need a schema change.
    #
    # Validation contract: PolicyScope is the single authority — writes go
    # through `PolicyScope(...).value` and reads through `PolicyScope(row.scope)`
    # (which raises on an unknown value). Deliberately NOT a DB CHECK/enum:
    # that would force a constraint migration for every new scope and defeat
    # the "new scopes are data, not schema" goal the composite unique enables.
    scope: Mapped[str] = mapped_column()

    # Per-dimension enforcement flags. Distinguish "no restriction" from
    # "deny-all" (empty whitelist).
    models_restriction_enabled: Mapped[bool] = mapped_column(server_default="False")
    mcp_restriction_enabled: Mapped[bool] = mapped_column(server_default="False")
    prompt_enforcement_enabled: Mapped[bool] = mapped_column(server_default="False")

    # ON DELETE RESTRICT: admin must unset the prompt on the policy before
    # the library entry can be deleted. The service surfaces this as a 409
    # with context so the FK violation never reaches the client raw.
    default_prompt_library_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(PromptLibrary.id, ondelete="RESTRICT"), nullable=True
    )

    updated_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "scope", name="uq_governance_policies_tenant_id_scope"
        ),
        CheckConstraint(
            "NOT prompt_enforcement_enabled OR default_prompt_library_id IS NOT NULL",
            name="prompt_enforcement_requires_prompt",
        ),
    )


class GovernancePolicyCompletionModels(BaseCrossReference):
    # __tablename__ auto-generated as "governance_policy_completion_models".

    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey(GovernancePolicies.id, ondelete="CASCADE"), primary_key=True
    )
    completion_model_id: Mapped[UUID] = mapped_column(
        ForeignKey(CompletionModels.id, ondelete="CASCADE"), primary_key=True
    )
    is_default: Mapped[bool] = mapped_column(server_default="False")

    __table_args__ = (
        Index(
            "uniq_policy_default_model",
            "policy_id",
            unique=True,
            postgresql_where="is_default",
        ),
    )


class GovernancePolicyMcpServers(BaseCrossReference):
    # __tablename__ auto-generated as "governance_policy_mcp_servers".

    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey(GovernancePolicies.id, ondelete="CASCADE"), primary_key=True
    )
    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServers.id, ondelete="CASCADE"), primary_key=True
    )
    # Whether the server starts switched ON in the user's chat (UX seed only;
    # the user can toggle any allowed server per conversation).
    is_default_enabled: Mapped[bool] = mapped_column(server_default="True")


class GovernancePolicyDisabledMcpTools(BaseCrossReference):
    # __tablename__ auto-generated as "governance_policy_disabled_mcp_tools".
    # Deny-set: rows are tools the admin switched OFF on an allowed server.
    # Tools synced onto a server later are therefore allowed automatically.

    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey(GovernancePolicies.id, ondelete="CASCADE"), primary_key=True
    )
    mcp_tool_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServerTools.id, ondelete="CASCADE"), primary_key=True
    )


class GovernancePolicyProviders(BaseCrossReference):
    # __tablename__ auto-generated as "governance_policy_providers".
    # Whitelisting a provider means "all org-enabled models from this
    # provider, including future additions" — admins lean on this to avoid
    # re-curating after every model upgrade.

    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey(GovernancePolicies.id, ondelete="CASCADE"), primary_key=True
    )
    model_provider_id: Mapped[UUID] = mapped_column(
        ForeignKey(ModelProviders.id, ondelete="CASCADE"), primary_key=True
    )
