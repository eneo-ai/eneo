# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from intric.database.database import AsyncSession
from intric.database.tables.personal_assistant_policy_table import (
    PersonalAssistantPolicies,
    PersonalAssistantPolicyCompletionModels,
    PersonalAssistantPolicyMcpServers,
    PersonalAssistantPolicyProviders,
)
from intric.personal_assistant_policy.domain.personal_assistant_policy import (
    PersonalAssistantPolicy,
    PolicyCompletionModel,
)


class PersonalAssistantPolicyRepoImpl:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _load_policy(
        self, row: PersonalAssistantPolicies
    ) -> PersonalAssistantPolicy:
        models_stmt = sa.select(
            PersonalAssistantPolicyCompletionModels.completion_model_id,
            PersonalAssistantPolicyCompletionModels.is_default,
        ).where(PersonalAssistantPolicyCompletionModels.policy_id == row.id)
        model_rows = (await self.session.execute(models_stmt)).all()

        mcp_stmt = sa.select(PersonalAssistantPolicyMcpServers.mcp_server_id).where(
            PersonalAssistantPolicyMcpServers.policy_id == row.id
        )
        mcp_ids = [r[0] for r in (await self.session.execute(mcp_stmt)).all()]

        provider_stmt = sa.select(
            PersonalAssistantPolicyProviders.model_provider_id
        ).where(PersonalAssistantPolicyProviders.policy_id == row.id)
        provider_ids = [r[0] for r in (await self.session.execute(provider_stmt)).all()]

        return PersonalAssistantPolicy(
            id=row.id,
            tenant_id=row.tenant_id,
            models_restriction_enabled=row.models_restriction_enabled,
            mcp_restriction_enabled=row.mcp_restriction_enabled,
            prompt_enforcement_enabled=row.prompt_enforcement_enabled,
            completion_models=[
                PolicyCompletionModel(completion_model_id=r[0], is_default=bool(r[1]))
                for r in model_rows
            ],
            model_provider_ids=provider_ids,
            mcp_server_ids=mcp_ids,
            default_prompt_library_id=row.default_prompt_library_id,
            updated_at=row.updated_at,
            updated_by_user_id=row.updated_by_user_id,
        )

    async def get_by_tenant(self, tenant_id: UUID) -> PersonalAssistantPolicy | None:
        stmt = sa.select(PersonalAssistantPolicies).where(
            PersonalAssistantPolicies.tenant_id == tenant_id
        )
        row = await self.session.scalar(stmt)
        if row is None:
            return None
        return await self._load_policy(row)

    async def create_empty(self, tenant_id: UUID) -> PersonalAssistantPolicy:
        stmt = (
            insert(PersonalAssistantPolicies)
            .values(tenant_id=tenant_id)
            .on_conflict_do_nothing(
                constraint="uq_personal_assistant_policies_tenant_id"
            )
            .returning(PersonalAssistantPolicies)
        )
        row = await self.session.scalar(stmt)
        if row is None:
            existing = await self.get_by_tenant(tenant_id)
            assert existing is not None
            return existing
        return await self._load_policy(row)

    async def save(
        self,
        policy: PersonalAssistantPolicy,
        *,
        updated_by_user_id: UUID,
    ) -> PersonalAssistantPolicy:
        assert policy.id is not None

        update = (
            sa.update(PersonalAssistantPolicies)
            .where(PersonalAssistantPolicies.id == policy.id)
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
            sa.delete(PersonalAssistantPolicyCompletionModels).where(
                PersonalAssistantPolicyCompletionModels.policy_id == policy.id
            )
        )
        if policy.completion_models:
            await self.session.execute(
                sa.insert(PersonalAssistantPolicyCompletionModels).values(
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
            sa.delete(PersonalAssistantPolicyMcpServers).where(
                PersonalAssistantPolicyMcpServers.policy_id == policy.id
            )
        )
        if policy.mcp_server_ids:
            await self.session.execute(
                sa.insert(PersonalAssistantPolicyMcpServers).values(
                    [
                        {"policy_id": policy.id, "mcp_server_id": mid}
                        for mid in policy.mcp_server_ids
                    ]
                )
            )

        await self.session.execute(
            sa.delete(PersonalAssistantPolicyProviders).where(
                PersonalAssistantPolicyProviders.policy_id == policy.id
            )
        )
        if policy.model_provider_ids:
            await self.session.execute(
                sa.insert(PersonalAssistantPolicyProviders).values(
                    [
                        {"policy_id": policy.id, "model_provider_id": pid}
                        for pid in policy.model_provider_ids
                    ]
                )
            )

        reloaded = await self.session.scalar(
            sa.select(PersonalAssistantPolicies).where(
                PersonalAssistantPolicies.id == policy.id
            )
        )
        assert reloaded is not None
        return await self._load_policy(reloaded)

    async def get_by_prompt_library_id(
        self, *, tenant_id: UUID, prompt_library_id: UUID
    ) -> PersonalAssistantPolicy | None:
        stmt = sa.select(PersonalAssistantPolicies).where(
            PersonalAssistantPolicies.tenant_id == tenant_id,
            PersonalAssistantPolicies.default_prompt_library_id == prompt_library_id,
        )
        row = await self.session.scalar(stmt)
        if row is None:
            return None
        return await self._load_policy(row)
