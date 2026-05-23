from typing import Optional
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.ai_models_table import CompletionModels
from intric.database.tables.base_class import BaseCrossReference, BasePublic
from intric.database.tables.mcp_server_table import MCPServers
from intric.database.tables.model_providers_table import ModelProviders
from intric.database.tables.prompt_library_table import PromptLibrary
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users


class PersonalAssistantPolicies(BasePublic):
    # __tablename__ auto-generated as "personal_assistant_policies".

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))

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
        UniqueConstraint("tenant_id", name="uq_personal_assistant_policies_tenant_id"),
        CheckConstraint(
            "NOT prompt_enforcement_enabled OR default_prompt_library_id IS NOT NULL",
            name="prompt_enforcement_requires_prompt",
        ),
    )


class PersonalAssistantPolicyCompletionModels(BaseCrossReference):
    # __tablename__ auto-generated as "personal_assistant_policy_completion_models".

    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey(PersonalAssistantPolicies.id, ondelete="CASCADE"), primary_key=True
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


class PersonalAssistantPolicyMcpServers(BaseCrossReference):
    # __tablename__ auto-generated as "personal_assistant_policy_mcp_servers".

    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey(PersonalAssistantPolicies.id, ondelete="CASCADE"), primary_key=True
    )
    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServers.id, ondelete="CASCADE"), primary_key=True
    )


class PersonalAssistantPolicyProviders(BaseCrossReference):
    # __tablename__ auto-generated as "personal_assistant_policy_providers".
    # Whitelisting a provider means "all org-enabled models from this
    # provider, including future additions" — admins lean on this to avoid
    # re-curating after every model upgrade.

    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey(PersonalAssistantPolicies.id, ondelete="CASCADE"), primary_key=True
    )
    model_provider_id: Mapped[UUID] = mapped_column(
        ForeignKey(ModelProviders.id, ondelete="CASCADE"), primary_key=True
    )
