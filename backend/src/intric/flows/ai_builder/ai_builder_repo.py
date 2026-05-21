"""Repository for AI Builder sessions and plans."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, TypedDict, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import TypeAdapter
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.flow_tables import (
    BuilderPlans,
    BuilderSessionFiles,
    BuilderSessions,
)
from intric.database.tables.tenant_table import Tenants
from intric.flows.ai_builder.ai_builder_conversation_compaction import (
    compact_ai_builder_conversation,
)
from intric.flows.ai_builder.ai_builder_error_contract import AIBuilderErrorCode
from intric.flows.ai_builder.ai_builder_models import (
    BuilderPlan,
    BuilderPlanEditResult,
    BuilderSession,
    ConversationMessage,
    FlowDraftSpecCore,
    PlannerPlanEnvelope,
    PlanStatus,
    SessionStatus,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_session_transitions import (
    ensure_valid_session_status_transition,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningState,
)
from intric.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
    carry_forward_persisted_planner_state,
)
from intric.flows.flow_resource_bindings import LocalResourceBinding
from intric.main.exceptions import BadRequestException, NotFoundException

if TYPE_CHECKING:
    from intric.flows.flow import Flow

_LOCAL_RESOURCE_BINDING_ADAPTER = TypeAdapter(LocalResourceBinding)


class AIBuilderRepository:
    """Persistence layer for builder sessions and plans."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @contextlib.asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[None, None]:
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

    @contextlib.asynccontextmanager
    async def savepoint(self) -> AsyncGenerator[None, None]:
        """Yield a SAVEPOINT-scoped nested transaction.

        Guarantees that writes performed inside the block either all
        land together or are all rolled back, independent of whether
        the caller owns an outer transaction. Used by turn orchestrators
        that must unify several repo writes into one atomic unit.
        """
        async with self._transaction():
            async with self.session.begin_nested():
                yield

    # ---------------------------------------------------------------------------
    # Sessions
    # ---------------------------------------------------------------------------

    async def acquire_session_creation_lock(self, *, tenant_id: UUID) -> None:
        async with self._transaction():
            await self.session.execute(
                select(Tenants.id).where(Tenants.id == tenant_id).with_for_update()
            )

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
                    BuilderSessions.status.in_(
                        [
                            SessionStatus.CHATTING.value,
                            SessionStatus.AWAITING_APPROVAL.value,
                            SessionStatus.APPLYING.value,
                        ]
                    ),
                    BuilderSessions.flow_id.is_(None)
                    if flow_id is None
                    else BuilderSessions.flow_id == flow_id,
                )
                .order_by(
                    BuilderSessions.updated_at.desc(), BuilderSessions.created_at.desc()
                )
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
                .order_by(
                    BuilderSessions.updated_at.desc(), BuilderSessions.created_at.desc()
                )
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
            detach_stmt = sa.delete(BuilderSessionFiles).where(
                BuilderSessionFiles.session_id == session_id,
                BuilderSessionFiles.tenant_id == tenant_id,
            )
            await self.session.execute(detach_stmt)
            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                )
                .values(
                    status=SessionStatus.CANCELLED.value,
                    active_request_id=None,
                    lock_token=None,
                    locked_at=None,
                    lock_expires_at=None,
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
            session_ids_stmt = select(BuilderSessions.id).where(
                BuilderSessions.tenant_id == tenant_id,
                BuilderSessions.actor_user_id == actor_user_id,
                BuilderSessions.space_id == space_id,
                BuilderSessions.target_kind == target_kind.value,
                BuilderSessions.status.in_(
                    [
                        SessionStatus.CHATTING.value,
                        SessionStatus.AWAITING_APPROVAL.value,
                        SessionStatus.APPLYING.value,
                    ]
                ),
                BuilderSessions.flow_id.is_(None)
                if flow_id is None
                else BuilderSessions.flow_id == flow_id,
            )
            session_ids = list(
                (await self.session.execute(session_ids_stmt)).scalars().all()
            )
            if session_ids:
                detach_stmt = sa.delete(BuilderSessionFiles).where(
                    BuilderSessionFiles.session_id.in_(session_ids),
                    BuilderSessionFiles.tenant_id == tenant_id,
                )
                await self.session.execute(detach_stmt)

            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.tenant_id == tenant_id,
                    BuilderSessions.actor_user_id == actor_user_id,
                    BuilderSessions.space_id == space_id,
                    BuilderSessions.target_kind == target_kind.value,
                    BuilderSessions.status.in_(
                        [
                            SessionStatus.CHATTING.value,
                            SessionStatus.AWAITING_APPROVAL.value,
                            SessionStatus.APPLYING.value,
                        ]
                    ),
                    BuilderSessions.flow_id.is_(None)
                    if flow_id is None
                    else BuilderSessions.flow_id == flow_id,
                )
                .values(
                    status=SessionStatus.CANCELLED.value,
                    active_request_id=None,
                    lock_token=None,
                    locked_at=None,
                    lock_expires_at=None,
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

    async def attach_session_files(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        file_ids: list[UUID],
    ) -> None:
        if not file_ids:
            return

        async with self._transaction():
            rows = [
                {
                    "session_id": session_id,
                    "file_id": file_id,
                    "tenant_id": tenant_id,
                }
                for file_id in dict.fromkeys(file_ids)
            ]
            stmt = pg_insert(BuilderSessionFiles).values(rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["session_id", "file_id"])
            await self.session.execute(stmt)

    async def list_session_file_ids(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
    ) -> list[UUID]:
        async with self._transaction():
            stmt = (
                select(BuilderSessionFiles.file_id)
                .where(
                    BuilderSessionFiles.session_id == session_id,
                    BuilderSessionFiles.tenant_id == tenant_id,
                )
                .order_by(BuilderSessionFiles.created_at.asc())
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())

    async def detach_session_file(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        file_id: UUID,
    ) -> None:
        async with self._transaction():
            stmt = sa.delete(BuilderSessionFiles).where(
                BuilderSessionFiles.session_id == session_id,
                BuilderSessionFiles.tenant_id == tenant_id,
                BuilderSessionFiles.file_id == file_id,
            )
            await self.session.execute(stmt)

    async def detach_session_files_for_sessions(
        self,
        *,
        session_ids: list[UUID],
        tenant_id: UUID,
    ) -> None:
        if not session_ids:
            return
        async with self._transaction():
            stmt = sa.delete(BuilderSessionFiles).where(
                BuilderSessionFiles.session_id.in_(session_ids),
                BuilderSessionFiles.tenant_id == tenant_id,
            )
            await self.session.execute(stmt)

    async def update_session_status(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        status: SessionStatus,
        lease: SessionSendLease,
    ) -> None:
        await self._update_session_status(
            session_id=session_id,
            tenant_id=tenant_id,
            status=status,
            lease=lease,
        )

    async def update_session_status_without_send_lease(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        status: SessionStatus,
    ) -> None:
        await self._update_session_status(
            session_id=session_id,
            tenant_id=tenant_id,
            status=status,
            lease=None,
        )

    async def _update_session_status(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        status: SessionStatus,
        lease: SessionSendLease | None,
    ) -> None:
        async with self._transaction():
            current_stmt = select(BuilderSessions.status).where(
                BuilderSessions.id == session_id,
                BuilderSessions.tenant_id == tenant_id,
            )
            current_value = (
                await self.session.execute(current_stmt)
            ).scalar_one_or_none()
            if current_value is None:
                raise NotFoundException("Builder session not found.")
            ensure_valid_session_status_transition(
                current=SessionStatus(current_value),
                next_status=status,
            )
            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                    *(_lease_filters(lease) if lease is not None else ()),
                )
                .values(
                    status=status.value,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            if lease is not None:
                updated_session_id = await self.session.scalar(
                    stmt.returning(BuilderSessions.id)
                )
            else:
                await self.session.execute(stmt)
                updated_session_id = session_id
            if updated_session_id is None:
                raise BadRequestException(
                    "The AI Builder session lease was lost while updating session status.",
                    code=AIBuilderErrorCode.SESSION_SEND_LEASE_LOST.value,
                )

    async def update_session_conversation(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        conversation: list[ConversationMessage],
        lease: SessionSendLease,
    ) -> None:
        async with self._transaction():
            compacted = compact_ai_builder_conversation(conversation)
            serialized = [msg.model_dump(mode="json") for msg in compacted]
            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                    *_lease_filters(lease),
                )
                .values(
                    conversation=serialized,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            updated_session_id = await self.session.scalar(
                stmt.returning(BuilderSessions.id)
            )
            if updated_session_id is None:
                raise BadRequestException(
                    "The AI Builder session lease was lost while updating conversation state.",
                    code=AIBuilderErrorCode.SESSION_SEND_LEASE_LOST.value,
                )

    async def append_session_messages(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        conversation: list[ConversationMessage],
        lease: SessionSendLease,
    ) -> list[ConversationMessage]:
        """Persist `conversation` messages and return the compacted list that was stored.

        Returning the compacted list lets callers derive side-effects
        (notably `PlanningState`) from the same view that will be read
        back on the next turn. Without this, long sessions could save a
        state whose `evidence.conversation_message_ids` referred to
        messages that had been compacted away before persist.
        """
        if not conversation:
            return []

        async with self._transaction():
            committed_file_ids: list[UUID] = []
            for message in conversation:
                if message.role != "user":
                    continue
                metadata = (
                    message.metadata if isinstance(message.metadata, dict) else None
                )
                raw_file_ids = (
                    cast(list[Any] | None, metadata.get("file_ids"))
                    if metadata
                    else None
                )
                if not isinstance(raw_file_ids, list):
                    continue
                for raw_file_id in raw_file_ids:
                    try:
                        committed_file_ids.append(
                            raw_file_id
                            if isinstance(raw_file_id, UUID)
                            else UUID(str(cast(object, raw_file_id)))
                        )
                    except (TypeError, ValueError):
                        continue

            stmt = select(BuilderSessions).where(
                BuilderSessions.id == session_id,
                BuilderSessions.tenant_id == tenant_id,
                *_lease_filters(lease),
            )
            row = (await self.session.execute(stmt)).scalar_one_or_none()
            if row is None:
                raise BadRequestException(
                    "The AI Builder session lease was lost while appending conversation messages.",
                    code=AIBuilderErrorCode.SESSION_SEND_LEASE_LOST.value,
                )

            existing = _session_from_row(row).conversation
            compacted = compact_ai_builder_conversation([*existing, *conversation])
            serialized = [msg.model_dump(mode="json") for msg in compacted]
            update_stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                    *_lease_filters(lease),
                )
                .values(
                    conversation=serialized,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            updated_session_id = await self.session.scalar(
                update_stmt.returning(BuilderSessions.id)
            )
            if updated_session_id is None:
                raise BadRequestException(
                    "The AI Builder session lease was lost while saving conversation messages.",
                    code=AIBuilderErrorCode.SESSION_SEND_LEASE_LOST.value,
                )
            if committed_file_ids:
                rows = [
                    {
                        "session_id": session_id,
                        "file_id": file_id,
                        "tenant_id": tenant_id,
                    }
                    for file_id in dict.fromkeys(committed_file_ids)
                ]
                stmt = pg_insert(BuilderSessionFiles).values(rows)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["session_id", "file_id"]
                )
                await self.session.execute(stmt)

            return compacted

    async def update_session_latest_plan(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        plan_id: UUID,
        lease: SessionSendLease,
    ) -> None:
        await self._update_session_latest_plan(
            session_id=session_id,
            tenant_id=tenant_id,
            plan_id=plan_id,
            lease=lease,
        )

    async def update_session_latest_plan_without_send_lease(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        plan_id: UUID,
    ) -> None:
        """Replace latest plan during user lifecycle revision and clear expired locks."""
        await self._update_session_latest_plan(
            session_id=session_id,
            tenant_id=tenant_id,
            plan_id=plan_id,
            lease=None,
        )

    async def _update_session_latest_plan(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        plan_id: UUID,
        lease: SessionSendLease | None,
    ) -> None:
        async with self._transaction():
            current_stmt = select(
                BuilderSessions.status,
                BuilderSessions.active_request_id,
                BuilderSessions.lock_token,
                BuilderSessions.lock_expires_at,
            ).where(
                BuilderSessions.id == session_id,
                BuilderSessions.tenant_id == tenant_id,
            )
            current_row = (await self.session.execute(current_stmt)).one_or_none()
            if current_row is None:
                raise NotFoundException("Builder session not found.")
            (
                current_status_value,
                active_request_id,
                lock_token,
                lock_expires_at,
            ) = current_row
            current_status = SessionStatus(current_status_value)
            now = datetime.now(timezone.utc)

            if lease is not None:
                ensure_valid_session_status_transition(
                    current=current_status,
                    next_status=SessionStatus.AWAITING_APPROVAL,
                )
                where_clauses = [
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                    *_lease_filters(lease),
                ]
                values = {
                    "latest_plan_id": plan_id,
                    "status": SessionStatus.AWAITING_APPROVAL.value,
                    "updated_at": now,
                }
            else:
                if current_status != SessionStatus.AWAITING_APPROVAL:
                    raise BadRequestException(
                        "Can only revise plans when the session is awaiting approval.",
                        code=AIBuilderErrorCode.INVALID_SESSION_TRANSITION.value,
                    )
                lock_is_set = active_request_id is not None or lock_token is not None
                lock_is_expired = lock_expires_at is not None and lock_expires_at <= now
                if lock_is_set and not lock_is_expired:
                    raise BadRequestException(
                        "An active send is currently in progress for this session.",
                        code=AIBuilderErrorCode.SESSION_SEND_IN_PROGRESS.value,
                    )
                expired_lock_is_available = sa.and_(
                    BuilderSessions.lock_expires_at.is_not(None),
                    BuilderSessions.lock_expires_at <= sa.func.now(),
                )
                lock_is_available = sa.or_(
                    sa.and_(
                        BuilderSessions.active_request_id.is_(None),
                        BuilderSessions.lock_token.is_(None),
                    ),
                    expired_lock_is_available,
                )
                where_clauses = [
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                    BuilderSessions.status == SessionStatus.AWAITING_APPROVAL.value,
                    # Recheck lock availability in the UPDATE so a fresh claim between
                    # the precheck and write cannot be cleared by this lifecycle update.
                    lock_is_available,
                ]
                values = {
                    "latest_plan_id": plan_id,
                    "active_request_id": None,
                    "lock_token": None,
                    "locked_at": None,
                    "lock_expires_at": None,
                    "updated_at": now,
                }

            stmt = update(BuilderSessions).where(*where_clauses).values(**values)
            updated_session_id = await self.session.scalar(
                stmt.returning(BuilderSessions.id)
            )
            if updated_session_id is None:
                if lease is not None:
                    raise BadRequestException(
                        "The AI Builder session lease was lost while recording the latest plan.",
                        code=AIBuilderErrorCode.SESSION_SEND_LEASE_LOST.value,
                    )
                raise BadRequestException(
                    "The latest plan could not be updated due to a concurrent session change.",
                    code=AIBuilderErrorCode.SESSION_LATEST_PLAN_UPDATE_CONFLICT.value,
                )

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

    async def claim_session_send(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        lease: SessionSendLease,
        lock_expires_at: datetime,
    ) -> bool:
        async with self._transaction():
            now = datetime.now(timezone.utc)
            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                    sa.or_(
                        BuilderSessions.active_request_id.is_(None),
                        BuilderSessions.lock_expires_at <= sa.func.now(),
                    ),
                    BuilderSessions.status.in_(
                        [
                            SessionStatus.CHATTING.value,
                            SessionStatus.AWAITING_APPROVAL.value,
                        ]
                    ),
                )
                .values(
                    active_request_id=lease.request_id,
                    lock_token=lease.lock_token,
                    locked_at=now,
                    lock_expires_at=lock_expires_at,
                    updated_at=now,
                )
                .returning(BuilderSessions.id)
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none() is not None

    async def refresh_session_send_lease(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        lease: SessionSendLease,
        lock_expires_at: datetime,
    ) -> bool:
        async with self._transaction():
            now = datetime.now(timezone.utc)
            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                    *_lease_filters(lease),
                )
                .values(
                    locked_at=now,
                    lock_expires_at=lock_expires_at,
                    updated_at=now,
                )
                .returning(BuilderSessions.id)
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none() is not None

    async def release_session_send(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        lease: SessionSendLease,
    ) -> None:
        async with self._transaction():
            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                    *_lease_filters(lease),
                )
                .values(
                    active_request_id=None,
                    lock_token=None,
                    locked_at=None,
                    lock_expires_at=None,
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
        resource_bindings: tuple[LocalResourceBinding, ...] = tuple(),
        edit_result: BuilderPlanEditResult | None = None,
    ) -> BuilderPlan:
        async with self._transaction():
            spec_hash = spec.spec_hash()
            values: dict[str, object] = {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "status": PlanStatus.PROPOSED.value,
                "spec_json": spec.model_dump(mode="json"),
                "spec_hash": spec_hash,
                "envelope_json": _envelope_json_for_storage(envelope),
                "resource_bindings_json": _resource_bindings_json_for_storage(
                    resource_bindings
                ),
            }
            if edit_result is not None:
                values["edit_result_json"] = edit_result.model_dump(
                    mode="json", exclude_none=True
                )
            stmt = insert(BuilderPlans).values(**values).returning(BuilderPlans)
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
    # Planning state (jsonb-discipline: enforced writes + reads)
    # ---------------------------------------------------------------------------

    async def save_planning_state(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        state: PlanningState,
        base_version: int | None = None,
    ) -> int:
        """Persist the full `PlanningState` snapshot and return the new version.

        The column values are sourced from `_planning_state_for_storage`,
        so a container mutation that bypassed Pydantic's field validator
        raises at serialization time rather than landing as drifted
        JSONB. The version counter is incremented atomically via the
        column expression so concurrent turns cannot collide on read-
        modify-write.

        When `base_version` is provided the UPDATE filter additionally
        requires the row's current `planning_state_version` to equal
        it. If the row moved on (concurrent writer committed in
        between), the UPDATE matches zero rows and this raises
        `BadRequestException(code=AIBuilderErrorCode.PLANNING_STATE_VERSION_MISMATCH)`.
        Callers should reload the state and retry with the fresh
        version. When `base_version` is `None` the save is
        unconditional (last-writer-wins).

        Raises `NotFoundException` when `(session_id, tenant_id)` does
        not match a builder session — the caller misrouted the write.
        """
        column_values = _planning_state_for_storage(state)
        async with self._transaction():
            where_clauses = [
                BuilderSessions.id == session_id,
                BuilderSessions.tenant_id == tenant_id,
            ]
            if base_version is not None:
                where_clauses.append(
                    BuilderSessions.planning_state_version == base_version
                )
            stmt = (
                update(BuilderSessions)
                .where(*where_clauses)
                .values(
                    planning_state_jsonb=column_values["planning_state_jsonb"],
                    planning_state_version=BuilderSessions.planning_state_version + 1,
                    planning_phase=column_values["planning_phase"],
                    architecture_hash=column_values["architecture_hash"],
                    planning_state_updated_at=column_values[
                        "planning_state_updated_at"
                    ],
                    updated_at=datetime.now(timezone.utc),
                )
                .returning(BuilderSessions.planning_state_version)
            )
            result = await self.session.execute(stmt)
            new_version = result.scalar_one_or_none()
            if new_version is not None:
                return int(new_version)

            # Zero rows matched. Distinguish "row missing" (wrong
            # session/tenant) from "version moved on" (stale caller).
            exists_stmt = select(BuilderSessions.planning_state_version).where(
                BuilderSessions.id == session_id,
                BuilderSessions.tenant_id == tenant_id,
            )
            current_version = (
                await self.session.execute(exists_stmt)
            ).scalar_one_or_none()
            if current_version is None:
                raise NotFoundException(
                    f"Builder session {session_id} not found for tenant "
                    f"{tenant_id}; planning state not saved."
                )
            raise BadRequestException(
                (
                    f"Planning state version mismatch: expected base_version="
                    f"{base_version}, found {current_version}."
                ),
                code=AIBuilderErrorCode.PLANNING_STATE_VERSION_MISMATCH.value,
            )

    async def load_planning_state(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
    ) -> PlanningState | None:
        """Return the persisted `PlanningState` or `None` if never saved.

        Three distinct outcomes are kept separate so callers don't
        confuse a caller bug with a fresh session:

        - Row missing (wrong tenant or unknown session): raise
          `NotFoundException`.
        - Row present but `planning_state_jsonb IS NULL`: return `None`
          so the caller knows to stamp a new `PlanningState`.
        - Row present with a payload: return the validated model; any
          drifted JSONB raises Pydantic's `ValidationError` rather than
          silently reverting to a default.
        """
        async with self._transaction():
            stmt = select(
                BuilderSessions.id,
                BuilderSessions.planning_state_jsonb,
            ).where(
                BuilderSessions.id == session_id,
                BuilderSessions.tenant_id == tenant_id,
            )
            row = (await self.session.execute(stmt)).one_or_none()
            if row is None:
                raise NotFoundException(
                    f"Builder session {session_id} not found for tenant {tenant_id}."
                )
            payload = row[1]
            if payload is None:
                return None
            return PlanningState.model_validate(payload)

    # ---------------------------------------------------------------------------
    # Turn commit (atomic conversation + planning-state writes)
    # ---------------------------------------------------------------------------

    async def commit_turn(
        self,
        *,
        turn: SessionSendTurn,
        new_messages: list[ConversationMessage],
        flow: "Flow | None" = None,
        architecture_commit: ArchitectureCommit | None = None,
    ) -> int:
        """Append new conversation messages and save `PlanningState` atomically.

        The `PlanningState` is built from the compacted conversation
        that `append_session_messages` actually persisted, so
        `evidence.conversation_message_ids` always matches what the next
        turn will read back. Building it from the caller's pre-compaction
        list would drift once a session crosses the compaction
        threshold.

        When `architecture_commit` is provided, it is stamped on the
        rebuilt state inside the savepoint so the commit lands as one
        unit with the conversation append. This is the only path through
        which the planner's `commit_architecture` action persists to
        `PlanningState.architecture_commit`.

        `turn.base_planning_state_version` is forwarded to
        `save_planning_state`, so every active turn uses the same CAS
        version that the orchestrator validated against. A concurrent
        writer that moves the row between the guardrail's Python-side
        check and this UPDATE raises `planning_state_version_mismatch`
        instead of silently overwriting committed state.

        Returns the new `planning_state_version` (monotonically bumped
        by `save_planning_state`). Callers who don't need it can ignore
        the return value.

        Atomicity is enforced via a savepoint (`savepoint()`) rather
        than only the outer transaction, so even a caller that already
        holds an outer transaction and swallows the exception (such as
        a test fixture) still sees the inner writes rolled back as one
        unit.
        """
        async with self.savepoint():
            prior_state = await self.load_planning_state(
                session_id=turn.session_id, tenant_id=turn.tenant_id
            )
            persisted = await self.append_session_messages(
                session_id=turn.session_id,
                tenant_id=turn.tenant_id,
                conversation=new_messages,
                lease=turn.lease,
            )
            state = build_planning_state_from_conversation(persisted, flow=flow)
            if architecture_commit is not None:
                state.architecture_commit = architecture_commit
            carry_forward_persisted_planner_state(state, prior_state)
            return await self.save_planning_state(
                session_id=turn.session_id,
                tenant_id=turn.tenant_id,
                state=state,
                base_version=turn.base_planning_state_version,
            )


# ---------------------------------------------------------------------------
# Row → domain model converters
# ---------------------------------------------------------------------------


def _lease_filters(lease: SessionSendLease) -> tuple[Any, Any]:
    return (
        BuilderSessions.active_request_id == lease.request_id,
        BuilderSessions.lock_token == lease.lock_token,
    )


class _SessionRowData(TypedDict):
    id: UUID
    tenant_id: UUID
    space_id: UUID
    flow_id: UUID | None
    target_kind: str
    status: str
    actor_user_id: UUID
    conversation: list[object]
    active_request_id: UUID | None
    latest_plan_id: UUID | None
    planning_state_version: int
    created_at: datetime | None
    updated_at: datetime | None


class _PlanRowData(TypedDict):
    id: UUID
    session_id: UUID
    tenant_id: UUID
    status: str
    spec_json: dict[str, object]
    spec_hash: str
    envelope_json: dict[str, object]
    resource_bindings_json: list[dict[str, object]]
    edit_result_json: object | None
    created_at: datetime | None
    updated_at: datetime | None


def _session_row_data(row: Any) -> _SessionRowData:
    if hasattr(row, "__getitem__"):
        mapping = dict(cast(dict[str, object], row))
        conversation = cast(list[object], mapping.get("conversation", []) or [])
        return {
            "id": cast(UUID, mapping["id"]),
            "tenant_id": cast(UUID, mapping["tenant_id"]),
            "space_id": cast(UUID, mapping["space_id"]),
            "flow_id": cast(UUID | None, mapping.get("flow_id")),
            "target_kind": cast(str, mapping["target_kind"]),
            "status": cast(str, mapping["status"]),
            "actor_user_id": cast(UUID, mapping["actor_user_id"]),
            "conversation": conversation,
            "active_request_id": cast(UUID | None, mapping.get("active_request_id")),
            "latest_plan_id": cast(UUID | None, mapping.get("latest_plan_id")),
            "planning_state_version": int(
                cast(int, mapping.get("planning_state_version") or 0)
            ),
            "created_at": cast(datetime | None, mapping.get("created_at")),
            "updated_at": cast(datetime | None, mapping.get("updated_at")),
        }

    return {
        "id": cast(UUID, row.id),
        "tenant_id": cast(UUID, row.tenant_id),
        "space_id": cast(UUID, row.space_id),
        "flow_id": cast(UUID | None, row.flow_id),
        "target_kind": cast(str, row.target_kind),
        "status": cast(str, row.status),
        "actor_user_id": cast(UUID, row.actor_user_id),
        "conversation": cast(list[object], row.conversation or []),
        "active_request_id": cast(UUID | None, row.active_request_id),
        "latest_plan_id": cast(UUID | None, row.latest_plan_id),
        "planning_state_version": int(
            cast(int, getattr(row, "planning_state_version", 0) or 0)
        ),
        "created_at": cast(datetime | None, row.created_at),
        "updated_at": cast(datetime | None, row.updated_at),
    }


def _plan_row_data(row: Any) -> _PlanRowData:
    if hasattr(row, "__getitem__"):
        mapping = dict(cast(dict[str, object], row))
        return {
            "id": cast(UUID, mapping["id"]),
            "session_id": cast(UUID, mapping["session_id"]),
            "tenant_id": cast(UUID, mapping["tenant_id"]),
            "status": cast(str, mapping["status"]),
            "spec_json": cast(dict[str, object], mapping["spec_json"]),
            "spec_hash": cast(str, mapping["spec_hash"]),
            "envelope_json": cast(dict[str, object], mapping["envelope_json"]),
            "resource_bindings_json": cast(
                list[dict[str, object]], mapping["resource_bindings_json"]
            ),
            "edit_result_json": mapping.get("edit_result_json"),
            "created_at": cast(datetime | None, mapping.get("created_at")),
            "updated_at": cast(datetime | None, mapping.get("updated_at")),
        }

    return {
        "id": cast(UUID, row.id),
        "session_id": cast(UUID, row.session_id),
        "tenant_id": cast(UUID, row.tenant_id),
        "status": cast(str, row.status),
        "spec_json": cast(dict[str, object], row.spec_json),
        "spec_hash": cast(str, row.spec_hash),
        "envelope_json": cast(dict[str, object], row.envelope_json),
        "resource_bindings_json": cast(
            list[dict[str, object]], row.resource_bindings_json
        ),
        "edit_result_json": getattr(row, "edit_result_json", None),
        "created_at": cast(datetime | None, row.created_at),
        "updated_at": cast(datetime | None, row.updated_at),
    }


def _session_from_row(row: Any) -> BuilderSession:
    """Convert a DB row/mapping to a BuilderSession domain model."""
    data = _session_row_data(row)

    conversation: list[ConversationMessage] = []
    for msg in data["conversation"]:
        if isinstance(msg, ConversationMessage):
            conversation.append(msg)
        else:
            conversation.append(
                ConversationMessage.from_persisted(cast(dict[str, object], msg))
            )

    return BuilderSession(
        id=data["id"],
        tenant_id=data["tenant_id"],
        space_id=data["space_id"],
        flow_id=data["flow_id"],
        target_kind=TargetKind(data["target_kind"]),
        status=SessionStatus(data["status"]),
        actor_user_id=data["actor_user_id"],
        conversation=conversation,
        latest_plan_id=data["latest_plan_id"],
        planning_state_version=data["planning_state_version"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


def _envelope_json_for_storage(envelope: PlannerPlanEnvelope) -> dict[str, object]:
    """Serialize envelope for `builder_plans.envelope_json`.

    The spec duplicate is stripped so `spec_json` stays the single source of
    truth. `_plan_from_row` re-hydrates the spec on read.
    """
    return envelope.model_dump(mode="json", exclude={"spec"})


def _resource_bindings_json_for_storage(
    bindings: tuple[LocalResourceBinding, ...],
) -> list[dict[str, object]]:
    return [binding.model_dump(mode="json", round_trip=True) for binding in bindings]


def _resource_bindings_from_json(
    resource_bindings_json: list[dict[str, object]],
) -> tuple[LocalResourceBinding, ...]:
    return tuple(
        # JSONB rehydrates UUIDs/enums as JSON primitives; validation returns
        # the strict domain model before the value leaves the repository.
        _LOCAL_RESOURCE_BINDING_ADAPTER.validate_python(binding_json, strict=False)
        for binding_json in resource_bindings_json
    )


def _plan_from_row(row: Any) -> BuilderPlan:
    """Convert a DB row/mapping to a BuilderPlan domain model."""
    data = _plan_row_data(row)

    spec = FlowDraftSpecCore.model_validate(data["spec_json"])
    envelope_data = {k: v for k, v in data["envelope_json"].items() if k != "spec"}
    envelope_data["spec"] = data["spec_json"]
    envelope = PlannerPlanEnvelope.model_validate(envelope_data)
    edit_result = (
        BuilderPlanEditResult.model_validate(data["edit_result_json"])
        if data["edit_result_json"] is not None
        else None
    )

    return BuilderPlan(
        id=data["id"],
        session_id=data["session_id"],
        tenant_id=data["tenant_id"],
        status=PlanStatus(data["status"]),
        spec=spec,
        spec_hash=data["spec_hash"],
        envelope=envelope,
        resource_bindings=_resource_bindings_from_json(data["resource_bindings_json"]),
        edit_result=edit_result,
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


# jsonb-discipline: enforced (writes + reads)
#
# `planning_state_jsonb` is written and read exclusively through these
# two helpers plus their calling repo methods. Partial JSONB operators
# (`jsonb_set`, `||`, path updates) and raw JSONB reads from elsewhere
# in the codebase are forbidden so the column never drifts out of
# Pydantic's typed world.


def _planning_state_for_storage(state: PlanningState) -> dict[str, object]:
    """Return the full column-values map for persisting `state`.

    `validated_snapshot()` re-runs Pydantic's validators so container
    mutations that bypassed the field validator (list appends, dict
    inserts) raise here rather than silently landing in JSONB.
    """
    snapshot = state.validated_snapshot()
    architecture_hash = (
        snapshot.architecture_commit.architecture_hash
        if snapshot.architecture_commit is not None
        else None
    )
    return {
        "planning_state_jsonb": snapshot.model_dump(mode="json"),
        "planning_phase": snapshot.phase,
        "architecture_hash": architecture_hash,
        "planning_state_updated_at": datetime.now(timezone.utc),
    }
