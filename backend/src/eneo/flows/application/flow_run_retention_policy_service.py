from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
)
from eneo.flows.domain.flow_run_retention_policy import (
    FlowRunRetentionFlowTargetPage,
    FlowRunRetentionPolicy,
    FlowRunRetentionPolicySettings,
    FlowRunRetentionReviewCursor,
    FlowRunRetentionReviewPage,
    FlowRunRetentionScope,
    FlowRunRetentionSpaceTargetPage,
    effective_flow_run_retention_policy,
)
from eneo.flows.infrastructure.flow_run_retention_policy_repo import (
    FlowRunRetentionPolicyChange,
    FlowRunRetentionPolicyRepository,
)
from eneo.roles.permissions import Permission, validate_permissions
from eneo.settings.settings import (
    FlowRunHistoryPurgeBlockedPublic,
    FlowRunHistoryPurgePublic,
)
from eneo.users.user import UserInDB


class FlowRunRetentionPolicyService:
    def __init__(
        self,
        *,
        user: UserInDB,
        repository: FlowRunRetentionPolicyRepository,
        audit_service: AuditService,
    ) -> None:
        self.user = user
        self.repository = repository
        self.audit_service = audit_service

    @validate_permissions(Permission.ADMIN)
    async def get_organization(self) -> FlowRunRetentionPolicySettings:
        return await self.repository.get_organization(tenant_id=self.user.tenant_id)

    @validate_permissions(Permission.ADMIN)
    async def list_space_targets(
        self,
        *,
        limit: int,
        offset: int,
    ) -> FlowRunRetentionSpaceTargetPage:
        return await self.repository.list_space_targets(
            tenant_id=self.user.tenant_id,
            limit=limit,
            offset=offset,
        )

    @validate_permissions(Permission.ADMIN)
    async def list_flow_targets(
        self,
        *,
        space_id: UUID,
        limit: int,
        offset: int,
    ) -> FlowRunRetentionFlowTargetPage:
        return await self.repository.list_flow_targets(
            tenant_id=self.user.tenant_id,
            space_id=space_id,
            limit=limit,
            offset=offset,
        )

    @validate_permissions(Permission.ADMIN)
    async def replace_organization(
        self,
        *,
        policy: FlowRunRetentionPolicy | None,
    ) -> FlowRunRetentionPolicySettings:
        change = await self.repository.replace_organization(
            tenant_id=self.user.tenant_id,
            policy=policy,
        )
        await self._audit_change(change)
        return change.after

    @validate_permissions(Permission.ADMIN)
    async def get_space(self, *, space_id: UUID) -> FlowRunRetentionPolicySettings:
        return await self.repository.get_space(
            tenant_id=self.user.tenant_id,
            space_id=space_id,
        )

    @validate_permissions(Permission.ADMIN)
    async def replace_space(
        self,
        *,
        space_id: UUID,
        policy: FlowRunRetentionPolicy | None,
    ) -> FlowRunRetentionPolicySettings:
        change = await self.repository.replace_space(
            tenant_id=self.user.tenant_id,
            space_id=space_id,
            policy=policy,
        )
        await self._audit_change(change)
        return change.after

    @validate_permissions(Permission.ADMIN)
    async def get_flow(self, *, flow_id: UUID) -> FlowRunRetentionPolicySettings:
        return await self.repository.get_flow(
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
        )

    @validate_permissions(Permission.ADMIN)
    async def replace_flow(
        self,
        *,
        flow_id: UUID,
        policy: FlowRunRetentionPolicy | None,
    ) -> FlowRunRetentionPolicySettings:
        change = await self.repository.replace_flow(
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            policy=policy,
        )
        await self._audit_change(change)
        return change.after

    @validate_permissions(Permission.ADMIN)
    async def list_organization_review_queue(
        self,
        *,
        limit: int,
        cursor: FlowRunRetentionReviewCursor | None,
    ) -> FlowRunRetentionReviewPage:
        return await self.repository.list_review_queue(
            tenant_id=self.user.tenant_id,
            now=datetime.now(timezone.utc),
            limit=limit,
            cursor=cursor,
        )

    @validate_permissions(Permission.ADMIN)
    async def list_space_review_queue(
        self,
        *,
        space_id: UUID,
        limit: int,
        cursor: FlowRunRetentionReviewCursor | None,
    ) -> FlowRunRetentionReviewPage:
        await self.repository.get_space(
            tenant_id=self.user.tenant_id,
            space_id=space_id,
        )
        return await self.repository.list_review_queue(
            tenant_id=self.user.tenant_id,
            now=datetime.now(timezone.utc),
            limit=limit,
            cursor=cursor,
            space_id=space_id,
        )

    @validate_permissions(Permission.ADMIN)
    async def list_flow_review_queue(
        self,
        *,
        flow_id: UUID,
        limit: int,
        cursor: FlowRunRetentionReviewCursor | None,
    ) -> FlowRunRetentionReviewPage:
        await self.repository.get_flow(
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
        )
        return await self.repository.list_review_queue(
            tenant_id=self.user.tenant_id,
            now=datetime.now(timezone.utc),
            limit=limit,
            cursor=cursor,
            flow_id=flow_id,
        )

    @validate_permissions(Permission.ADMIN)
    async def purge_due_history(
        self,
        *,
        dry_run: bool,
        limit: int,
        space_id: UUID | None = None,
        flow_id: UUID | None = None,
    ) -> FlowRunHistoryPurgePublic:
        if flow_id is not None:
            settings = await self.repository.get_flow(
                tenant_id=self.user.tenant_id, flow_id=flow_id
            )
        elif space_id is not None:
            settings = await self.repository.get_space(
                tenant_id=self.user.tenant_id, space_id=space_id
            )
        else:
            settings = await self.repository.get_organization(
                tenant_id=self.user.tenant_id
            )
        result = await DataRetentionService(
            self.repository.session
        ).purge_due_flow_run_history_for_tenant(
            tenant_id=self.user.tenant_id,
            now=datetime.now(timezone.utc),
            limit=limit,
            dry_run=dry_run,
            space_id=space_id,
            flow_id=flow_id,
        )
        response = FlowRunHistoryPurgePublic(
            dry_run=dry_run,
            scope=settings.scope,
            candidate_count=result.candidate_count,
            purged_count=len(result.purged_run_ids),
            purged_run_ids=list(result.purged_run_ids),
            transcript_candidate_count=result.transcript_candidate_count,
            transcript_purged_count=result.transcript_purged_count,
            blocked=FlowRunHistoryPurgeBlockedPublic(
                undelivered_audit=result.blocked.skipped_undelivered_audit,
                unresolved_webhook=result.blocked.skipped_unresolved_webhook,
                review_required=result.blocked.skipped_review_required,
                counted_runs=result.blocked.counted_runs,
                complete=result.blocked.complete,
            ),
        )
        if not dry_run:
            await self.audit_service.log(
                tenant_id=self.user.tenant_id,
                user=self.user,
                action=ActionType.FLOW_RUN_HISTORY_PURGED,
                entity_type=self._entity_type(settings.scope),
                entity_id=settings.scope_id,
                description="Purged due Flow run history and expired unbound live transcripts.",
                metadata={
                    "scope": settings.scope.value,
                    "scope_id": str(settings.scope_id),
                    "tenant_id": str(self.user.tenant_id),
                    "space_id": str(space_id) if space_id is not None else None,
                    "flow_id": str(flow_id) if flow_id is not None else None,
                    "limit": limit,
                    "purged_count": response.purged_count,
                    "purged_run_ids": [str(run_id) for run_id in result.purged_run_ids],
                    "transcript_candidate_count": response.transcript_candidate_count,
                    "transcript_purged_count": response.transcript_purged_count,
                    "blocked": response.blocked.model_dump(),
                },
                required=True,
            )
        return response

    async def _audit_change(self, change: FlowRunRetentionPolicyChange) -> None:
        if not change.changed:
            return
        after = change.after
        effective_policy = effective_flow_run_retention_policy(after.effective)
        await self.audit_service.log(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.FLOW_RUN_RETENTION_POLICY_CHANGED,
            entity_type=self._entity_type(after.scope),
            entity_id=after.scope_id,
            description="Changed Flow run-history retention policy.",
            metadata={
                "scope": after.scope.value,
                "scope_id": str(after.scope_id),
                "previous_local_policy": self._audit_policy(change.before.local_policy),
                "new_local_policy": self._audit_policy(after.local_policy),
                "effective_policy": self._audit_policy(effective_policy),
                "effective_source": after.effective.source,
            },
            required=True,
        )

    @staticmethod
    def _audit_policy(
        policy: FlowRunRetentionPolicy | None,
    ) -> dict[str, str | int] | None:
        if policy is None:
            return None
        return {"mode": policy.mode.value, "days": policy.days}

    @staticmethod
    def _entity_type(scope: FlowRunRetentionScope) -> EntityType:
        if scope is FlowRunRetentionScope.ORGANIZATION:
            return EntityType.TENANT_SETTINGS
        if scope is FlowRunRetentionScope.SPACE:
            return EntityType.SPACE
        return EntityType.FLOW
