from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import FlowRuns, Flows
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.domain.flow_run_retention_policy import (
    FlowRunRetentionConfiguredSource,
    FlowRunRetentionFlowTarget,
    FlowRunRetentionFlowTargetPage,
    FlowRunRetentionMode,
    FlowRunRetentionPolicy,
    FlowRunRetentionPolicySettings,
    FlowRunRetentionReviewCursor,
    FlowRunRetentionReviewItem,
    FlowRunRetentionReviewPage,
    FlowRunRetentionScope,
    FlowRunRetentionSpaceTarget,
    FlowRunRetentionSpaceTargetPage,
    flow_run_retention_policy_from_storage,
    flow_run_retention_policy_settings,
)
from eneo.flows.enums import TERMINAL_FLOW_RUN_STATUS_VALUES, FlowRunStatus
from eneo.flows.infrastructure.flow_run_retention_policy_query import (
    effective_flow_run_retention_policy_sql,
    flow_run_history_due_predicates,
    flow_run_history_eligible_since_sql,
)
from eneo.main.exceptions import NotFoundException


@dataclass(frozen=True, slots=True)
class FlowRunRetentionPolicyChange:
    before: FlowRunRetentionPolicySettings
    after: FlowRunRetentionPolicySettings

    @property
    def changed(self) -> bool:
        return self.before.local_policy != self.after.local_policy


class FlowRunRetentionPolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_organization(
        self,
        *,
        tenant_id: UUID,
    ) -> FlowRunRetentionPolicySettings:
        row = (
            await self.session.execute(
                sa.select(
                    Tenants.id,
                    Tenants.flow_run_history_retention_mode,
                    Tenants.flow_run_history_retention_days,
                ).where(Tenants.id == tenant_id)
            )
        ).one_or_none()
        if row is None:
            raise NotFoundException("Organization not found.")
        return flow_run_retention_policy_settings(
            scope=FlowRunRetentionScope.ORGANIZATION,
            scope_id=row.id,
            organization_policy=flow_run_retention_policy_from_storage(
                mode=row.flow_run_history_retention_mode,
                days=row.flow_run_history_retention_days,
            ),
        )

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
        rows = (
            await self.session.execute(
                sa.select(Flows.id, Flows.space_id, Flows.name)
                .where(Flows.tenant_id == tenant_id)
                .where(Flows.space_id == space_id)
                .where(Flows.deleted_at.is_(None))
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
                )
                for row in rows[:limit]
            ],
            has_more=len(rows) > limit,
        )

    async def get_space(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
    ) -> FlowRunRetentionPolicySettings:
        row = (
            await self.session.execute(
                sa.select(
                    Spaces.id,
                    Tenants.flow_run_history_retention_mode.label("organization_mode"),
                    Tenants.flow_run_history_retention_days.label("organization_days"),
                    Spaces.flow_run_history_retention_mode.label("space_mode"),
                    Spaces.flow_run_history_retention_days.label("space_days"),
                )
                .join(Tenants, Tenants.id == Spaces.tenant_id)
                .where(Spaces.id == space_id)
                .where(Spaces.tenant_id == tenant_id)
            )
        ).one_or_none()
        if row is None:
            raise NotFoundException("Space not found.")
        return flow_run_retention_policy_settings(
            scope=FlowRunRetentionScope.SPACE,
            scope_id=row.id,
            organization_policy=flow_run_retention_policy_from_storage(
                mode=row.organization_mode,
                days=row.organization_days,
            ),
            space_policy=flow_run_retention_policy_from_storage(
                mode=row.space_mode,
                days=row.space_days,
            ),
        )

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
                    Tenants.flow_run_history_retention_mode.label("organization_mode"),
                    Tenants.flow_run_history_retention_days.label("organization_days"),
                    Spaces.flow_run_history_retention_mode.label("space_mode"),
                    Spaces.flow_run_history_retention_days.label("space_days"),
                    Flows.flow_run_history_retention_mode.label("flow_mode"),
                    Flows.flow_run_history_retention_days.label("flow_days"),
                )
                .join(
                    Spaces,
                    sa.and_(
                        Spaces.id == Flows.space_id,
                        Spaces.tenant_id == Flows.tenant_id,
                    ),
                )
                .join(Tenants, Tenants.id == Flows.tenant_id)
                .where(Flows.id == flow_id)
                .where(Flows.tenant_id == tenant_id)
                .where(Flows.deleted_at.is_(None))
            )
        ).one_or_none()
        if row is None:
            raise NotFoundException("Flow not found.")
        return flow_run_retention_policy_settings(
            scope=FlowRunRetentionScope.FLOW,
            scope_id=row.id,
            organization_policy=flow_run_retention_policy_from_storage(
                mode=row.organization_mode,
                days=row.organization_days,
            ),
            space_policy=flow_run_retention_policy_from_storage(
                mode=row.space_mode,
                days=row.space_days,
            ),
            flow_policy=flow_run_retention_policy_from_storage(
                mode=row.flow_mode,
                days=row.flow_days,
            ),
        )

    async def replace_organization(
        self,
        *,
        tenant_id: UUID,
        policy: FlowRunRetentionPolicy | None,
    ) -> FlowRunRetentionPolicyChange:
        await self._lock_organization(tenant_id=tenant_id)
        before = await self.get_organization(tenant_id=tenant_id)
        if before.local_policy != policy:
            await self.session.execute(
                sa.update(Tenants)
                .where(Tenants.id == tenant_id)
                .values(**self._policy_values(policy))
            )
        return FlowRunRetentionPolicyChange(
            before=before,
            after=await self.get_organization(tenant_id=tenant_id),
        )

    async def replace_space(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        policy: FlowRunRetentionPolicy | None,
    ) -> FlowRunRetentionPolicyChange:
        await self._lock_space(tenant_id=tenant_id, space_id=space_id)
        before = await self.get_space(tenant_id=tenant_id, space_id=space_id)
        if before.local_policy != policy:
            await self.session.execute(
                sa.update(Spaces)
                .where(Spaces.id == space_id)
                .where(Spaces.tenant_id == tenant_id)
                .values(**self._policy_values(policy))
            )
        return FlowRunRetentionPolicyChange(
            before=before,
            after=await self.get_space(tenant_id=tenant_id, space_id=space_id),
        )

    async def replace_flow(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        policy: FlowRunRetentionPolicy | None,
    ) -> FlowRunRetentionPolicyChange:
        await self._lock_flow(tenant_id=tenant_id, flow_id=flow_id)
        before = await self.get_flow(tenant_id=tenant_id, flow_id=flow_id)
        if before.local_policy != policy:
            await self.session.execute(
                sa.update(Flows)
                .where(Flows.id == flow_id)
                .where(Flows.tenant_id == tenant_id)
                .where(Flows.deleted_at.is_(None))
                .values(**self._policy_values(policy))
            )
        return FlowRunRetentionPolicyChange(
            before=before,
            after=await self.get_flow(tenant_id=tenant_id, flow_id=flow_id),
        )

    async def list_review_queue(
        self,
        *,
        tenant_id: UUID,
        now: datetime,
        limit: int,
        cursor: FlowRunRetentionReviewCursor | None,
        space_id: UUID | None = None,
        flow_id: UUID | None = None,
    ) -> FlowRunRetentionReviewPage:
        anchor = cast(
            sa.ColumnElement[datetime],
            sa.func.coalesce(FlowRuns.finished_at, FlowRuns.created_at),
        )
        effective_policy = effective_flow_run_retention_policy_sql(
            organization_mode=(
                Tenants.flow_run_history_retention_mode.__clause_element__()
            ),
            organization_days=(
                Tenants.flow_run_history_retention_days.__clause_element__()
            ),
            space_mode=(Spaces.flow_run_history_retention_mode.__clause_element__()),
            space_days=Spaces.flow_run_history_retention_days.__clause_element__(),
            flow_mode=Flows.flow_run_history_retention_mode.__clause_element__(),
            flow_days=Flows.flow_run_history_retention_days.__clause_element__(),
        )
        eligible_since = flow_run_history_eligible_since_sql(
            anchor=anchor,
            effective_days=effective_policy.days,
        )
        stmt = (
            sa.select(
                FlowRuns.id.label("run_id"),
                Flows.id.label("flow_id"),
                Flows.name.label("flow_name"),
                Spaces.id.label("space_id"),
                Spaces.name.label("space_name"),
                FlowRuns.status,
                anchor.label("retention_anchor"),
                eligible_since.label("eligible_since"),
                effective_policy.days.label("effective_days"),
                effective_policy.source.label("policy_source"),
            )
            .join(
                Flows,
                sa.and_(
                    FlowRuns.flow_id == Flows.id,
                    FlowRuns.tenant_id == Flows.tenant_id,
                ),
            )
            .join(
                Spaces,
                sa.and_(
                    Flows.space_id == Spaces.id,
                    Flows.tenant_id == Spaces.tenant_id,
                ),
            )
            .join(Tenants, FlowRuns.tenant_id == Tenants.id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status.in_(TERMINAL_FLOW_RUN_STATUS_VALUES))
            .where(effective_policy.mode == FlowRunRetentionMode.REVIEW_REQUIRED.value)
            .where(
                *flow_run_history_due_predicates(
                    now=now,
                    anchor=anchor,
                    effective_days=effective_policy.days,
                )
            )
        )
        if space_id is not None:
            stmt = stmt.where(Spaces.id == space_id)
        if flow_id is not None:
            stmt = stmt.where(Flows.id == flow_id)
        if cursor is not None:
            stmt = stmt.where(
                sa.or_(
                    anchor > cursor.retention_anchor,
                    sa.and_(
                        anchor == cursor.retention_anchor,
                        FlowRuns.id > cursor.run_id,
                    ),
                )
            )
        rows = (
            await self.session.execute(
                stmt.order_by(anchor.asc(), FlowRuns.id.asc()).limit(limit + 1)
            )
        ).all()
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        items = [
            FlowRunRetentionReviewItem(
                run_id=row.run_id,
                flow_id=row.flow_id,
                flow_name=row.flow_name,
                space_id=row.space_id,
                space_name=row.space_name,
                status=FlowRunStatus(row.status),
                retention_anchor=row.retention_anchor,
                eligible_since=row.eligible_since,
                effective_policy=FlowRunRetentionPolicy(
                    mode=FlowRunRetentionMode.REVIEW_REQUIRED,
                    days=row.effective_days,
                ),
                policy_source=cast(
                    FlowRunRetentionConfiguredSource,
                    row.policy_source,
                ),
            )
            for row in page_rows
        ]
        next_cursor = (
            FlowRunRetentionReviewCursor(
                retention_anchor=page_rows[-1].retention_anchor,
                run_id=page_rows[-1].run_id,
            ).serialize()
            if has_more and page_rows
            else None
        )
        return FlowRunRetentionReviewPage(
            items=items,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    async def _lock_organization(self, *, tenant_id: UUID) -> None:
        found = await self.session.scalar(
            sa.select(Tenants.id).where(Tenants.id == tenant_id).with_for_update()
        )
        if found is None:
            raise NotFoundException("Organization not found.")

    async def _lock_space(self, *, tenant_id: UUID, space_id: UUID) -> None:
        found = await self.session.scalar(
            sa.select(Spaces.id)
            .where(Spaces.id == space_id)
            .where(Spaces.tenant_id == tenant_id)
            .with_for_update()
        )
        if found is None:
            raise NotFoundException("Space not found.")

    async def _lock_flow(self, *, tenant_id: UUID, flow_id: UUID) -> None:
        found = await self.session.scalar(
            sa.select(Flows.id)
            .where(Flows.id == flow_id)
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
            .with_for_update()
        )
        if found is None:
            raise NotFoundException("Flow not found.")

    @staticmethod
    def _policy_values(
        policy: FlowRunRetentionPolicy | None,
    ) -> dict[str, str | int | None]:
        return {
            "flow_run_history_retention_mode": (
                policy.mode.value if policy is not None else None
            ),
            "flow_run_history_retention_days": (
                policy.days if policy is not None else None
            ),
        }
