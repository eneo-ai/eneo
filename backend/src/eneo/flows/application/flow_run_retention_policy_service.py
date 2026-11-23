from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.flows.application.flow_retention_authz import (
    require_retention_manage,
    require_retention_view,
)
from eneo.flows.domain.flow_retention_hold import FlowRetentionHoldReviewLimit
from eneo.flows.domain.flow_run_retention_policy import (
    FlowRunRetentionFlowTargetPage,
    FlowRunRetentionPolicy,
    FlowRunRetentionPolicySettings,
    FlowRunRetentionScope,
    FlowRunRetentionSpaceTargetPage,
)
from eneo.flows.infrastructure.flow_retention_repo import FlowRetentionRepository
from eneo.flows.infrastructure.flow_run_retention_policy_repo import (
    FlowRunRetentionPolicyChange,
    FlowRunRetentionPolicyRepository,
)
from eneo.main.exceptions import UnauthorizedException
from eneo.settings.settings import (
    FlowRunHistoryPurgeBlockedPublic,
    FlowRunHistoryPurgePublic,
)
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.actors.actor_manager import ActorManager
    from eneo.spaces.space_repo import SpaceRepository


class FlowRunRetentionPolicyService:
    def __init__(
        self,
        *,
        user: UserInDB,
        repository: FlowRunRetentionPolicyRepository,
        audit_service: AuditService,
        space_repo: SpaceRepository,
        actor_manager: ActorManager,
    ) -> None:
        self.user = user
        self.repository = repository
        self.audit_service = audit_service
        self.space_repo = space_repo
        self.actor_manager = actor_manager

    async def list_space_targets(
        self,
        *,
        limit: int,
        offset: int,
    ) -> FlowRunRetentionSpaceTargetPage:
        require_retention_view(self.user)
        return await self.repository.list_space_targets(
            tenant_id=self.user.tenant_id,
            limit=limit,
            offset=offset,
        )

    async def list_flow_targets(
        self,
        *,
        space_id: UUID,
        limit: int,
        offset: int,
    ) -> FlowRunRetentionFlowTargetPage:
        require_retention_view(self.user)
        return await self.repository.list_flow_targets(
            tenant_id=self.user.tenant_id,
            space_id=space_id,
            limit=limit,
            offset=offset,
        )

    async def get_flow(self, *, flow_id: UUID) -> FlowRunRetentionPolicySettings:
        require_retention_view(self.user)
        return await self.repository.get_flow(
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
        )

    async def replace_flow(
        self,
        *,
        flow_id: UUID,
        policy: FlowRunRetentionPolicy | None,
    ) -> FlowRunRetentionPolicySettings:
        require_retention_manage(self.user)
        await self._require_space_retention_role(flow_id)
        change = await self.repository.replace_flow(
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            policy=policy,
        )
        await self._audit_change(change)
        return change.after

    async def _require_space_retention_role(self, flow_id: UUID) -> None:
        """A Flow's time is set by whoever sets retention in its space: the
        space admin, or a personal space's owner. The same rule as the space
        time and the assistant and app times (``SpaceActor.can_edit_retention``)."""
        space_id = await self.repository.get_flow_space_id(
            tenant_id=self.user.tenant_id, flow_id=flow_id
        )
        actor = self.actor_manager.get_space_actor(
            await self.space_repo.get_space_access_facts(space_id)
        )
        if not actor.can_edit_retention():
            raise UnauthorizedException(
                "Only space admins can change a Flow's retention time",
                code="forbidden_action",
                context={
                    "resource_type": "flow",
                    "action": "update_retention",
                    "auth_layer": "domain_policy",
                },
            )

    async def purge_due_history(
        self,
        *,
        dry_run: bool,
        limit: int,
        space_id: UUID | None = None,
        flow_id: UUID | None = None,
    ) -> FlowRunHistoryPurgePublic:
        require_retention_manage(self.user)
        tenant_id = self.user.tenant_id
        if flow_id is not None:
            scope, scope_id = (
                FlowRunRetentionScope.FLOW,
                (
                    await self.repository.get_flow(tenant_id=tenant_id, flow_id=flow_id)
                ).scope_id,
            )
        elif space_id is not None:
            scope, scope_id = (
                FlowRunRetentionScope.SPACE,
                (
                    await self.repository.require_space(
                        tenant_id=tenant_id, space_id=space_id
                    )
                ),
            )
        else:
            scope, scope_id = FlowRunRetentionScope.ORGANIZATION, tenant_id
        result = await FlowRetentionRepository(
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
            scope=scope,
            candidate_count=result.candidate_count,
            purged_count=len(result.purged_run_ids),
            purged_run_ids=list(result.purged_run_ids),
            transcript_candidate_count=result.transcript_candidate_count,
            transcript_purged_count=result.transcript_purged_count,
            blocked=FlowRunHistoryPurgeBlockedPublic(
                undelivered_audit=result.blocked.skipped_undelivered_audit,
                unresolved_webhook=result.blocked.skipped_unresolved_webhook,
                legal_hold=result.blocked.skipped_legal_hold,
                counted_runs=result.blocked.counted_runs,
                complete=result.blocked.complete,
            ),
        )
        if not dry_run:
            await self.audit_service.log(
                tenant_id=self.user.tenant_id,
                user=self.user,
                action=ActionType.FLOW_RUN_HISTORY_PURGED,
                entity_type=self._entity_type(scope),
                entity_id=scope_id,
                description="Purged due Flow run history and expired unbound live transcripts.",
                metadata={
                    "scope": scope.value,
                    "scope_id": str(scope_id),
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
                "effective_policy": (
                    {"days": after.effective.effective_days}
                    if after.effective.effective_days is not None
                    else None
                ),
                "effective_source": after.effective.source,
            },
            required=True,
        )

    async def get_hold_review_limit(self) -> FlowRetentionHoldReviewLimit:
        require_retention_view(self.user)
        return await self.repository.get_hold_review_limit(
            tenant_id=self.user.tenant_id
        )

    async def replace_hold_review_limit(
        self, *, days: int | None
    ) -> FlowRetentionHoldReviewLimit:
        """The guardrail on legal holds belongs to the people who own the rules."""
        require_retention_manage(self.user)
        before, after = await self.repository.replace_hold_review_limit(
            tenant_id=self.user.tenant_id, days=days
        )
        if before != after:
            await self.audit_service.log(
                tenant_id=self.user.tenant_id,
                user=self.user,
                action=ActionType.FLOW_RUN_RETENTION_POLICY_CHANGED,
                entity_type=EntityType.TENANT_SETTINGS,
                entity_id=self.user.tenant_id,
                description="Changed the review limit for legal holds on Flow run history.",
                metadata={
                    "scope": FlowRunRetentionScope.ORGANIZATION.value,
                    "scope_id": str(self.user.tenant_id),
                    "setting": "hold_review_limit_days",
                    "previous_value": before.days,
                    "new_value": after.days,
                },
                required=True,
            )
        return after

    @staticmethod
    def _audit_policy(
        policy: FlowRunRetentionPolicy | None,
    ) -> dict[str, int] | None:
        if policy is None:
            return None
        return {"days": policy.days}

    @staticmethod
    def _entity_type(scope: FlowRunRetentionScope) -> EntityType:
        if scope is FlowRunRetentionScope.ORGANIZATION:
            return EntityType.TENANT_SETTINGS
        if scope is FlowRunRetentionScope.SPACE:
            return EntityType.SPACE
        return EntityType.FLOW
