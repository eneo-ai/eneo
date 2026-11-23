from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.infrastructure.gallring_lock import (
    GallringSubject,
    acquire_exclusive,
)
from eneo.database.tables.flow_tables import FlowRuns, Flows
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.domain.flow_retention_hold import FlowRetentionHoldReviewLimit
from eneo.flows.domain.flow_run_retention_policy import (
    FlowRunRetentionFlowTarget,
    FlowRunRetentionFlowTargetPage,
    FlowRunRetentionPolicy,
    FlowRunRetentionPolicySettings,
    FlowRunRetentionSpaceTarget,
    FlowRunRetentionSpaceTargetPage,
    flow_run_retention_policy_settings,
    require_within_space_cap,
)
from eneo.flows.flow_retention_policy import (
    FLOW_RETENTION_POLICY_HOLD_MAX_REVIEW_DAYS_KEY,
    apply_flow_retention_policy_patch,
    resolve_flow_retention_policy,
)
from eneo.flows.infrastructure.flow_retention_hold_repo import flow_has_active_hold
from eneo.main.exceptions import NotFoundException
from eneo.tenants.tenant_repo import update_tenant_flow_settings


@dataclass(frozen=True, slots=True)
class FlowRunRetentionPolicyChange:
    before: FlowRunRetentionPolicySettings
    after: FlowRunRetentionPolicySettings

    @property
    def changed(self) -> bool:
        return self.before.local_policy != self.after.local_policy


def _hold_review_limit(
    flow_settings: dict[str, Any] | None,
) -> FlowRetentionHoldReviewLimit:
    policy = resolve_flow_retention_policy(flow_settings)
    return FlowRetentionHoldReviewLimit(
        days=policy.effective_hold_max_review_days(),
        is_default=policy.hold_max_review_days is None,
    )


class FlowRunRetentionPolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_space_targets(
        self,
        *,
        tenant_id: UUID,
        limit: int,
        offset: int,
    ) -> FlowRunRetentionSpaceTargetPage:
        rows = (
            await self.session.execute(
                sa.select(Spaces.id, Spaces.name)
                .where(Spaces.tenant_id == tenant_id)
                .where(Spaces.user_id.is_(None))
                .order_by(sa.func.lower(Spaces.name), Spaces.id)
                .offset(offset)
                .limit(limit + 1)
            )
        ).all()
        return FlowRunRetentionSpaceTargetPage(
            items=[
                FlowRunRetentionSpaceTarget(id=row.id, name=row.name)
                for row in rows[:limit]
            ],
            has_more=len(rows) > limit,
        )

    async def list_flow_targets(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        limit: int,
        offset: int,
    ) -> FlowRunRetentionFlowTargetPage:
        target_space_id = await self.session.scalar(
            sa.select(Spaces.id)
            .where(Spaces.id == space_id)
            .where(Spaces.tenant_id == tenant_id)
            .where(Spaces.user_id.is_(None))
        )
        if target_space_id is None:
            raise NotFoundException("Space not found.")
        # A deleted flow stays administrable while it keeps run history that
        # retention governs; one without runs has nothing left to govern.
        rows = (
            await self.session.execute(
                sa.select(
                    Flows.id,
                    Flows.space_id,
                    Flows.name,
                    Flows.deleted_at.is_not(None).label("retired"),
                    flow_has_active_hold(Flows.id).label("held"),
                )
                .where(Flows.tenant_id == tenant_id)
                .where(Flows.space_id == space_id)
                .where(
                    sa.or_(
                        Flows.deleted_at.is_(None),
                        sa.exists().where(
                            FlowRuns.flow_id == Flows.id,
                            FlowRuns.tenant_id == Flows.tenant_id,
                        ),
                    )
                )
                .order_by(sa.func.lower(Flows.name), Flows.id)
                .offset(offset)
                .limit(limit + 1)
            )
        ).all()
        return FlowRunRetentionFlowTargetPage(
            items=[
                FlowRunRetentionFlowTarget(
                    id=row.id,
                    space_id=row.space_id,
                    name=row.name,
                    retired=row.retired,
                    held=row.held,
                )
                for row in rows[:limit]
            ],
            has_more=len(rows) > limit,
        )

    async def require_space(self, *, tenant_id: UUID, space_id: UUID) -> UUID:
        """A Space of this organisation, personal ones included, or 404."""
        found = await self.session.scalar(
            sa.select(Spaces.id)
            .where(Spaces.id == space_id)
            .where(Spaces.tenant_id == tenant_id)
        )
        if found is None:
            raise NotFoundException("Space not found.")
        return found

    async def get_flow(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
    ) -> FlowRunRetentionPolicySettings:
        row = (
            await self.session.execute(
                sa.select(
                    Flows.id,
                    Spaces.data_retention_days.label("space_days"),
                    Flows.flow_run_history_retention_days.label("flow_days"),
                )
                .join(
                    Spaces,
                    sa.and_(
                        Spaces.id == Flows.space_id,
                        Spaces.tenant_id == Flows.tenant_id,
                    ),
                )
                .where(Flows.id == flow_id)
                .where(Flows.tenant_id == tenant_id)
            )
        ).one_or_none()
        if row is None:
            raise NotFoundException("Flow not found.")
        return flow_run_retention_policy_settings(
            flow_id=row.id, space_days=row.space_days, flow_days=row.flow_days
        )

    async def replace_flow(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        policy: FlowRunRetentionPolicy | None,
    ) -> FlowRunRetentionPolicyChange:
        await acquire_exclusive(self.session, GallringSubject.FLOW_HISTORY)
        await self._lock_flow(tenant_id=tenant_id, flow_id=flow_id)
        before = await self.get_flow(tenant_id=tenant_id, flow_id=flow_id)
        # Read under the lock the Space writer also takes, so the cap holds.
        # Every time sent is checked, also one stored before the cap was lowered.
        require_within_space_cap(
            space_days=before.inherited_policy.days
            if before.inherited_policy
            else None,
            days=policy.days if policy is not None else None,
        )
        if before.local_policy != policy:
            await self.session.execute(
                sa.update(Flows)
                .where(Flows.id == flow_id)
                .where(Flows.tenant_id == tenant_id)
                .values(
                    flow_run_history_retention_days=(
                        policy.days if policy is not None else None
                    )
                )
            )
        return FlowRunRetentionPolicyChange(
            before=before,
            after=await self.get_flow(tenant_id=tenant_id, flow_id=flow_id),
        )

    async def get_hold_review_limit(
        self, *, tenant_id: UUID
    ) -> FlowRetentionHoldReviewLimit:
        flow_settings = await self.session.scalar(
            sa.select(Tenants.flow_settings).where(Tenants.id == tenant_id)
        )
        return _hold_review_limit(flow_settings)

    async def replace_hold_review_limit(
        self, *, tenant_id: UUID, days: int | None
    ) -> tuple[FlowRetentionHoldReviewLimit, FlowRetentionHoldReviewLimit]:
        """Store the limit in the tenant's flow settings; returns (before, after)."""
        await acquire_exclusive(self.session, GallringSubject.FLOW_HISTORY)
        change = await update_tenant_flow_settings(
            self.session,
            tenant_id,
            lambda current: apply_flow_retention_policy_patch(
                current,
                hold_max_review_days=days,
                remove_keys=(
                    {FLOW_RETENTION_POLICY_HOLD_MAX_REVIEW_DAYS_KEY}
                    if days is None
                    else set()
                ),
            ),
        )
        return _hold_review_limit(change.before), _hold_review_limit(change.after)

    async def _lock_flow(self, *, tenant_id: UUID, flow_id: UUID) -> None:
        found = await self.session.scalar(
            sa.select(Flows.id)
            .where(Flows.id == flow_id)
            .where(Flows.tenant_id == tenant_id)
            .with_for_update()
        )
        if found is None:
            raise NotFoundException("Flow not found.")
