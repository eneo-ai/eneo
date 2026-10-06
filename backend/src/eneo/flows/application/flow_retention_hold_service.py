from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from eneo.audit.application.audit_metadata import actor_snapshot
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_models import audit_actor_for
from eneo.data_retention.infrastructure.retention_lock import (
    RetentionSubject,
    acquire_exclusive,
)
from eneo.flows.application.flow_retention_authz import (
    require_retention_holds,
    require_retention_view,
)
from eneo.flows.domain.flow_retention_hold import (
    FLOW_RETENTION_HOLD_ALREADY_RELEASED_CODE,
    FLOW_RETENTION_HOLD_END_NOT_IN_FUTURE_CODE,
    FLOW_RETENTION_HOLD_NOT_ACTIVE_CODE,
    FLOW_RETENTION_HOLD_REVIEW_NOT_LATER_CODE,
    FLOW_RETENTION_HOLD_REVIEW_OUT_OF_RANGE_CODE,
    FLOW_RETENTION_HOLD_RUN_NOT_IN_FLOW_CODE,
    FlowRetentionHold,
    FlowRetentionHoldCreateRequest,
    FlowRetentionHoldExtendReviewRequest,
    FlowRetentionHoldPage,
    FlowRetentionHoldPlacement,
    FlowRetentionHoldStatusFilter,
)
from eneo.flows.infrastructure.flow_retention_hold_repo import (
    FlowRetentionHoldRepository,
)
from eneo.main.exceptions import BadRequestException, ConflictException
from eneo.users.user import UserInDB


class FlowRetentionHoldService:
    """Places, lists, extends the review of, and releases legal holds.

    Every stop of retention names who, why, when and until when: a hold needs a
    reason and a review date, a release or extension needs a reason, and each
    change writes one required audit row in its transaction. Changes take the
    retention lock EXCLUSIVE before reading anything, so they wait for open
    deletions and a deletion never runs on an older hold state.
    """

    def __init__(
        self,
        *,
        user: UserInDB,
        repository: FlowRetentionHoldRepository,
        audit_service: AuditService,
    ) -> None:
        self.user = user
        self.repository = repository
        self.audit_service = audit_service

    async def list_holds(
        self,
        *,
        status: FlowRetentionHoldStatusFilter,
        flow_id: UUID | None,
        limit: int,
        offset: int,
    ) -> FlowRetentionHoldPage:
        require_retention_view(self.user)
        return await self.repository.list(
            tenant_id=self.user.tenant_id,
            status=status,
            flow_id=flow_id,
            limit=limit,
            offset=offset,
        )

    async def place(
        self, request: FlowRetentionHoldCreateRequest
    ) -> FlowRetentionHoldPlacement:
        require_retention_holds(self.user)
        now = datetime.now(timezone.utc)
        if request.ends_at is not None and request.ends_at <= now:
            raise BadRequestException(
                "The end date of a legal hold must be in the future.",
                code=FLOW_RETENTION_HOLD_END_NOT_IN_FUTURE_CODE,
            )
        tenant_id = self.user.tenant_id
        await acquire_exclusive(self.repository.session, RetentionSubject.FLOW_HISTORY)
        await self._require_review_in_range(request.review_by, now=now)
        await self.repository.require_flow(tenant_id=tenant_id, flow_id=request.flow_id)
        run_ids = list(dict.fromkeys(request.run_ids)) if request.run_ids else None
        if run_ids is not None:
            found = await self.repository.runs_of_flow(
                tenant_id=tenant_id, flow_id=request.flow_id, run_ids=run_ids
            )
            if len(found) != len(run_ids):
                raise BadRequestException(
                    "Every held run must be a run of the chosen Flow.",
                    code=FLOW_RETENTION_HOLD_RUN_NOT_IN_FLOW_CODE,
                )
        actor, user_id = self._actor()
        hold_ids = await self.repository.insert(
            tenant_id=tenant_id,
            flow_id=request.flow_id,
            run_ids=run_ids if run_ids is not None else [None],
            reason=request.reason,
            review_by=request.review_by,
            ends_at=request.ends_at,
            actor=actor,
            user_id=user_id,
        )
        holds = await self.repository.get_many(tenant_id=tenant_id, hold_ids=hold_ids)
        await self.audit_service.log(
            tenant_id=tenant_id,
            user=self.user,
            action=ActionType.FLOW_RETENTION_HOLD_PLACED,
            entity_type=EntityType.FLOW,
            entity_id=request.flow_id,
            description="Placed a legal hold on Flow run history.",
            metadata={
                "hold_ids": [str(hold_id) for hold_id in hold_ids],
                "flow_id": str(request.flow_id),
                "scope": "flow" if run_ids is None else "run",
                "run_ids": [str(run_id) for run_id in run_ids or []],
                "reason": request.reason,
                "review_by": request.review_by.isoformat(),
                "ends_at": (
                    request.ends_at.isoformat() if request.ends_at is not None else None
                ),
            },
            required=True,
        )
        return FlowRetentionHoldPlacement(holds=holds)

    async def extend_review(
        self, *, hold_id: UUID, request: FlowRetentionHoldExtendReviewRequest
    ) -> FlowRetentionHold:
        require_retention_holds(self.user)
        tenant_id = self.user.tenant_id
        await acquire_exclusive(self.repository.session, RetentionSubject.FLOW_HISTORY)
        hold = await self.repository.lock_for_change(
            tenant_id=tenant_id, hold_id=hold_id
        )
        if not hold.active:
            raise ConflictException(
                "Only an active legal hold can have its review extended.",
                code=FLOW_RETENTION_HOLD_NOT_ACTIVE_CODE,
            )
        if request.review_by <= hold.review_by:
            raise BadRequestException(
                "The new review date must be later than the current one.",
                code=FLOW_RETENTION_HOLD_REVIEW_NOT_LATER_CODE,
            )
        await self._require_review_in_range(
            request.review_by, now=datetime.now(timezone.utc)
        )
        await self.repository.set_review_by(
            tenant_id=tenant_id, hold_id=hold_id, review_by=request.review_by
        )
        [extended] = await self.repository.get_many(
            tenant_id=tenant_id, hold_ids=[hold_id]
        )
        await self.audit_service.log(
            tenant_id=tenant_id,
            user=self.user,
            action=ActionType.FLOW_RETENTION_HOLD_REVIEW_EXTENDED,
            entity_type=EntityType.FLOW,
            entity_id=hold.flow_id,
            description="Extended the review date of a legal hold on Flow run history.",
            metadata={
                **self._hold_metadata(hold),
                "previous_review_by": hold.review_by.isoformat(),
                "review_by": request.review_by.isoformat(),
                "reason": request.reason,
            },
            required=True,
        )
        return extended

    async def release(self, *, hold_id: UUID, reason: str) -> FlowRetentionHold:
        require_retention_holds(self.user)
        tenant_id = self.user.tenant_id
        await acquire_exclusive(self.repository.session, RetentionSubject.FLOW_HISTORY)
        hold = await self.repository.lock_for_change(
            tenant_id=tenant_id, hold_id=hold_id
        )
        if hold.released_at is not None:
            raise ConflictException(
                "This legal hold is already released.",
                code=FLOW_RETENTION_HOLD_ALREADY_RELEASED_CODE,
            )
        actor, user_id = self._actor()
        await self.repository.release(
            tenant_id=tenant_id,
            hold_id=hold_id,
            reason=reason,
            actor=actor,
            user_id=user_id,
        )
        [released] = await self.repository.get_many(
            tenant_id=tenant_id, hold_ids=[hold_id]
        )
        await self.audit_service.log(
            tenant_id=tenant_id,
            user=self.user,
            action=ActionType.FLOW_RETENTION_HOLD_RELEASED,
            entity_type=EntityType.FLOW,
            entity_id=released.flow_id,
            description="Released a legal hold on Flow run history.",
            metadata={**self._hold_metadata(hold), "release_reason": reason},
            required=True,
        )
        return released

    async def _require_review_in_range(
        self, review_by: datetime, *, now: datetime
    ) -> None:
        max_days = await self.repository.max_review_days(tenant_id=self.user.tenant_id)
        if not now < review_by <= now + timedelta(days=max_days):
            raise BadRequestException(
                "The review date must be in the future and at most "
                f"{max_days} days ahead.",
                code=FLOW_RETENTION_HOLD_REVIEW_OUT_OF_RANGE_CODE,
            )

    @staticmethod
    def _hold_metadata(hold: FlowRetentionHold) -> dict[str, Any]:
        return {
            "hold_id": str(hold.id),
            "flow_id": str(hold.flow_id),
            "scope": hold.scope,
            "flow_run_id": (
                str(hold.flow_run_id) if hold.flow_run_id is not None else None
            ),
        }

    def _actor(self) -> tuple[dict[str, Any], UUID | None]:
        user_id, _ = audit_actor_for(self.user)
        return actor_snapshot(self.user), user_id
