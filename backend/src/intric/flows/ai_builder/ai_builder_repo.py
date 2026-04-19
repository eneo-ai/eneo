"""Repository for AI Builder sessions and plans."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, TypedDict, cast
from uuid import UUID

import sqlalchemy as sa
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
from intric.flows.ai_builder.ai_builder_session_transitions import (
    ensure_valid_session_status_transition,
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
            compacted = compact_ai_builder_conversation(conversation)
            serialized = [msg.model_dump(mode="json") for msg in compacted]
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
            )
            row = (await self.session.execute(stmt)).scalar_one_or_none()
            if row is None:
                raise NotFoundException("Builder session not found.")

            existing = _session_from_row(row).conversation
            compacted = compact_ai_builder_conversation([*existing, *conversation])
            serialized = [msg.model_dump(mode="json") for msg in compacted]
            update_stmt = (
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
            await self.session.execute(update_stmt)
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

    async def update_session_latest_plan(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        plan_id: UUID,
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
                next_status=SessionStatus.AWAITING_APPROVAL,
            )
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

    async def claim_session_send(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        request_id: UUID,
        lock_token: UUID,
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
                    active_request_id=request_id,
                    lock_token=lock_token,
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
        request_id: UUID,
        lock_token: UUID,
        lock_expires_at: datetime,
    ) -> bool:
        async with self._transaction():
            now = datetime.now(timezone.utc)
            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                    BuilderSessions.active_request_id == request_id,
                    BuilderSessions.lock_token == lock_token,
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
        request_id: UUID,
        lock_token: UUID,
    ) -> None:
        async with self._transaction():
            stmt = (
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                    BuilderSessions.active_request_id == request_id,
                    BuilderSessions.lock_token == lock_token,
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
        edit_result_json: dict[str, object] | None = None,
    ) -> BuilderPlan:
        async with self._transaction():
            spec_hash = spec.spec_hash()
            values: dict[str, object] = {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "status": PlanStatus.PROPOSED.value,
                "spec_json": spec.model_dump(mode="json"),
                "spec_hash": spec_hash,
                "envelope_json": envelope.model_dump(mode="json"),
            }
            if edit_result_json is not None:
                values["edit_result_json"] = edit_result_json
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
# Row → domain model converters
# ---------------------------------------------------------------------------


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
    edit_result_json: dict[str, object] | None
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
            "edit_result_json": cast(
                dict[str, object] | None, mapping.get("edit_result_json")
            ),
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
        "edit_result_json": cast(
            dict[str, object] | None, getattr(row, "edit_result_json", None)
        ),
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
                ConversationMessage.model_validate(cast(dict[str, object], msg))
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
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


def _plan_from_row(row: Any) -> BuilderPlan:
    """Convert a DB row/mapping to a BuilderPlan domain model."""
    data = _plan_row_data(row)

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
        edit_result_json=data["edit_result_json"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )
