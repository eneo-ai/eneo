# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from intric.database.database import AsyncSession
from intric.database.tables.personal_chat_policy_table import (
    PersonalChatPolicies,
    PersonalChatPolicyCompletionModels,
    PersonalChatPolicyMcpServers,
)
from intric.personal_chat_policy.domain.personal_chat_policy import (
    PersonalChatPolicy,
    PolicyCompletionModel,
)


class PersonalChatPolicyRepoImpl:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _load_policy(self, row: PersonalChatPolicies) -> PersonalChatPolicy:
        models_stmt = sa.select(
            PersonalChatPolicyCompletionModels.completion_model_id,
            PersonalChatPolicyCompletionModels.is_default,
        ).where(PersonalChatPolicyCompletionModels.policy_id == row.id)
        model_rows = (await self.session.execute(models_stmt)).all()

        mcp_stmt = sa.select(PersonalChatPolicyMcpServers.mcp_server_id).where(
            PersonalChatPolicyMcpServers.policy_id == row.id
        )
        mcp_ids = [r[0] for r in (await self.session.execute(mcp_stmt)).all()]

        return PersonalChatPolicy(
            id=row.id,
            tenant_id=row.tenant_id,
            models_restriction_enabled=row.models_restriction_enabled,
            mcp_restriction_enabled=row.mcp_restriction_enabled,
            prompt_enforcement_enabled=row.prompt_enforcement_enabled,
            completion_models=[
                PolicyCompletionModel(completion_model_id=r[0], is_default=bool(r[1]))
                for r in model_rows
            ],
            mcp_server_ids=mcp_ids,
            default_prompt_library_id=row.default_prompt_library_id,
            updated_at=row.updated_at,
            updated_by_user_id=row.updated_by_user_id,
        )

    async def get_by_tenant(self, tenant_id: UUID) -> PersonalChatPolicy | None:
        stmt = sa.select(PersonalChatPolicies).where(
            PersonalChatPolicies.tenant_id == tenant_id
        )
        row = await self.session.scalar(stmt)
        if row is None:
            return None
        return await self._load_policy(row)

    async def create_empty(self, tenant_id: UUID) -> PersonalChatPolicy:
        stmt = (
            insert(PersonalChatPolicies)
            .values(tenant_id=tenant_id)
            .on_conflict_do_nothing(constraint="uq_personal_chat_policies_tenant_id")
            .returning(PersonalChatPolicies)
        )
        row = await self.session.scalar(stmt)
        if row is None:
            existing = await self.get_by_tenant(tenant_id)
            assert existing is not None
            return existing
        return await self._load_policy(row)

    async def save(
        self,
        policy: PersonalChatPolicy,
        *,
        updated_by_user_id: UUID,
    ) -> PersonalChatPolicy:
        assert policy.id is not None

        update = (
            sa.update(PersonalChatPolicies)
            .where(PersonalChatPolicies.id == policy.id)
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
            sa.delete(PersonalChatPolicyCompletionModels).where(
                PersonalChatPolicyCompletionModels.policy_id == policy.id
            )
        )
        if policy.completion_models:
            await self.session.execute(
                sa.insert(PersonalChatPolicyCompletionModels).values(
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
            sa.delete(PersonalChatPolicyMcpServers).where(
                PersonalChatPolicyMcpServers.policy_id == policy.id
            )
        )
        if policy.mcp_server_ids:
            await self.session.execute(
                sa.insert(PersonalChatPolicyMcpServers).values(
                    [
                        {"policy_id": policy.id, "mcp_server_id": mid}
                        for mid in policy.mcp_server_ids
                    ]
                )
            )

        reloaded = await self.session.scalar(
            sa.select(PersonalChatPolicies).where(PersonalChatPolicies.id == policy.id)
        )
        assert reloaded is not None
        return await self._load_policy(reloaded)

    async def get_by_prompt_library_id(
        self, *, tenant_id: UUID, prompt_library_id: UUID
    ) -> PersonalChatPolicy | None:
        stmt = sa.select(PersonalChatPolicies).where(
            PersonalChatPolicies.tenant_id == tenant_id,
            PersonalChatPolicies.default_prompt_library_id == prompt_library_id,
        )
        row = await self.session.scalar(stmt)
        if row is None:
            return None
        return await self._load_policy(row)
