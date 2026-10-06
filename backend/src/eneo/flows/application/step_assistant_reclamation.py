"""Flow-managed assistant reclamation, as a thin retention task adopter.

The shared engine owns discovery collection, cursors, budgets and audit.
Each unit locks its flow and assistant before fresh ownership/reference checks.
Configuration and scoped keys are bounded before any history is detached;
assistants whose atomic cost exceeds the operator cap remain untouched.
History detachment commits in bounded units. Final deletion prepares afresh
and uses the assistants' canonical deletion owner in one savepoint.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.assistants.assistant_repo import delete_removable_flow_managed_assistants
from eneo.assistants.assistant_service import remove_flow_managed_assistants
from eneo.audit.application.audit_service import AuditService
from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.authentication.api_key_scope_revoker import ApiKeyScopeRevoker
from eneo.authentication.api_key_v2_repo import ApiKeysV2Repository
from eneo.authentication.auth_models import (
    ApiKeyScopeType,
    ApiKeyStateReasonCode,
    ApiKeyV2InDB,
)
from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionStepResult,
    is_retention_timeout,
)
from eneo.data_retention.application.retention_units import (
    RetentionEffects,
    RetentionUnitCandidate,
    RetentionUnitDisposition,
    RetentionUnitUsage,
    gather_retention_units,
)
from eneo.data_retention.domain.retention import RetentionKeyset
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_retention_hold_repo import flow_has_active_hold
from eneo.flows.infrastructure.step_assistant_reclamation_repo import (
    CandidateAssistant,
    StepAssistantReclamationRepository,
)
from eneo.icons.icon_repo import IconRepository
from eneo.main.config import Settings
from eneo.main.exceptions import BadRequestException
from eneo.main.logging import get_logger

logger = get_logger(__name__)
STEP_ASSISTANTS_STEP = "step_assistants"


class ReclaimReason(StrEnum):
    REMOVED_STEP = "removed_step"
    RETIRED_FLOW = "retired_flow"


class KeepReason(StrEnum):
    EXECUTABLE_VERSION = "executable_version"
    RECENTLY_CREATED = "recently_created"
    EXTERNAL_REFERENCE = "external_reference"
    HELD = "held"
    UNKNOWN_REFERENCE = "unknown_reference"
    EXCEEDS_BUDGET = "assistant_exceeds_budget"


_RECLAIMED_KEY = {
    ReclaimReason.REMOVED_STEP: "removed_step_assistants",
    ReclaimReason.RETIRED_FLOW: "retired_flow_assistants",
}
STEP_ASSISTANT_COUNT_KEYS = frozenset(
    {*_RECLAIMED_KEY.values(), "step_results_detached", "draft_steps_deleted"}
)
STEP_ASSISTANT_BLOCKED_KEYS = frozenset(
    {
        *(reason.value for reason in KeepReason),
        "lock_deferred",
        "flow_failed",
        "nothing_left",
    }
)


async def flow_history_held(session: AsyncSession, *, flow_id: UUID) -> bool:
    """The task holds the shared retention lock before this fresh hold check."""
    return bool(await session.scalar(sa.select(flow_has_active_hold(flow_id))))


@dataclass(frozen=True)
class _Decision:
    reason: ReclaimReason | KeepReason
    retired: bool
    icon_id: UUID | None


@dataclass
class _Charge:
    # Admission is charged even when the unit's savepoint later rolls back.
    rows: int = 1


class StepAssistantReclamation:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        family_rows: int | None = None,
        chunk_rows: int | None = None,
    ) -> None:
        self._unattached_grace = timedelta(
            hours=settings.flow_step_assistant_unattached_grace_hours
        )
        self._cap = (
            family_rows
            if family_rows is not None
            else settings.retention_max_family_rows
        )
        self._chunk_rows = (
            chunk_rows if chunk_rows is not None else settings.retention_chunk_rows
        )
        self._gather_seconds = settings.retention_family_gather_seconds
        self.session = session
        self.flow_repo = FlowRepository(session=session)
        self.repo = StepAssistantReclamationRepository(session)
        self.icon_repo = IconRepository(session)
        self.api_key_repo = ApiKeysV2Repository(session)
        self.revoker = ApiKeyScopeRevoker(
            api_key_repo=self.api_key_repo,
            audit_service=AuditService(repository=AuditLogRepositoryImpl(session)),
            user=None,
        )

    async def step(self, batch: RetentionBatch) -> RetentionStepResult:
        out = RetentionEffects()
        unknown = bool(await self.repo.unknown_assistant_foreign_keys())

        async def next_candidate(
            after: RetentionKeyset | None,
        ) -> RetentionUnitCandidate | None:
            candidate = await self.repo.next_assistant(
                after=(after.at, after.id) if after is not None else None
            )
            if candidate is None:
                return None

            async def handle(rows: int, files: int) -> RetentionUnitUsage:
                return await self._unit(candidate, rows=rows, unknown=unknown, out=out)

            return RetentionKeyset(at=candidate.created_at, id=candidate.id), handle

        return await gather_retention_units(
            next_candidate,
            out,
            max_rows=batch.rows,
            max_files=batch.files,
            cursor=batch.cursor,
            chunk_rows=self._chunk_rows,
            gather_seconds=self._gather_seconds,
        )

    async def _unit(
        self,
        candidate: CandidateAssistant,
        *,
        rows: int,
        unknown: bool,
        out: RetentionEffects,
    ) -> RetentionUnitUsage:
        charge = _Charge()
        committed = RetentionEffects()
        try:
            async with self.session.begin_nested():
                usage = await self._reclaim(
                    candidate,
                    rows=rows,
                    unknown=unknown,
                    out=committed,
                    charge=charge,
                )
        except (SQLAlchemyError, BadRequestException) as exc:
            if is_retention_timeout(exc):
                raise
            logger.exception(
                "Step assistant reclamation failed",
                extra={"assistant_id": str(candidate.id)},
            )
            out.blocked["flow_failed"] += 1
            return RetentionUnitUsage(rows=charge.rows, files=0)
        out.merge(committed)
        return usage

    async def _decide(
        self,
        candidate: CandidateAssistant,
        *,
        unknown: bool,
        charge: _Charge,
    ) -> _Decision | None:
        flow = await self.flow_repo.flow_row_for_step_assistant_reclamation(
            flow_id=candidate.flow_id,
            tenant_id=candidate.tenant_id,
        )
        charge.rows += 1
        if flow is None:
            return None
        assistant = await self.repo.assistant_row(
            candidate, created_within=self._unattached_grace
        )
        charge.rows += 1
        if assistant is None:
            return None
        retired = flow.deleted_at is not None
        _, icon_id, recent = assistant
        if unknown:
            return _Decision(KeepReason.UNKNOWN_REFERENCE, retired, icon_id)
        if await flow_history_held(self.session, flow_id=candidate.flow_id):
            return _Decision(KeepReason.HELD, retired, icon_id)
        free = await self.flow_repo.orphaned_flow_managed_assistant_ids(
            flow_id=candidate.flow_id,
            tenant_id=candidate.tenant_id,
            assistant_ids=(candidate.id,),
        )
        charge.rows += len(free)
        if not free:
            return _Decision(KeepReason.EXECUTABLE_VERSION, retired, icon_id)
        if not retired and recent:
            return _Decision(KeepReason.RECENTLY_CREATED, retired, icon_id)
        external = await self.repo.externally_referenced((candidate.id,))
        charge.rows += len(external)
        if external:
            return _Decision(KeepReason.EXTERNAL_REFERENCE, retired, icon_id)
        return _Decision(
            ReclaimReason.RETIRED_FLOW if retired else ReclaimReason.REMOVED_STEP,
            retired,
            icon_id,
        )

    async def _reclaim(
        self,
        candidate: CandidateAssistant,
        *,
        rows: int,
        unknown: bool,
        out: RetentionEffects,
        charge: _Charge,
    ) -> RetentionUnitUsage:
        def done(reason: KeepReason | str | None = None) -> RetentionUnitUsage:
            if reason is not None:
                out.blocked[reason] += 1
            return RetentionUnitUsage(rows=charge.rows, files=0)

        def not_now() -> RetentionUnitUsage:
            return RetentionUnitUsage(
                rows=charge.rows,
                files=0,
                disposition=RetentionUnitDisposition.DOES_NOT_FIT,
            )

        # Candidate + flow + assistant + canonical orphan read + root deletion.
        if self._cap < 5:
            return done(KeepReason.EXCEEDS_BUDGET)
        if rows < 5:
            return not_now()
        decision = await self._decide(candidate, unknown=unknown, charge=charge)
        if decision is None:
            return done("lock_deferred")
        if isinstance(decision.reason, KeepReason):
            return done(decision.reason)
        icon = int(decision.icon_id is not None)
        # C includes owned configuration and a retired flow's draft steps;
        # K is the unrevoked scoped keys. Final cost is 5+2*C+3*K+icon:
        # four preparation rows, C+K measured rows, root/C writes, and each
        # key's UPDATE plus mandatory audit. Detach costs 4+C+K+2*N.
        max_configuration = max(0, (self._cap - 5 - icon) // 2)
        admitted_configuration = min(max_configuration, rows - charge.rows - 1)
        configuration = await self.repo.configuration_rows(
            candidate,
            retired=decision.retired,
            limit=admitted_configuration + 1,
        )
        charge.rows += configuration
        if configuration > max_configuration:
            return done(KeepReason.EXCEEDS_BUDGET)
        if configuration > admitted_configuration:
            return not_now()
        max_keys = max(0, (self._cap - 5 - 2 * configuration - icon) // 3)
        admitted_keys = min(max_keys, rows - charge.rows - 1)
        if admitted_keys < 0:
            return not_now()
        keys = await self.api_key_repo.list_by_scope(
            tenant_id=candidate.tenant_id,
            scope_type=ApiKeyScopeType.ASSISTANT,
            scope_id=candidate.id,
            unrevoked_only=True,
            limit=admitted_keys + 1,
        )
        charge.rows += len(keys)
        if len(keys) > max_keys:
            return done(KeepReason.EXCEEDS_BUDGET)
        if len(keys) > admitted_keys:
            return not_now()
        final_writes = 1 + configuration + 2 * len(keys) + icon
        history = await self.repo.has_run_history(candidate.id)
        if charge.rows + final_writes > self._cap or (
            history and charge.rows + 2 > self._cap
        ):
            return done(KeepReason.EXCEEDS_BUDGET)
        if history:
            count = min((rows - charge.rows) // 2, max(1, self._chunk_rows // 2))
            if count < 1:
                return not_now()
            charge.rows += 2 * count
            detached, _ = await self.repo.detach_run_history(
                (candidate.id,), limit=count
            )
            charge.rows -= 2 * (count - detached)
            if not detached:
                return done("lock_deferred")
            out.add(candidate.tenant_id, "step_results_detached", detached)
            return RetentionUnitUsage(
                rows=charge.rows,
                files=0,
                disposition=RetentionUnitDisposition.CONTINUE,
            )
        if charge.rows + final_writes > rows:
            return not_now()
        charge.rows += final_writes
        steps = await self._delete(candidate, retired=decision.retired, keys=keys)
        out.add(candidate.tenant_id, _RECLAIMED_KEY[decision.reason])
        out.add(candidate.tenant_id, "draft_steps_deleted", steps)
        return done()

    async def _delete(
        self,
        candidate: CandidateAssistant,
        *,
        retired: bool,
        keys: list[ApiKeyV2InDB],
    ) -> int:
        steps = (
            await self.repo.delete_retired_flow_steps(
                flow_id=candidate.flow_id,
                tenant_id=candidate.tenant_id,
                assistant_ids=(candidate.id,),
            )
            if retired
            else 0
        )

        async def revoke(assistant_id: UUID) -> None:
            await self.revoker.revoke_as_system(
                keys,
                reason_code=ApiKeyStateReasonCode.SCOPE_REMOVED,
                reason_text="Assistant deleted",
            )

        await remove_flow_managed_assistants(
            session=self.session,
            delete_removable=functools.partial(
                delete_removable_flow_managed_assistants, self.session
            ),
            icon_repo=self.icon_repo,
            flow_id=candidate.flow_id,
            tenant_id=candidate.tenant_id,
            assistant_ids=frozenset({candidate.id}),
            revoke_api_keys=revoke,
        )
        return steps
