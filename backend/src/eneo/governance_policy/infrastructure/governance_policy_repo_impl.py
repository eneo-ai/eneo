# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from eneo.database.database import AsyncSession
from eneo.database.tables.governance_policy_table import (
    GovernancePolicies,
    GovernancePolicyCompletionModels,
    GovernancePolicyDisabledMcpTools,
    GovernancePolicyMcpServers,
    GovernancePolicyProviders,
)
from eneo.governance_policy.domain.governance_policy import (
    GovernancePolicy,
    PolicyCompletionModel,
    PolicyMcpServer,
    PolicyScope,
)


class GovernancePolicyRepoImpl:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _load_policy(self, row: GovernancePolicies) -> GovernancePolicy:
        models_stmt = sa.select(
            GovernancePolicyCompletionModels.completion_model_id,
            GovernancePolicyCompletionModels.is_default,
        ).where(GovernancePolicyCompletionModels.policy_id == row.id)
        model_rows = (await self.session.execute(models_stmt)).all()

        mcp_stmt = sa.select(
            GovernancePolicyMcpServers.mcp_server_id,
            GovernancePolicyMcpServers.is_default_enabled,
        ).where(GovernancePolicyMcpServers.policy_id == row.id)
        mcp_rows = (await self.session.execute(mcp_stmt)).all()

        disabled_tools_stmt = sa.select(
            GovernancePolicyDisabledMcpTools.mcp_tool_id
        ).where(GovernancePolicyDisabledMcpTools.policy_id == row.id)
        disabled_tool_ids = [
            r[0] for r in (await self.session.execute(disabled_tools_stmt)).all()
        ]

        provider_stmt = sa.select(GovernancePolicyProviders.model_provider_id).where(
            GovernancePolicyProviders.policy_id == row.id
        )
        provider_ids = [r[0] for r in (await self.session.execute(provider_stmt)).all()]

        return GovernancePolicy(
            id=row.id,
            tenant_id=row.tenant_id,
            scope=PolicyScope(row.scope),
            models_restriction_enabled=row.models_restriction_enabled,
            mcp_restriction_enabled=row.mcp_restriction_enabled,
            prompt_enforcement_enabled=row.prompt_enforcement_enabled,
            completion_models=[
                PolicyCompletionModel(completion_model_id=r[0], is_default=bool(r[1]))
                for r in model_rows
            ],
            model_provider_ids=provider_ids,
            mcp_servers=[
                PolicyMcpServer(mcp_server_id=r[0], is_default_enabled=bool(r[1]))
                for r in mcp_rows
            ],
            disabled_mcp_tool_ids=disabled_tool_ids,
            default_prompt_library_id=row.default_prompt_library_id,
            updated_at=row.updated_at,
            updated_by_user_id=row.updated_by_user_id,
        )

    async def get_by_tenant(
        self, tenant_id: UUID, *, scope: PolicyScope
    ) -> GovernancePolicy | None:
        stmt = sa.select(GovernancePolicies).where(
            GovernancePolicies.tenant_id == tenant_id,
            GovernancePolicies.scope == scope.value,
        )
        row = await self.session.scalar(stmt)
        if row is None:
            return None
        return await self._load_policy(row)

    async def get_by_tenant_for_update(
        self, tenant_id: UUID, *, scope: PolicyScope
    ) -> GovernancePolicy | None:
        stmt = (
            sa.select(GovernancePolicies)
            .where(
                GovernancePolicies.tenant_id == tenant_id,
                GovernancePolicies.scope == scope.value,
            )
            .with_for_update()
        )
        row = await self.session.scalar(stmt)
        if row is None:
            return None
        return await self._load_policy(row)

    async def create_empty(
        self, tenant_id: UUID, *, scope: PolicyScope
    ) -> GovernancePolicy:
        stmt = (
            insert(GovernancePolicies)
            .values(tenant_id=tenant_id, scope=scope.value)
            .on_conflict_do_nothing(constraint="uq_governance_policies_tenant_id_scope")
            .returning(GovernancePolicies)
        )
        row = await self.session.scalar(stmt)
        if row is None:
            existing = await self.get_by_tenant(tenant_id, scope=scope)
            assert existing is not None
            return existing
        return await self._load_policy(row)

    async def save(
        self,
        policy: GovernancePolicy,
        *,
        updated_by_user_id: UUID,
    ) -> GovernancePolicy:
        assert policy.id is not None

        update = (
            sa.update(GovernancePolicies)
            .where(GovernancePolicies.id == policy.id)
            .values(
                models_restriction_enabled=policy.models_restriction_enabled,
                mcp_restriction_enabled=policy.mcp_restriction_enabled,
                prompt_enforcement_enabled=policy.prompt_enforcement_enabled,
                default_prompt_library_id=policy.default_prompt_library_id,
                updated_by_user_id=updated_by_user_id,
            )
        )
        await self.session.execute(update)

        # Replace m2m rows (simple + correct; small N per policy).
        await self.session.execute(
            sa.delete(GovernancePolicyCompletionModels).where(
                GovernancePolicyCompletionModels.policy_id == policy.id
            )
        )
        if policy.completion_models:
            await self.session.execute(
                sa.insert(GovernancePolicyCompletionModels).values(
                    [
                        {
                            "policy_id": policy.id,
                            "completion_model_id": m.completion_model_id,
                            "is_default": m.is_default,
                        }
                        for m in policy.completion_models
                    ]
                )
            )

        await self.session.execute(
            sa.delete(GovernancePolicyMcpServers).where(
                GovernancePolicyMcpServers.policy_id == policy.id
            )
        )
        if policy.mcp_servers:
            await self.session.execute(
                sa.insert(GovernancePolicyMcpServers).values(
                    [
                        {
                            "policy_id": policy.id,
                            "mcp_server_id": s.mcp_server_id,
                            "is_default_enabled": s.is_default_enabled,
                        }
                        for s in policy.mcp_servers
                    ]
                )
            )

        await self.session.execute(
            sa.delete(GovernancePolicyDisabledMcpTools).where(
                GovernancePolicyDisabledMcpTools.policy_id == policy.id
            )
        )
        if policy.disabled_mcp_tool_ids:
            await self.session.execute(
                sa.insert(GovernancePolicyDisabledMcpTools).values(
                    [
                        {"policy_id": policy.id, "mcp_tool_id": tid}
                        for tid in policy.disabled_mcp_tool_ids
                    ]
                )
            )

        await self.session.execute(
            sa.delete(GovernancePolicyProviders).where(
                GovernancePolicyProviders.policy_id == policy.id
            )
        )
        if policy.model_provider_ids:
            await self.session.execute(
                sa.insert(GovernancePolicyProviders).values(
                    [
                        {"policy_id": policy.id, "model_provider_id": pid}
                        for pid in policy.model_provider_ids
                    ]
                )
            )

        reloaded = await self.session.scalar(
            sa.select(GovernancePolicies).where(GovernancePolicies.id == policy.id)
        )
        assert reloaded is not None
        return await self._load_policy(reloaded)

    async def get_by_prompt_library_id(
        self, *, tenant_id: UUID, prompt_library_id: UUID
    ) -> GovernancePolicy | None:
        stmt = sa.select(GovernancePolicies).where(
            GovernancePolicies.tenant_id == tenant_id,
            GovernancePolicies.default_prompt_library_id == prompt_library_id,
        )
        row = await self.session.scalar(stmt)
        if row is None:
            return None
        return await self._load_policy(row)
