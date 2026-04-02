"""Repository for AI Builder sessions and plans."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import cast, insert, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.flow_tables import BuilderPlans, BuilderSessions
from intric.flows.ai_builder.ai_builder_models import (
    BuilderPlan,
    BuilderSession,
    ConversationMessage,
    FlowDraftSpecCore,
    PlannerPlanEnvelope,
    PlanStatus,
    SessionStatus,
    TargetKind,
)
from intric.main.exceptions import NotFoundException


class AIBuilderRepository:
    """Persistence layer for builder sessions and plans."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @contextlib.asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        """Ensure a transaction is active.

        Inside SSE generators the DI transaction has already committed,
        so we need to open a new one. If a transaction is already active
        (normal request flow), this is a no-op.
        """
        if self.session.in_transaction():
            yield
        else:
            async with self.session.begin():
                yield

    # ---------------------------------------------------------------------------
    # Sessions
    # ---------------------------------------------------------------------------

    async def create_session(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        actor_user_id: UUID,
        target_kind: TargetKind,
        flow_id: UUID | None = None,
    ) -> BuilderSession:
        async with self._transaction():
            stmt = (
                insert(BuilderSessions)
                .values(
                    tenant_id=tenant_id,
                    space_id=space_id,
                    flow_id=flow_id,
                    target_kind=target_kind.value,
                    status=SessionStatus.CHATTING.value,
                    actor_user_id=actor_user_id,
                    conversation=[],
                )
                .returning(BuilderSessions)
            )
            row = (await self.session.execute(stmt)).scalar_one()
            return _session_from_row(row)

    async def find_latest_resumable_session(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        space_id: UUID,
        target_kind: TargetKind,
        flow_id: UUID | None,
    ) -> BuilderSession | None:
        async with self._transaction():
            stmt = (
                select(BuilderSessions)
                .where(
                    BuilderSessions.tenant_id == tenant_id,
                    BuilderSessions.actor_user_id == actor_user_id,
                    BuilderSessions.space_id == space_id,
                    BuilderSessions.target_kind == target_kind.value,
                    BuilderSessions.status.in_([
                        SessionStatus.CHATTING.value,
                        SessionStatus.AWAITING_APPROVAL.value,
                        SessionStatus.APPLYING.value,
                    ]),
                    BuilderSessions.flow_id.is_(None)
                    if flow_id is None
                    else BuilderSessions.flow_id == flow_id,
                )
                .order_by(BuilderSessions.updated_at.desc(), BuilderSessions.created_at.desc())
            )
            row = (await self.session.execute(stmt)).scalars().first()
            return _session_from_row(row) if row is not None else None

    async def list_sessions_for_user(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        limit: int = 20,
    ) -> list[BuilderSession]:
        async with self._transaction():
            stmt = (
                select(BuilderSessions)
                .where(
                    BuilderSessions.tenant_id == tenant_id,
                    BuilderSessions.actor_user_id == actor_user_id,
                )
                .order_by(BuilderSessions.updated_at.desc(), BuilderSessions.created_at.desc())
                .limit(limit)
            )
            rows = (await self.session.execute(stmt)).scalars().all()
            return [_session_from_row(row) for row in rows]

    async def cancel_session(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
    ) -> None:
        async with self._transaction():
            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                )
                .values(
                    status=SessionStatus.CANCELLED.value,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await self.session.execute(stmt)

    async def cancel_matching_active_sessions(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        space_id: UUID,
        target_kind: TargetKind,
        flow_id: UUID | None,
    ) -> list[UUID]:
        async with self._transaction():
            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.tenant_id == tenant_id,
                    BuilderSessions.actor_user_id == actor_user_id,
                    BuilderSessions.space_id == space_id,
                    BuilderSessions.target_kind == target_kind.value,
                    BuilderSessions.status.in_([
                        SessionStatus.CHATTING.value,
                        SessionStatus.AWAITING_APPROVAL.value,
                        SessionStatus.APPLYING.value,
                    ]),
                    BuilderSessions.flow_id.is_(None)
                    if flow_id is None
                    else BuilderSessions.flow_id == flow_id,
                )
                .values(
                    status=SessionStatus.CANCELLED.value,
                    updated_at=datetime.now(timezone.utc),
                )
                .returning(BuilderSessions.id)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())

    async def get_session(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
    ) -> BuilderSession:
        async with self._transaction():
            stmt = select(BuilderSessions).where(
                BuilderSessions.id == session_id,
                BuilderSessions.tenant_id == tenant_id,
            )
            row = (await self.session.execute(stmt)).scalar_one_or_none()
            if row is None:
                raise NotFoundException("Builder session not found.")
            return _session_from_row(row)

    async def update_session_status(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        status: SessionStatus,
    ) -> None:
        async with self._transaction():
            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                )
                .values(
                    status=status.value,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await self.session.execute(stmt)

    async def update_session_conversation(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        conversation: list[ConversationMessage],
    ) -> None:
        async with self._transaction():
            serialized = [msg.model_dump(mode="json") for msg in conversation]
            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                )
                .values(
                    conversation=serialized,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await self.session.execute(stmt)

    async def append_session_messages(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        conversation: list[ConversationMessage],
    ) -> None:
        if not conversation:
            return

        async with self._transaction():
            serialized = [msg.model_dump(mode="json") for msg in conversation]
            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                )
                .values(
                    conversation=BuilderSessions.conversation.op("||")(
                        cast(serialized, JSONB)
                    ),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await self.session.execute(stmt)

    async def update_session_latest_plan(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        plan_id: UUID,
    ) -> None:
        async with self._transaction():
            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                )
                .values(
                    latest_plan_id=plan_id,
                    status=SessionStatus.AWAITING_APPROVAL.value,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await self.session.execute(stmt)

    async def update_session_flow_id(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        flow_id: UUID,
    ) -> None:
        async with self._transaction():
            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                )
                .values(
                    flow_id=flow_id,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await self.session.execute(stmt)

    # ---------------------------------------------------------------------------
    # Plans
    # ---------------------------------------------------------------------------

    async def create_plan(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        spec: FlowDraftSpecCore,
        envelope: PlannerPlanEnvelope,
        edit_result_json: dict | None = None,
    ) -> BuilderPlan:
        async with self._transaction():
            spec_hash = spec.spec_hash()
            values: dict = {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "status": PlanStatus.PROPOSED.value,
                "spec_json": spec.model_dump(mode="json"),
                "spec_hash": spec_hash,
                "envelope_json": envelope.model_dump(mode="json"),
            }
            if edit_result_json is not None:
                values["edit_result_json"] = edit_result_json
            stmt = (
                insert(BuilderPlans)
                .values(**values)
                .returning(BuilderPlans)
            )
            row = (await self.session.execute(stmt)).scalar_one()
            return _plan_from_row(row)

    async def get_plan(
        self,
        *,
        plan_id: UUID,
        tenant_id: UUID,
    ) -> BuilderPlan:
        async with self._transaction():
            stmt = select(BuilderPlans).where(
                BuilderPlans.id == plan_id,
                BuilderPlans.tenant_id == tenant_id,
            )
            row = (await self.session.execute(stmt)).scalar_one_or_none()
            if row is None:
                raise NotFoundException("Builder plan not found.")
            return _plan_from_row(row)

    async def list_session_plans(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
    ) -> list[BuilderPlan]:
        async with self._transaction():
            stmt = (
                select(BuilderPlans)
                .where(
                    BuilderPlans.session_id == session_id,
                    BuilderPlans.tenant_id == tenant_id,
                )
                .order_by(BuilderPlans.created_at.desc())
            )
            rows = (await self.session.execute(stmt)).scalars().all()
            return [_plan_from_row(row) for row in rows]

    async def update_plan_status(
        self,
        *,
        plan_id: UUID,
        tenant_id: UUID,
        status: PlanStatus,
    ) -> None:
        async with self._transaction():
            stmt = (
                update(BuilderPlans)
                .where(
                    BuilderPlans.id == plan_id,
                    BuilderPlans.tenant_id == tenant_id,
                )
                .values(
                    status=status.value,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await self.session.execute(stmt)

    async def supersede_existing_plans(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
    ) -> None:
        """Mark all proposed plans for this session as superseded."""
        async with self._transaction():
            stmt = (
                update(BuilderPlans)
                .where(
                    BuilderPlans.session_id == session_id,
                    BuilderPlans.tenant_id == tenant_id,
                    BuilderPlans.status == PlanStatus.PROPOSED.value,
                )
                .values(
                    status=PlanStatus.SUPERSEDED.value,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await self.session.execute(stmt)


# ---------------------------------------------------------------------------
# Row → domain model converters
# ---------------------------------------------------------------------------


def _session_from_row(row: Any) -> BuilderSession:
    """Convert a DB row/mapping to a BuilderSession domain model."""
    # Handle both ORM objects and mappings
    if hasattr(row, "__getitem__"):
        data = dict(row)
    else:
        data = {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "space_id": row.space_id,
            "flow_id": row.flow_id,
            "target_kind": row.target_kind,
            "status": row.status,
            "actor_user_id": row.actor_user_id,
            "conversation": row.conversation,
            "latest_plan_id": row.latest_plan_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    conv_raw = data.get("conversation", [])
    conversation = [
        ConversationMessage.model_validate(msg) if isinstance(msg, dict) else msg
        for msg in (conv_raw or [])
    ]

    return BuilderSession(
        id=data["id"],
        tenant_id=data["tenant_id"],
        space_id=data["space_id"],
        flow_id=data.get("flow_id"),
        target_kind=TargetKind(data["target_kind"]),
        status=SessionStatus(data["status"]),
        actor_user_id=data["actor_user_id"],
        conversation=conversation,
        latest_plan_id=data.get("latest_plan_id"),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


def _plan_from_row(row: Any) -> BuilderPlan:
    """Convert a DB row/mapping to a BuilderPlan domain model."""
    if hasattr(row, "__getitem__"):
        data = dict(row)
    else:
        data = {
            "id": row.id,
            "session_id": row.session_id,
            "tenant_id": row.tenant_id,
            "status": row.status,
            "spec_json": row.spec_json,
            "spec_hash": row.spec_hash,
            "envelope_json": row.envelope_json,
            "edit_result_json": getattr(row, "edit_result_json", None),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    spec = FlowDraftSpecCore.model_validate(data["spec_json"])
    envelope = PlannerPlanEnvelope.model_validate(data["envelope_json"])

    return BuilderPlan(
        id=data["id"],
        session_id=data["session_id"],
        tenant_id=data["tenant_id"],
        status=PlanStatus(data["status"]),
        spec=spec,
        spec_hash=data["spec_hash"],
        envelope=envelope,
        edit_result_json=data.get("edit_result_json"),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )
