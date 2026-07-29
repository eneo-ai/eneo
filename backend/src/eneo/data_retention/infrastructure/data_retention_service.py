import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, TypeAlias, TypedDict, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.constants import (
    MIN_RETENTION_DAYS,
    ORPHANED_SESSION_CLEANUP_DAYS,
)
from eneo.database.affected_rows import affected_row_count
from eneo.database.tables.app_table import AppRuns, Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_classification_retention_policy_table import (
    FlowClassificationRetentionPolicies,
)
from eneo.database.tables.flow_tables import (
    BuilderSessions,
    FlowOutboxDeliveryStatus,
    FlowProviderCalls,
    FlowRunAuditOutbox,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowRuntimeUploadedFiles,
    Flows,
    FlowStepAttemptResolvedInputs,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.ai_builder.ai_builder_domain_models import SessionStatus
from eneo.flows.domain.flow import FlowProviderCallTokenUsage, FlowRunTokenUsage
from eneo.flows.enums import TERMINAL_FLOW_RUN_STATUS_VALUES
from eneo.flows.flow_retention_policy import resolve_flow_retention_policy
from eneo.flows.flow_retention_tombstone import (
    FLOW_RETENTION_ACTOR_SOURCE,
    FlowAttemptRetentionMarker,
    FlowRetentionDataClass,
    FlowRetentionObjectType,
    FlowRetentionState,
    FlowRetentionTombstone,
    FlowRetentionTombstoneCounts,
    RunDebugAttemptRetentionCounts,
    RunDebugStepResultRetentionCounts,
    append_retention_tombstone,
    has_retention_tombstone,
    parse_attempt_retention_counts,
)
from eneo.flows.infrastructure.flow_run_history_purge_repo import (
    FlowRunHistoryPurgeRepository,
    FlowRunHistoryPurgeResult,
    FlowTemplateAssetPurgeCounts,
    flow_run_active_rerun_exists,
    flow_run_undelivered_audit_exists,
    flow_run_unresolved_webhook_exists,
)
from eneo.main.exceptions import ConflictException, NotFoundException

logger = logging.getLogger(__name__)

# Statement batch size for retention deletes; worker transaction loops decide commit scope.
RETENTION_BATCH_SIZE = 5000
ACTIVE_BUILDER_SESSION_STATUS_VALUES = (
    SessionStatus.CHATTING.value,
    SessionStatus.AWAITING_APPROVAL.value,
)
RETENTION_ELIGIBLE_BUILDER_SESSION_STATUS_VALUES = (
    SessionStatus.APPLIED.value,
    SessionStatus.CANCELLED.value,
    *ACTIVE_BUILDER_SESSION_STATUS_VALUES,
)


def _builder_session_has_no_fresh_send_lock(now: datetime) -> sa.ColumnElement[bool]:
    return sa.or_(
        sa.not_(BuilderSessions.status.in_(ACTIVE_BUILDER_SESSION_STATUS_VALUES)),
        sa.and_(
            BuilderSessions.active_request_id.is_(None),
            BuilderSessions.lock_token.is_(None),
        ),
        sa.and_(
            BuilderSessions.lock_expires_at.is_not(None),
            BuilderSessions.lock_expires_at <= sa.literal(now),
        ),
    )


class FlowRuntimeCleanupCounts(TypedDict):
    debug_step_results: int
    debug_step_attempts: int
    debug_provider_calls: int
    debug_resolved_input_aggregates: int
    debug_resolved_input_edges: int
    flow_runs_considered: int
    flow_runs_lock_deferred: int
    flow_runs_purged: int
    flow_generated_files_deleted: int
    flow_runtime_source_candidates: int
    flow_runtime_source_candidate_bytes: int
    flow_runtime_source_bindings_deleted: int
    flow_runtime_source_files_deleted: int
    flow_runtime_source_bytes_deleted: int
    flow_webhook_deliveries_deleted: int
    flow_audit_outbox_rows_deleted: int
    flow_review_checkpoints_deleted: int
    flow_template_assets_purged: int
    flow_template_asset_files_deleted: int
    flow_template_assets_skipped_published_reference: int
    flow_template_assets_skipped_undetermined_reference: int
    flow_runs_skipped_undelivered_audit: int
    flow_runs_skipped_unresolved_webhook: int
    flow_runs_skipped_active_rerun: int


def _empty_flow_runtime_cleanup_counts() -> FlowRuntimeCleanupCounts:
    return {
        "debug_step_results": 0,
        "debug_step_attempts": 0,
        "debug_provider_calls": 0,
        "debug_resolved_input_aggregates": 0,
        "debug_resolved_input_edges": 0,
        "flow_runs_considered": 0,
        "flow_runs_lock_deferred": 0,
        "flow_runs_purged": 0,
        "flow_generated_files_deleted": 0,
        "flow_runtime_source_candidates": 0,
        "flow_runtime_source_candidate_bytes": 0,
        "flow_runtime_source_bindings_deleted": 0,
        "flow_runtime_source_files_deleted": 0,
        "flow_runtime_source_bytes_deleted": 0,
        "flow_webhook_deliveries_deleted": 0,
        "flow_audit_outbox_rows_deleted": 0,
        "flow_review_checkpoints_deleted": 0,
        "flow_template_assets_purged": 0,
        "flow_template_asset_files_deleted": 0,
        "flow_template_assets_skipped_published_reference": 0,
        "flow_template_assets_skipped_undetermined_reference": 0,
        "flow_runs_skipped_undelivered_audit": 0,
        "flow_runs_skipped_unresolved_webhook": 0,
        "flow_runs_skipped_active_rerun": 0,
    }


@dataclass(frozen=True)
class _FlowRuntimeRetentionAction:
    run_id: UUID
    tenant_id: UUID
    trace_id: UUID
    cutoff: datetime
    policy_source: str
    cleanup_timestamp: datetime


@dataclass(frozen=True, slots=True)
class FlowRunHistoryPurgeBlockedCounts:
    skipped_undelivered_audit: int = 0
    skipped_unresolved_webhook: int = 0
    skipped_active_rerun: int = 0


@dataclass(frozen=True, slots=True)
class FlowDebugRedactionCounts:
    debug_step_results: int = 0
    debug_step_attempts: int = 0
    debug_provider_calls: int = 0
    debug_resolved_input_aggregates: int = 0
    debug_resolved_input_edges: int = 0


FLOW_RETENTION_PREVIEW_MAX_AGE = timedelta(minutes=15)
FLOW_RETENTION_PREVIEW_FUTURE_TOLERANCE = timedelta(seconds=30)
FLOW_RETENTION_CONFIRMATION_REQUIRED_CODE = "flow_retention_confirmation_required"
FLOW_RETENTION_PREVIEW_STALE_CODE = "flow_retention_preview_stale"


@dataclass(frozen=True, slots=True)
class FlowRetentionClassificationPolicyState:
    security_classification_id: UUID
    data_retention_days: int | None
    minimum_retention_days: int | None = None
    no_purge: bool = False


@dataclass(frozen=True, slots=True)
class FlowRetentionControlPlaneState:
    organization_run_history_days: int | None
    runtime_upload_abandonment_days: int | None
    classification_policies: tuple[FlowRetentionClassificationPolicyState, ...]
    latent_space_retention_days: tuple[int, ...]
    latent_flow_retention_days: tuple[int, ...]
    organization_minimum_retention_days: int | None = None
    organization_no_purge: bool = False

    @property
    def version(self) -> str:
        payload = {
            "organization_run_history_days": self.organization_run_history_days,
            "organization_minimum_retention_days": (
                self.organization_minimum_retention_days
            ),
            "organization_no_purge": self.organization_no_purge,
            "runtime_upload_abandonment_days": (self.runtime_upload_abandonment_days),
            "classification_policies": [
                [
                    str(policy.security_classification_id),
                    policy.data_retention_days,
                    policy.minimum_retention_days,
                    policy.no_purge,
                ]
                for policy in self.classification_policies
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class FlowRetentionOrganizationProposal:
    flow_run_history_retention_days: int | None
    flow_runtime_upload_abandonment_days: int | None
    flow_run_history_minimum_retention_days: int | None = None
    flow_run_history_no_purge: bool = False


@dataclass(frozen=True, slots=True)
class FlowRetentionClassificationProposal:
    security_classification_id: UUID
    data_retention_days: int | None
    minimum_retention_days: int | None = None
    no_purge: bool = False


@dataclass(frozen=True, slots=True)
class FlowRetentionValuePatch:
    is_set: bool
    value: int | None


@dataclass(frozen=True, slots=True)
class FlowRetentionBoolPatch:
    is_set: bool
    value: bool


@dataclass(frozen=True, slots=True)
class FlowRetentionChangeConfirmation:
    expected_control_plane_version: str
    expected_preview_hash: str
    previewed_at: datetime


@dataclass(frozen=True, slots=True)
class FlowRetentionDataImpact:
    current_eligible_count: int
    proposed_eligible_count: int
    newly_eligible_count: int
    no_longer_eligible_count: int
    proposed_eligible_bytes: int
    newly_eligible_bytes: int
    earliest_proposed_anchor: datetime | None
    latest_proposed_anchor: datetime | None
    earliest_proposed_delete_after_at: datetime | None
    latest_proposed_delete_after_at: datetime | None
    earliest_proposed_minimum_not_before_at: datetime | None
    latest_proposed_minimum_not_before_at: datetime | None

    def hash_payload(self) -> dict[str, object]:
        return {
            "current_eligible_count": self.current_eligible_count,
            "proposed_eligible_count": self.proposed_eligible_count,
            "newly_eligible_count": self.newly_eligible_count,
            "no_longer_eligible_count": self.no_longer_eligible_count,
            "proposed_eligible_bytes": self.proposed_eligible_bytes,
            "newly_eligible_bytes": self.newly_eligible_bytes,
            "earliest_proposed_anchor": _datetime_hash_value(
                self.earliest_proposed_anchor
            ),
            "latest_proposed_anchor": _datetime_hash_value(self.latest_proposed_anchor),
            "earliest_proposed_delete_after_at": _datetime_hash_value(
                self.earliest_proposed_delete_after_at
            ),
            "latest_proposed_delete_after_at": _datetime_hash_value(
                self.latest_proposed_delete_after_at
            ),
            "earliest_proposed_minimum_not_before_at": _datetime_hash_value(
                self.earliest_proposed_minimum_not_before_at
            ),
            "latest_proposed_minimum_not_before_at": _datetime_hash_value(
                self.latest_proposed_minimum_not_before_at
            ),
        }


@dataclass(frozen=True, slots=True)
class FlowRetentionLifecycleBlockers:
    undelivered_audit_count: int
    unresolved_webhook_count: int
    active_rerun_count: int

    def hash_payload(self) -> dict[str, int]:
        return {
            "undelivered_audit_count": self.undelivered_audit_count,
            "unresolved_webhook_count": self.unresolved_webhook_count,
            "active_rerun_count": self.active_rerun_count,
        }


@dataclass(frozen=True, slots=True)
class FlowRetentionPolicyBlockers:
    run_history_minimum_not_satisfied_count: int
    run_history_no_purge_count: int
    run_history_policy_conflict_count: int
    runtime_upload_minimum_not_satisfied_count: int
    runtime_upload_no_purge_count: int
    runtime_upload_policy_conflict_count: int

    def hash_payload(self) -> dict[str, int]:
        return {
            "run_history_minimum_not_satisfied_count": (
                self.run_history_minimum_not_satisfied_count
            ),
            "run_history_no_purge_count": self.run_history_no_purge_count,
            "run_history_policy_conflict_count": (
                self.run_history_policy_conflict_count
            ),
            "runtime_upload_minimum_not_satisfied_count": (
                self.runtime_upload_minimum_not_satisfied_count
            ),
            "runtime_upload_no_purge_count": self.runtime_upload_no_purge_count,
            "runtime_upload_policy_conflict_count": (
                self.runtime_upload_policy_conflict_count
            ),
        }


@dataclass(frozen=True, slots=True)
class FlowRetentionImpactPreview:
    destructive_change: bool
    control_plane_version: str
    preview_hash: str
    previewed_at: datetime
    run_history: FlowRetentionDataImpact
    runtime_uploads: FlowRetentionDataImpact
    lifecycle_blockers: FlowRetentionLifecycleBlockers
    policy_blockers: FlowRetentionPolicyBlockers
    latent_space_retention_days: tuple[int, ...]
    latent_flow_retention_days: tuple[int, ...]

    def audit_summary(self) -> dict[str, object]:
        return {
            "run_history": self.run_history.hash_payload(),
            "runtime_uploads": self.runtime_uploads.hash_payload(),
            "lifecycle_blockers": self.lifecycle_blockers.hash_payload(),
            "policy_blockers": self.policy_blockers.hash_payload(),
        }


@dataclass(frozen=True, slots=True)
class FlowRetentionOrganizationChangeDecision:
    old_policy: FlowRetentionOrganizationProposal
    new_policy: FlowRetentionOrganizationProposal
    destructive_change: bool
    preview: FlowRetentionImpactPreview | None


@dataclass(frozen=True, slots=True)
class FlowRetentionClassificationChangeDecision:
    old_policy: FlowRetentionClassificationProposal | None
    new_policy: FlowRetentionClassificationProposal
    destructive_change: bool
    preview: FlowRetentionImpactPreview | None


@dataclass(frozen=True, slots=True)
class _FlowRetentionSqlProposal:
    organization_run_history_days: int | None
    runtime_upload_abandonment_days: int | None
    organization_minimum_retention_days: int | None = None
    organization_no_purge: bool = False
    classification_id: UUID | None = None
    classification_days: int | None = None
    classification_minimum_retention_days: int | None = None
    classification_no_purge: bool = False


FlowRetentionSqlDays: TypeAlias = sa.ColumnElement[int] | sa.ColumnElement[int | None]
FlowRetentionSqlBool: TypeAlias = sa.ColumnElement[bool] | sa.ColumnElement[bool | None]


@dataclass(frozen=True, slots=True)
class FlowRunHistoryRetentionEligibilitySql:
    """Predicates derived from one run-history policy envelope."""

    delete_after_due: sa.ColumnElement[bool]
    minimum_satisfied: sa.ColumnElement[bool]
    eligible: sa.ColumnElement[bool]


@dataclass(frozen=True, slots=True)
class FlowRunHistoryRetentionSqlEnvelope:
    """SQL expressions for the complete Flow run-history retention envelope."""

    organization_days: FlowRetentionSqlDays
    classification_days: FlowRetentionSqlDays
    space_days: FlowRetentionSqlDays
    flow_days: FlowRetentionSqlDays
    organization_minimum_days: FlowRetentionSqlDays
    classification_minimum_days: FlowRetentionSqlDays
    organization_no_purge: FlowRetentionSqlBool
    classification_no_purge: FlowRetentionSqlBool
    activation_days: sa.ColumnElement[int | None]
    effective_days: sa.ColumnElement[int | None]
    effective_minimum_days: sa.ColumnElement[int | None]
    no_purge: sa.ColumnElement[bool]
    policy_conflict: sa.ColumnElement[bool]

    def eligibility(
        self,
        *,
        anchor: sa.ColumnElement[datetime],
        at: datetime,
    ) -> FlowRunHistoryRetentionEligibilitySql:
        """Apply activation, delete-after, and barrier predicates together."""
        delete_after_due = sa.and_(
            self.activation_days.is_not(None),
            anchor
            <= sa.literal(at) - sa.func.make_interval(0, 0, 0, self.effective_days),
        )
        minimum_satisfied = sa.or_(
            self.effective_minimum_days.is_(None),
            anchor
            <= sa.literal(at)
            - sa.func.make_interval(0, 0, 0, self.effective_minimum_days),
        )
        return FlowRunHistoryRetentionEligibilitySql(
            delete_after_due=delete_after_due,
            minimum_satisfied=minimum_satisfied,
            eligible=sa.and_(
                delete_after_due,
                minimum_satisfied,
                sa.not_(self.no_purge),
            ),
        )


def _datetime_hash_value(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _retention_change_is_destructive(
    *, old_days: int | None, new_days: int | None
) -> bool:
    return new_days is not None and (old_days is None or new_days < old_days)


def _retention_barrier_changed(
    *,
    old_minimum_days: int | None,
    new_minimum_days: int | None,
    old_no_purge: bool,
    new_no_purge: bool,
) -> bool:
    return old_minimum_days != new_minimum_days or old_no_purge is not new_no_purge


def _retention_days_literal(value: int | None) -> FlowRetentionSqlDays:
    if value is None:
        return cast(sa.ColumnElement[int | None], sa.null())
    return sa.literal(value, type_=sa.Integer())


class DataRetentionService:
    """Service for managing data retention and deletion based on hierarchical policies."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.session = session

    @staticmethod
    def flow_run_history_retention_sql_envelope(
        *,
        organization_days: FlowRetentionSqlDays,
        classification_days: FlowRetentionSqlDays,
        space_days: FlowRetentionSqlDays,
        flow_days: FlowRetentionSqlDays,
        organization_minimum_days: FlowRetentionSqlDays,
        classification_minimum_days: FlowRetentionSqlDays,
        organization_no_purge: FlowRetentionSqlBool,
        classification_no_purge: FlowRetentionSqlBool,
    ) -> FlowRunHistoryRetentionSqlEnvelope:
        """Build the sole SQL policy envelope used by reads and deletion paths."""
        activation_days = cast(
            sa.ColumnElement[int | None],
            sa.func.least(organization_days, classification_days),
        )
        effective_days = cast(
            sa.ColumnElement[int | None],
            sa.case(
                (
                    activation_days.is_not(None),
                    sa.func.least(activation_days, space_days, flow_days),
                ),
                else_=sa.null(),
            ),
        )
        effective_minimum_days = cast(
            sa.ColumnElement[int | None],
            sa.func.greatest(
                organization_minimum_days,
                classification_minimum_days,
            ),
        )
        no_purge = sa.or_(
            sa.func.coalesce(organization_no_purge, sa.false()),
            sa.func.coalesce(classification_no_purge, sa.false()),
        )
        policy_conflict = sa.and_(
            effective_days.is_not(None),
            effective_minimum_days.is_not(None),
            effective_days < effective_minimum_days,
        )
        return FlowRunHistoryRetentionSqlEnvelope(
            organization_days=organization_days,
            classification_days=classification_days,
            space_days=space_days,
            flow_days=flow_days,
            organization_minimum_days=organization_minimum_days,
            classification_minimum_days=classification_minimum_days,
            organization_no_purge=organization_no_purge,
            classification_no_purge=classification_no_purge,
            activation_days=activation_days,
            effective_days=effective_days,
            effective_minimum_days=effective_minimum_days,
            no_purge=no_purge,
            policy_conflict=policy_conflict,
        )

    async def get_flow_retention_control_plane_state(
        self,
        *,
        tenant_id: UUID,
        lock: bool = False,
    ) -> FlowRetentionControlPlaneState:
        tenant_stmt = sa.select(
            Tenants.flow_run_history_retention_days,
            Tenants.flow_runtime_upload_abandonment_days,
            Tenants.flow_run_history_minimum_retention_days,
            Tenants.flow_run_history_no_purge,
        ).where(Tenants.id == tenant_id)
        if lock:
            tenant_stmt = tenant_stmt.with_for_update(of=Tenants)
        tenant_row = (await self.session.execute(tenant_stmt)).one_or_none()
        if tenant_row is None:
            raise NotFoundException("Tenant not found.")

        policy_rows = (
            await self.session.execute(
                sa.select(
                    FlowClassificationRetentionPolicies.security_classification_id,
                    FlowClassificationRetentionPolicies.data_retention_days,
                    FlowClassificationRetentionPolicies.minimum_retention_days,
                    FlowClassificationRetentionPolicies.no_purge,
                )
                .where(FlowClassificationRetentionPolicies.tenant_id == tenant_id)
                .order_by(
                    FlowClassificationRetentionPolicies.security_classification_id
                )
            )
        ).all()
        space_days = tuple(
            day
            for day in (
                await self.session.scalars(
                    sa.select(Spaces.data_retention_days)
                    .where(
                        Spaces.tenant_id == tenant_id,
                        Spaces.data_retention_days.is_not(None),
                    )
                    .distinct()
                    .order_by(Spaces.data_retention_days)
                )
            ).all()
            if day is not None
        )
        flow_days = tuple(
            day
            for day in (
                await self.session.scalars(
                    sa.select(Flows.data_retention_days)
                    .where(
                        Flows.tenant_id == tenant_id,
                        Flows.data_retention_days.is_not(None),
                    )
                    .distinct()
                    .order_by(Flows.data_retention_days)
                )
            ).all()
            if day is not None
        )
        organization_days, upload_days, organization_minimum_days, no_purge = tenant_row
        return FlowRetentionControlPlaneState(
            organization_run_history_days=organization_days,
            runtime_upload_abandonment_days=upload_days,
            classification_policies=tuple(
                FlowRetentionClassificationPolicyState(
                    security_classification_id=classification_id,
                    data_retention_days=retention_days,
                    minimum_retention_days=minimum_retention_days,
                    no_purge=classification_no_purge,
                )
                for (
                    classification_id,
                    retention_days,
                    minimum_retention_days,
                    classification_no_purge,
                ) in policy_rows
            ),
            latent_space_retention_days=space_days,
            latent_flow_retention_days=flow_days,
            organization_minimum_retention_days=organization_minimum_days,
            organization_no_purge=no_purge,
        )

    async def preview_flow_retention_organization_change(
        self,
        *,
        tenant_id: UUID,
        proposal: FlowRetentionOrganizationProposal,
        previewed_at: datetime | None = None,
    ) -> FlowRetentionImpactPreview:
        state = await self.get_flow_retention_control_plane_state(tenant_id=tenant_id)
        sql_proposal = _FlowRetentionSqlProposal(
            organization_run_history_days=(proposal.flow_run_history_retention_days),
            runtime_upload_abandonment_days=(
                proposal.flow_runtime_upload_abandonment_days
            ),
            organization_minimum_retention_days=(
                proposal.flow_run_history_minimum_retention_days
            ),
            organization_no_purge=proposal.flow_run_history_no_purge,
        )
        destructive_change = (
            _retention_change_is_destructive(
                old_days=state.organization_run_history_days,
                new_days=proposal.flow_run_history_retention_days,
            )
            or _retention_change_is_destructive(
                old_days=state.runtime_upload_abandonment_days,
                new_days=proposal.flow_runtime_upload_abandonment_days,
            )
            or _retention_barrier_changed(
                old_minimum_days=state.organization_minimum_retention_days,
                new_minimum_days=proposal.flow_run_history_minimum_retention_days,
                old_no_purge=state.organization_no_purge,
                new_no_purge=proposal.flow_run_history_no_purge,
            )
        )
        return await self._preview_flow_retention_change(
            tenant_id=tenant_id,
            state=state,
            proposal=sql_proposal,
            destructive_change=destructive_change,
            previewed_at=previewed_at or datetime.now(timezone.utc),
        )

    async def preview_flow_retention_classification_change(
        self,
        *,
        tenant_id: UUID,
        proposal: FlowRetentionClassificationProposal,
        previewed_at: datetime | None = None,
    ) -> FlowRetentionImpactPreview:
        state = await self.get_flow_retention_control_plane_state(tenant_id=tenant_id)
        old_policy = next(
            (
                policy
                for policy in state.classification_policies
                if policy.security_classification_id
                == proposal.security_classification_id
            ),
            None,
        )
        return await self._preview_flow_retention_change(
            tenant_id=tenant_id,
            state=state,
            proposal=_FlowRetentionSqlProposal(
                organization_run_history_days=(state.organization_run_history_days),
                runtime_upload_abandonment_days=(state.runtime_upload_abandonment_days),
                organization_minimum_retention_days=(
                    state.organization_minimum_retention_days
                ),
                organization_no_purge=state.organization_no_purge,
                classification_id=proposal.security_classification_id,
                classification_days=proposal.data_retention_days,
                classification_minimum_retention_days=(proposal.minimum_retention_days),
                classification_no_purge=proposal.no_purge,
            ),
            destructive_change=_retention_change_is_destructive(
                old_days=(old_policy.data_retention_days if old_policy else None),
                new_days=proposal.data_retention_days,
            )
            or _retention_barrier_changed(
                old_minimum_days=(
                    old_policy.minimum_retention_days if old_policy else None
                ),
                new_minimum_days=proposal.minimum_retention_days,
                old_no_purge=old_policy.no_purge if old_policy else False,
                new_no_purge=proposal.no_purge,
            )
            or (
                old_policy is not None
                and proposal.data_retention_days is None
                and proposal.minimum_retention_days is None
                and not proposal.no_purge
            ),
            previewed_at=previewed_at or datetime.now(timezone.utc),
        )

    async def prepare_flow_retention_organization_change(
        self,
        *,
        tenant_id: UUID,
        run_history_patch: FlowRetentionValuePatch,
        upload_abandonment_patch: FlowRetentionValuePatch,
        minimum_retention_patch: FlowRetentionValuePatch,
        no_purge_patch: FlowRetentionBoolPatch,
        confirmation: FlowRetentionChangeConfirmation | None,
    ) -> FlowRetentionOrganizationChangeDecision:
        state = await self.get_flow_retention_control_plane_state(
            tenant_id=tenant_id,
            lock=True,
        )
        old_policy = FlowRetentionOrganizationProposal(
            flow_run_history_retention_days=(state.organization_run_history_days),
            flow_runtime_upload_abandonment_days=(
                state.runtime_upload_abandonment_days
            ),
            flow_run_history_minimum_retention_days=(
                state.organization_minimum_retention_days
            ),
            flow_run_history_no_purge=state.organization_no_purge,
        )
        new_policy = FlowRetentionOrganizationProposal(
            flow_run_history_retention_days=(
                run_history_patch.value
                if run_history_patch.is_set
                else state.organization_run_history_days
            ),
            flow_runtime_upload_abandonment_days=(
                upload_abandonment_patch.value
                if upload_abandonment_patch.is_set
                else state.runtime_upload_abandonment_days
            ),
            flow_run_history_minimum_retention_days=(
                minimum_retention_patch.value
                if minimum_retention_patch.is_set
                else state.organization_minimum_retention_days
            ),
            flow_run_history_no_purge=(
                no_purge_patch.value
                if no_purge_patch.is_set
                else state.organization_no_purge
            ),
        )
        destructive_change = (
            _retention_change_is_destructive(
                old_days=old_policy.flow_run_history_retention_days,
                new_days=new_policy.flow_run_history_retention_days,
            )
            or _retention_change_is_destructive(
                old_days=old_policy.flow_runtime_upload_abandonment_days,
                new_days=new_policy.flow_runtime_upload_abandonment_days,
            )
            or _retention_barrier_changed(
                old_minimum_days=(old_policy.flow_run_history_minimum_retention_days),
                new_minimum_days=(new_policy.flow_run_history_minimum_retention_days),
                old_no_purge=old_policy.flow_run_history_no_purge,
                new_no_purge=new_policy.flow_run_history_no_purge,
            )
        )
        preview = None
        if destructive_change or confirmation is not None:
            preview = await self._confirm_flow_retention_change(
                tenant_id=tenant_id,
                state=state,
                proposal=_FlowRetentionSqlProposal(
                    organization_run_history_days=(
                        new_policy.flow_run_history_retention_days
                    ),
                    runtime_upload_abandonment_days=(
                        new_policy.flow_runtime_upload_abandonment_days
                    ),
                    organization_minimum_retention_days=(
                        new_policy.flow_run_history_minimum_retention_days
                    ),
                    organization_no_purge=(new_policy.flow_run_history_no_purge),
                ),
                confirmation=confirmation,
            )
        return FlowRetentionOrganizationChangeDecision(
            old_policy=old_policy,
            new_policy=new_policy,
            destructive_change=destructive_change,
            preview=preview,
        )

    async def prepare_flow_retention_classification_change(
        self,
        *,
        tenant_id: UUID,
        proposal: FlowRetentionClassificationProposal,
        confirmation: FlowRetentionChangeConfirmation | None,
    ) -> FlowRetentionClassificationChangeDecision:
        state = await self.get_flow_retention_control_plane_state(
            tenant_id=tenant_id,
            lock=True,
        )
        old_state = next(
            (
                policy
                for policy in state.classification_policies
                if policy.security_classification_id
                == proposal.security_classification_id
            ),
            None,
        )
        old_policy = (
            FlowRetentionClassificationProposal(
                security_classification_id=proposal.security_classification_id,
                data_retention_days=old_state.data_retention_days,
                minimum_retention_days=old_state.minimum_retention_days,
                no_purge=old_state.no_purge,
            )
            if old_state is not None
            else None
        )
        destructive_change = _retention_change_is_destructive(
            old_days=(old_state.data_retention_days if old_state else None),
            new_days=proposal.data_retention_days,
        ) or _retention_barrier_changed(
            old_minimum_days=(old_state.minimum_retention_days if old_state else None),
            new_minimum_days=proposal.minimum_retention_days,
            old_no_purge=old_state.no_purge if old_state else False,
            new_no_purge=proposal.no_purge,
        )
        all_off_removes_policy = (
            old_state is not None
            and proposal.data_retention_days is None
            and proposal.minimum_retention_days is None
            and not proposal.no_purge
        )
        destructive_change = destructive_change or all_off_removes_policy
        preview = None
        if destructive_change or confirmation is not None:
            preview = await self._confirm_flow_retention_change(
                tenant_id=tenant_id,
                state=state,
                proposal=_FlowRetentionSqlProposal(
                    organization_run_history_days=(state.organization_run_history_days),
                    runtime_upload_abandonment_days=(
                        state.runtime_upload_abandonment_days
                    ),
                    organization_minimum_retention_days=(
                        state.organization_minimum_retention_days
                    ),
                    organization_no_purge=state.organization_no_purge,
                    classification_id=proposal.security_classification_id,
                    classification_days=proposal.data_retention_days,
                    classification_minimum_retention_days=(
                        proposal.minimum_retention_days
                    ),
                    classification_no_purge=proposal.no_purge,
                ),
                confirmation=confirmation,
            )
        return FlowRetentionClassificationChangeDecision(
            old_policy=old_policy,
            new_policy=proposal,
            destructive_change=destructive_change,
            preview=preview,
        )

    async def _confirm_flow_retention_change(
        self,
        *,
        tenant_id: UUID,
        state: FlowRetentionControlPlaneState,
        proposal: _FlowRetentionSqlProposal,
        confirmation: FlowRetentionChangeConfirmation | None,
    ) -> FlowRetentionImpactPreview:
        if confirmation is None:
            raise ConflictException(
                "Preview and confirm this destructive Flow retention change.",
                code=FLOW_RETENTION_CONFIRMATION_REQUIRED_CODE,
            )
        now = datetime.now(timezone.utc)
        previewed_at = confirmation.previewed_at
        if previewed_at.tzinfo is None:
            raise ConflictException(
                "Flow retention preview timestamp must include a timezone.",
                code=FLOW_RETENTION_PREVIEW_STALE_CODE,
            )
        previewed_at = previewed_at.astimezone(timezone.utc)
        if (
            previewed_at < now - FLOW_RETENTION_PREVIEW_MAX_AGE
            or previewed_at > now + FLOW_RETENTION_PREVIEW_FUTURE_TOLERANCE
        ):
            raise ConflictException(
                "Flow retention preview expired; request a new preview.",
                code=FLOW_RETENTION_PREVIEW_STALE_CODE,
            )
        if confirmation.expected_control_plane_version != state.version:
            raise ConflictException(
                "Flow retention policy changed; request a new preview.",
                code=FLOW_RETENTION_PREVIEW_STALE_CODE,
            )
        preview = await self._preview_flow_retention_change(
            tenant_id=tenant_id,
            state=state,
            proposal=proposal,
            destructive_change=True,
            previewed_at=previewed_at,
        )
        if confirmation.expected_preview_hash != preview.preview_hash:
            raise ConflictException(
                "Flow retention impact changed; request a new preview.",
                code=FLOW_RETENTION_PREVIEW_STALE_CODE,
            )
        return preview

    async def _preview_flow_retention_change(
        self,
        *,
        tenant_id: UUID,
        state: FlowRetentionControlPlaneState,
        proposal: _FlowRetentionSqlProposal,
        destructive_change: bool,
        previewed_at: datetime,
    ) -> FlowRetentionImpactPreview:
        normalized_previewed_at = previewed_at.astimezone(timezone.utc)
        run_row = (
            (
                await self.session.execute(
                    self._build_flow_retention_run_impact_query(
                        tenant_id=tenant_id,
                        state=state,
                        proposal=proposal,
                        previewed_at=normalized_previewed_at,
                    )
                )
            )
            .mappings()
            .one()
        )
        upload_row = (
            (
                await self.session.execute(
                    self._build_flow_retention_upload_impact_query(
                        tenant_id=tenant_id,
                        state=state,
                        proposal=proposal,
                        previewed_at=normalized_previewed_at,
                    )
                )
            )
            .mappings()
            .one()
        )
        run_history = _flow_retention_data_impact_from_row(run_row)
        runtime_uploads = _flow_retention_data_impact_from_row(upload_row)
        blockers = FlowRetentionLifecycleBlockers(
            undelivered_audit_count=_retention_row_int(
                run_row, "undelivered_audit_count"
            ),
            unresolved_webhook_count=_retention_row_int(
                run_row, "unresolved_webhook_count"
            ),
            active_rerun_count=_retention_row_int(run_row, "active_rerun_count"),
        )
        policy_blockers = FlowRetentionPolicyBlockers(
            run_history_minimum_not_satisfied_count=_retention_row_int(
                run_row, "minimum_not_satisfied_count"
            ),
            run_history_no_purge_count=_retention_row_int(run_row, "no_purge_count"),
            run_history_policy_conflict_count=_retention_row_int(
                run_row, "policy_conflict_count"
            ),
            runtime_upload_minimum_not_satisfied_count=_retention_row_int(
                upload_row, "minimum_not_satisfied_count"
            ),
            runtime_upload_no_purge_count=_retention_row_int(
                upload_row, "no_purge_count"
            ),
            runtime_upload_policy_conflict_count=_retention_row_int(
                upload_row, "policy_conflict_count"
            ),
        )
        hash_payload = {
            "control_plane_version": state.version,
            "previewed_at": normalized_previewed_at.isoformat(),
            "proposal": {
                "organization_run_history_days": (
                    proposal.organization_run_history_days
                ),
                "organization_minimum_retention_days": (
                    proposal.organization_minimum_retention_days
                ),
                "organization_no_purge": proposal.organization_no_purge,
                "runtime_upload_abandonment_days": (
                    proposal.runtime_upload_abandonment_days
                ),
                "classification_id": (
                    str(proposal.classification_id)
                    if proposal.classification_id is not None
                    else None
                ),
                "classification_days": proposal.classification_days,
                "classification_minimum_retention_days": (
                    proposal.classification_minimum_retention_days
                ),
                "classification_no_purge": proposal.classification_no_purge,
            },
            "run_history": run_history.hash_payload(),
            "runtime_uploads": runtime_uploads.hash_payload(),
            "lifecycle_blockers": blockers.hash_payload(),
            "policy_blockers": policy_blockers.hash_payload(),
            "latent_space_retention_days": state.latent_space_retention_days,
            "latent_flow_retention_days": state.latent_flow_retention_days,
        }
        preview_hash = hashlib.sha256(
            json.dumps(
                hash_payload,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return FlowRetentionImpactPreview(
            destructive_change=destructive_change,
            control_plane_version=state.version,
            preview_hash=preview_hash,
            previewed_at=normalized_previewed_at,
            run_history=run_history,
            runtime_uploads=runtime_uploads,
            lifecycle_blockers=blockers,
            policy_blockers=policy_blockers,
            latent_space_retention_days=state.latent_space_retention_days,
            latent_flow_retention_days=state.latent_flow_retention_days,
        )

    def _build_flow_retention_run_impact_query(
        self,
        *,
        tenant_id: UUID,
        state: FlowRetentionControlPlaneState,
        proposal: _FlowRetentionSqlProposal,
        previewed_at: datetime,
    ) -> sa.Select[
        tuple[int, int, int, int, int, int, datetime, datetime, int, int, int]
    ]:
        anchor = self._flow_run_history_retention_anchor()
        current_classification_days = (
            FlowClassificationRetentionPolicies.data_retention_days.__clause_element__()
        )
        current_classification_minimum_days = FlowClassificationRetentionPolicies.minimum_retention_days.__clause_element__()
        current_classification_no_purge = (
            FlowClassificationRetentionPolicies.no_purge.__clause_element__()
        )
        proposed_classification_days = current_classification_days
        proposed_classification_minimum_days = current_classification_minimum_days
        proposed_classification_no_purge = current_classification_no_purge
        if proposal.classification_id is not None:
            proposed_classification_days = sa.case(
                (
                    Spaces.security_classification_id == proposal.classification_id,
                    _retention_days_literal(proposal.classification_days),
                ),
                else_=current_classification_days,
            )
            proposed_classification_minimum_days = sa.case(
                (
                    Spaces.security_classification_id == proposal.classification_id,
                    _retention_days_literal(
                        proposal.classification_minimum_retention_days
                    ),
                ),
                else_=current_classification_minimum_days,
            )
            proposed_classification_no_purge = sa.case(
                (
                    Spaces.security_classification_id == proposal.classification_id,
                    sa.literal(proposal.classification_no_purge, type_=sa.Boolean()),
                ),
                else_=current_classification_no_purge,
            )

        current_envelope = self.flow_run_history_retention_sql_envelope(
            organization_days=_retention_days_literal(
                state.organization_run_history_days
            ),
            classification_days=current_classification_days,
            space_days=Spaces.data_retention_days.__clause_element__(),
            flow_days=Flows.data_retention_days.__clause_element__(),
            organization_minimum_days=_retention_days_literal(
                state.organization_minimum_retention_days
            ),
            classification_minimum_days=current_classification_minimum_days,
            organization_no_purge=sa.literal(
                state.organization_no_purge,
                type_=sa.Boolean(),
            ),
            classification_no_purge=current_classification_no_purge,
        )
        proposed_envelope = self.flow_run_history_retention_sql_envelope(
            organization_days=_retention_days_literal(
                proposal.organization_run_history_days
            ),
            classification_days=proposed_classification_days,
            space_days=Spaces.data_retention_days.__clause_element__(),
            flow_days=Flows.data_retention_days.__clause_element__(),
            organization_minimum_days=_retention_days_literal(
                proposal.organization_minimum_retention_days
            ),
            classification_minimum_days=proposed_classification_minimum_days,
            organization_no_purge=sa.literal(
                proposal.organization_no_purge,
                type_=sa.Boolean(),
            ),
            classification_no_purge=proposed_classification_no_purge,
        )
        current_eligibility = current_envelope.eligibility(
            anchor=anchor,
            at=previewed_at,
        )
        proposed_eligibility = proposed_envelope.eligibility(
            anchor=anchor,
            at=previewed_at,
        )
        current_due = current_eligibility.eligible
        proposed_due = proposed_eligibility.eligible
        proposed_delete_after_at = sa.case(
            (
                proposed_envelope.activation_days.is_not(None),
                anchor
                + sa.func.make_interval(
                    0,
                    0,
                    0,
                    proposed_envelope.effective_days,
                ),
            ),
            else_=sa.null(),
        )
        proposed_minimum_not_before_at = sa.case(
            (
                proposed_envelope.effective_minimum_days.is_not(None),
                anchor
                + sa.func.make_interval(
                    0,
                    0,
                    0,
                    proposed_envelope.effective_minimum_days,
                ),
            ),
            else_=sa.null(),
        )
        candidates = (
            sa.select(
                FlowRuns.id.label("run_id"),
                FlowRuns.tenant_id.label("tenant_id"),
                anchor.label("retention_anchor"),
                current_due.label("current_due"),
                proposed_due.label("proposed_due"),
                proposed_eligibility.delete_after_due.label(
                    "proposed_delete_after_due"
                ),
                proposed_eligibility.minimum_satisfied.label(
                    "proposed_minimum_satisfied"
                ),
                proposed_envelope.no_purge.label("proposed_no_purge"),
                proposed_envelope.policy_conflict.label("proposed_policy_conflict"),
                proposed_delete_after_at.label("proposed_delete_after_at"),
                proposed_minimum_not_before_at.label("proposed_minimum_not_before_at"),
            )
            .join(Flows, FlowRuns.flow_id == Flows.id)
            .join(Spaces, Flows.space_id == Spaces.id)
            .outerjoin(
                FlowClassificationRetentionPolicies,
                sa.and_(
                    FlowClassificationRetentionPolicies.security_classification_id
                    == Spaces.security_classification_id,
                    FlowClassificationRetentionPolicies.tenant_id == Spaces.tenant_id,
                ),
            )
            .where(
                FlowRuns.tenant_id == tenant_id,
                FlowRuns.status.in_(TERMINAL_FLOW_RUN_STATUS_VALUES),
                anchor
                <= sa.literal(previewed_at)
                - sa.func.make_interval(0, 0, 0, MIN_RETENTION_DAYS),
            )
            .cte("flow_retention_preview_candidates")
        )
        input_file_refs = sa.select(
            FlowRunStepInputFiles.flow_run_id.label("run_id"),
            FlowRunStepInputFiles.tenant_id.label("tenant_id"),
            FlowRunStepInputFiles.file_id.label("file_id"),
        ).join(
            candidates,
            FlowRunStepInputFiles.flow_run_id == candidates.c.run_id,
        )
        result_file_refs = sa.select(
            FlowRunStepResultFiles.flow_run_id.label("run_id"),
            FlowRunStepResultFiles.tenant_id.label("tenant_id"),
            FlowRunStepResultFiles.file_id.label("file_id"),
        ).join(
            candidates,
            FlowRunStepResultFiles.flow_run_id == candidates.c.run_id,
        )
        file_refs = input_file_refs.union(result_file_refs).cte(
            "flow_retention_preview_file_refs"
        )
        file_bytes = (
            sa.select(
                file_refs.c.run_id,
                sa.func.coalesce(sa.func.sum(Files.size), 0).label("file_bytes"),
            )
            .join(
                Files,
                sa.and_(
                    Files.id == file_refs.c.file_id,
                    Files.tenant_id == file_refs.c.tenant_id,
                ),
            )
            .group_by(file_refs.c.run_id)
            .cte("flow_retention_preview_file_bytes")
        )
        undelivered_audit = flow_run_undelivered_audit_exists(candidates.c.run_id)
        unresolved_webhook = flow_run_unresolved_webhook_exists(candidates.c.run_id)
        active_rerun = flow_run_active_rerun_exists(candidates.c.run_id)
        newly_due = sa.and_(
            candidates.c.proposed_due,
            sa.not_(candidates.c.current_due),
        )
        no_longer_due = sa.and_(
            candidates.c.current_due,
            sa.not_(candidates.c.proposed_due),
        )
        return (
            sa.select(
                sa.func.count()
                .filter(candidates.c.current_due)
                .label("current_eligible_count"),
                sa.func.count()
                .filter(candidates.c.proposed_due)
                .label("proposed_eligible_count"),
                sa.func.count().filter(newly_due).label("newly_eligible_count"),
                sa.func.count().filter(no_longer_due).label("no_longer_eligible_count"),
                sa.func.coalesce(
                    sa.func.sum(file_bytes.c.file_bytes).filter(
                        candidates.c.proposed_due
                    ),
                    0,
                ).label("proposed_eligible_bytes"),
                sa.func.coalesce(
                    sa.func.sum(file_bytes.c.file_bytes).filter(newly_due),
                    0,
                ).label("newly_eligible_bytes"),
                sa.func.min(candidates.c.retention_anchor)
                .filter(candidates.c.proposed_due)
                .label("earliest_proposed_anchor"),
                sa.func.max(candidates.c.retention_anchor)
                .filter(candidates.c.proposed_due)
                .label("latest_proposed_anchor"),
                sa.func.min(candidates.c.proposed_delete_after_at).label(
                    "earliest_proposed_delete_after_at"
                ),
                sa.func.max(candidates.c.proposed_delete_after_at).label(
                    "latest_proposed_delete_after_at"
                ),
                sa.func.min(candidates.c.proposed_minimum_not_before_at).label(
                    "earliest_proposed_minimum_not_before_at"
                ),
                sa.func.max(candidates.c.proposed_minimum_not_before_at).label(
                    "latest_proposed_minimum_not_before_at"
                ),
                sa.func.count()
                .filter(
                    candidates.c.proposed_delete_after_due,
                    sa.not_(candidates.c.proposed_minimum_satisfied),
                )
                .label("minimum_not_satisfied_count"),
                sa.func.count()
                .filter(
                    candidates.c.proposed_delete_after_due,
                    candidates.c.proposed_minimum_satisfied,
                    candidates.c.proposed_no_purge,
                )
                .label("no_purge_count"),
                sa.func.count()
                .filter(candidates.c.proposed_policy_conflict)
                .label("policy_conflict_count"),
                sa.func.count()
                .filter(candidates.c.proposed_due, undelivered_audit)
                .label("undelivered_audit_count"),
                sa.func.count()
                .filter(
                    candidates.c.proposed_due,
                    sa.not_(undelivered_audit),
                    unresolved_webhook,
                )
                .label("unresolved_webhook_count"),
                sa.func.count()
                .filter(
                    candidates.c.proposed_due,
                    sa.not_(undelivered_audit),
                    sa.not_(unresolved_webhook),
                    active_rerun,
                )
                .label("active_rerun_count"),
            )
            .select_from(candidates)
            .outerjoin(file_bytes, file_bytes.c.run_id == candidates.c.run_id)
        )

    def _build_flow_retention_upload_impact_query(
        self,
        *,
        tenant_id: UUID,
        state: FlowRetentionControlPlaneState,
        proposal: _FlowRetentionSqlProposal,
        previewed_at: datetime,
    ) -> sa.Select[tuple[int, int, int, int, int, int, datetime, datetime]]:
        current_delete_after_due = _retention_anchor_due(
            anchor=FlowRuntimeUploadedFiles.created_at,
            retention_days=state.runtime_upload_abandonment_days,
            previewed_at=previewed_at,
        )
        proposed_delete_after_due = _retention_anchor_due(
            anchor=FlowRuntimeUploadedFiles.created_at,
            retention_days=proposal.runtime_upload_abandonment_days,
            previewed_at=previewed_at,
        )
        current_minimum_satisfied = (
            sa.true()
            if state.organization_minimum_retention_days is None
            else _retention_anchor_due(
                anchor=FlowRuntimeUploadedFiles.created_at,
                retention_days=state.organization_minimum_retention_days,
                previewed_at=previewed_at,
            )
        )
        proposed_minimum_satisfied = (
            sa.true()
            if proposal.organization_minimum_retention_days is None
            else _retention_anchor_due(
                anchor=FlowRuntimeUploadedFiles.created_at,
                retention_days=proposal.organization_minimum_retention_days,
                previewed_at=previewed_at,
            )
        )
        current_due = sa.and_(
            current_delete_after_due,
            current_minimum_satisfied,
            sa.literal(not state.organization_no_purge, type_=sa.Boolean()),
        )
        proposed_due = sa.and_(
            proposed_delete_after_due,
            proposed_minimum_satisfied,
            sa.literal(not proposal.organization_no_purge, type_=sa.Boolean()),
        )
        proposed_policy_conflict = (
            proposal.runtime_upload_abandonment_days is not None
            and proposal.organization_minimum_retention_days is not None
            and proposal.runtime_upload_abandonment_days
            < proposal.organization_minimum_retention_days
        )
        newly_due = sa.and_(proposed_due, sa.not_(current_due))
        no_longer_due = sa.and_(current_due, sa.not_(proposed_due))
        attached_to_run = sa.exists(
            sa.select(1).where(
                FlowRunStepInputFiles.file_id == FlowRuntimeUploadedFiles.file_id,
                FlowRunStepInputFiles.tenant_id == FlowRuntimeUploadedFiles.tenant_id,
            )
        )
        return (
            sa.select(
                sa.func.count().filter(current_due).label("current_eligible_count"),
                sa.func.count().filter(proposed_due).label("proposed_eligible_count"),
                sa.func.count().filter(newly_due).label("newly_eligible_count"),
                sa.func.count().filter(no_longer_due).label("no_longer_eligible_count"),
                sa.func.coalesce(sa.func.sum(Files.size).filter(proposed_due), 0).label(
                    "proposed_eligible_bytes"
                ),
                sa.func.coalesce(sa.func.sum(Files.size).filter(newly_due), 0).label(
                    "newly_eligible_bytes"
                ),
                sa.func.min(FlowRuntimeUploadedFiles.created_at)
                .filter(proposed_due)
                .label("earliest_proposed_anchor"),
                sa.func.max(FlowRuntimeUploadedFiles.created_at)
                .filter(proposed_due)
                .label("latest_proposed_anchor"),
                sa.func.min(
                    _retention_deadline(
                        anchor=FlowRuntimeUploadedFiles.created_at,
                        retention_days=proposal.runtime_upload_abandonment_days,
                    )
                ).label("earliest_proposed_delete_after_at"),
                sa.func.max(
                    _retention_deadline(
                        anchor=FlowRuntimeUploadedFiles.created_at,
                        retention_days=proposal.runtime_upload_abandonment_days,
                    )
                ).label("latest_proposed_delete_after_at"),
                sa.func.min(
                    _retention_deadline(
                        anchor=FlowRuntimeUploadedFiles.created_at,
                        retention_days=proposal.organization_minimum_retention_days,
                    )
                ).label("earliest_proposed_minimum_not_before_at"),
                sa.func.max(
                    _retention_deadline(
                        anchor=FlowRuntimeUploadedFiles.created_at,
                        retention_days=proposal.organization_minimum_retention_days,
                    )
                ).label("latest_proposed_minimum_not_before_at"),
                sa.func.count()
                .filter(
                    proposed_delete_after_due,
                    sa.not_(proposed_minimum_satisfied),
                )
                .label("minimum_not_satisfied_count"),
                sa.func.count()
                .filter(
                    proposed_delete_after_due,
                    proposed_minimum_satisfied,
                    sa.literal(
                        proposal.organization_no_purge,
                        type_=sa.Boolean(),
                    ),
                )
                .label("no_purge_count"),
                sa.func.count()
                .filter(sa.literal(proposed_policy_conflict, type_=sa.Boolean()))
                .label("policy_conflict_count"),
            )
            .select_from(FlowRuntimeUploadedFiles)
            .join(
                Files,
                sa.and_(
                    Files.id == FlowRuntimeUploadedFiles.file_id,
                    Files.tenant_id == FlowRuntimeUploadedFiles.tenant_id,
                ),
            )
            .where(
                FlowRuntimeUploadedFiles.tenant_id == tenant_id,
                sa.not_(attached_to_run),
            )
        )

    async def cleanup_old_flow_runtime_data(self) -> FlowRuntimeCleanupCounts:
        now = datetime.now(timezone.utc)
        counts = _empty_flow_runtime_cleanup_counts()

        purge_result = await self._purge_all_old_flow_run_history(now=now)
        abandoned_upload_counts = await FlowRunHistoryPurgeRepository(
            self.session
        ).purge_abandoned_runtime_uploads(
            now=now,
            limit=RETENTION_BATCH_SIZE,
        )
        purge_counts = purge_result.counts.add(abandoned_upload_counts)
        counts["flow_runs_considered"] += purge_counts.flow_runs_considered
        counts["flow_runs_lock_deferred"] += purge_counts.flow_runs_lock_deferred
        counts["flow_runs_purged"] += purge_counts.flow_runs_purged
        counts["flow_generated_files_deleted"] += (
            purge_counts.flow_generated_files_deleted
        )
        counts["flow_runtime_source_candidates"] += (
            purge_counts.flow_runtime_source_candidates
        )
        counts["flow_runtime_source_candidate_bytes"] += (
            purge_counts.flow_runtime_source_candidate_bytes
        )
        counts["flow_runtime_source_bindings_deleted"] += (
            purge_counts.flow_runtime_source_bindings_deleted
        )
        counts["flow_runtime_source_files_deleted"] += (
            purge_counts.flow_runtime_source_files_deleted
        )
        counts["flow_runtime_source_bytes_deleted"] += (
            purge_counts.flow_runtime_source_bytes_deleted
        )
        counts["flow_webhook_deliveries_deleted"] += (
            purge_counts.flow_webhook_deliveries_deleted
        )
        counts["flow_audit_outbox_rows_deleted"] += (
            purge_counts.flow_audit_outbox_rows_deleted
        )
        counts["flow_review_checkpoints_deleted"] += (
            purge_counts.flow_review_checkpoints_deleted
        )
        template_asset_counts = await self.purge_soft_deleted_flow_template_assets(
            limit=RETENTION_BATCH_SIZE,
        )
        counts["flow_template_assets_purged"] += (
            template_asset_counts.flow_template_assets_purged
        )
        counts["flow_template_asset_files_deleted"] += (
            template_asset_counts.flow_template_asset_files_deleted
        )
        counts["flow_template_assets_skipped_published_reference"] += (
            template_asset_counts.flow_template_assets_skipped_published_reference
        )
        counts["flow_template_assets_skipped_undetermined_reference"] += (
            template_asset_counts.flow_template_assets_skipped_undetermined_reference
        )
        blocked_counts = await self.count_blocked_flow_run_history_purge_candidates(
            now=now
        )
        counts["flow_runs_skipped_undelivered_audit"] += (
            blocked_counts.skipped_undelivered_audit
        )
        counts["flow_runs_skipped_unresolved_webhook"] += (
            blocked_counts.skipped_unresolved_webhook
        )
        counts["flow_runs_skipped_active_rerun"] += blocked_counts.skipped_active_rerun

        if (
            blocked_counts.skipped_undelivered_audit > 0
            or blocked_counts.skipped_unresolved_webhook > 0
            or blocked_counts.skipped_active_rerun > 0
        ):
            logger.info(
                "Skipped Flow run-history purge candidates "
                "(undelivered_audit=%s, unresolved_webhook=%s, active_rerun=%s)",
                blocked_counts.skipped_undelivered_audit,
                blocked_counts.skipped_unresolved_webhook,
                blocked_counts.skipped_active_rerun,
            )

        if (
            template_asset_counts.flow_template_assets_skipped_undetermined_reference
            > 0
        ):
            logger.warning(
                "Skipped Flow template asset purge candidates because published "
                "definition references could not be determined (count=%s)",
                template_asset_counts.flow_template_assets_skipped_undetermined_reference,
            )

        debug_counts = await self.redact_old_flow_debug_evidence(now=now)
        counts["debug_step_results"] += debug_counts.debug_step_results
        counts["debug_step_attempts"] += debug_counts.debug_step_attempts
        counts["debug_provider_calls"] += debug_counts.debug_provider_calls
        counts["debug_resolved_input_aggregates"] += (
            debug_counts.debug_resolved_input_aggregates
        )
        counts["debug_resolved_input_edges"] += debug_counts.debug_resolved_input_edges
        return counts

    async def delete_old_delivered_flow_audit_outbox_rows(self) -> int:
        audit_log_exists = (
            sa.select(sa.literal(1))
            .select_from(AuditLogTable)
            .where(AuditLogTable.id == FlowRunAuditOutbox.id)
            .exists()
        )
        base_subquery = sa.select(FlowRunAuditOutbox.id).where(
            sa.and_(
                FlowRunAuditOutbox.delivery_status
                == FlowOutboxDeliveryStatus.DELIVERED.value,
                sa.not_(audit_log_exists),
            )
        )

        total_deleted = 0
        while True:
            batch_subquery = base_subquery.order_by(FlowRunAuditOutbox.id).limit(
                RETENTION_BATCH_SIZE
            )
            # Audit logs own delivered audit lifetime; the outbox mirror is
            # removed only after audit retention deletes the matching audit row.
            result = await self.session.execute(
                sa.delete(FlowRunAuditOutbox).where(
                    FlowRunAuditOutbox.id.in_(batch_subquery)
                )
            )
            batch_deleted = affected_row_count(result)
            if batch_deleted == 0:
                break
            total_deleted += batch_deleted
            logger.debug(
                "Deleted batch of %s delivered Flow audit outbox rows "
                "whose audit logs were already deleted by retention (total: %s)",
                batch_deleted,
                total_deleted,
            )

        if total_deleted > 0:
            logger.info(
                "Deleted %s delivered Flow audit outbox rows whose audit logs "
                "were already deleted by retention",
                total_deleted,
            )
        else:
            logger.debug("No delivered Flow audit outbox rows ready for cleanup")

        return total_deleted

    def _build_effective_retention_days(
        self,
        entity_retention_col: Any,
        space_retention_col: Any = Spaces.data_retention_days,
    ) -> Any:
        """
        Build COALESCE expression for hierarchical retention policy.

        The hierarchy is:
        1. Entity-level retention (Assistant/App specific)
        2. Space-level retention
        3. Tenant-level retention (if enabled)
        4. NULL (keep forever)

        Args:
            entity_retention_col: Column for entity-level retention (e.g., Assistants.data_retention_days)
            space_retention_col: Column for space-level retention (default: Spaces.data_retention_days)

        Returns:
            SQLAlchemy COALESCE expression
        """
        return sa.func.coalesce(
            entity_retention_col,
            space_retention_col,
            sa.case(
                (
                    AuditRetentionPolicy.conversation_retention_enabled.is_(True),
                    AuditRetentionPolicy.conversation_retention_days,
                ),
                else_=None,
            ),
        )

    async def _delete_old_records(
        self,
        record_table: type,
        entity_table: type,
        entity_retention_col: Any,
        entity_fk_col: Any,
        record_fk_col: Any,
        record_type: str,
    ) -> int:
        """
        Generic method to delete old records based on hierarchical retention policies.

        Uses batch deletion to prevent transaction timeouts on large datasets.

        Args:
            record_table: Table to delete from (e.g., Questions, AppRuns)
            entity_table: Parent entity table (e.g., Assistants, Apps)
            entity_retention_col: Entity's retention days column
            entity_fk_col: Foreign key column in entity table to Space
            record_fk_col: Foreign key column in record table to entity
            record_type: Human-readable record type for logging

        Returns:
            Number of records deleted
        """
        logger.info(
            f"Starting deletion of old {record_type} based on retention policies"
        )

        # Build effective retention days using hierarchy
        effective_retention_days = self._build_effective_retention_days(
            entity_retention_col
        )

        # Build base subquery to identify records to delete (will be limited per batch)
        base_subquery = cast(
            sa.Select[Any],
            sa.select(record_table.id)  # type: ignore[attr-defined]
            .join(entity_table, record_fk_col == entity_table.id)  # type: ignore[attr-defined]
            .join(Spaces, entity_fk_col == Spaces.id)
            .outerjoin(
                AuditRetentionPolicy, Spaces.tenant_id == AuditRetentionPolicy.tenant_id
            )
            .where(
                sa.and_(
                    effective_retention_days.isnot(None),
                    record_table.created_at  # type: ignore[attr-defined]
                    # make_interval signature: (years, months, weeks, days, hours, mins, secs)
                    < sa.func.now()
                    - sa.func.make_interval(0, 0, 0, effective_retention_days),
                )
            ),
        )

        # Batch deletion to prevent transaction timeouts on large datasets
        total_deleted = 0
        while True:
            # Delete batch of records (ORDER BY ensures deterministic batch selection)
            batch_subquery = base_subquery.order_by(record_table.id).limit(  # type: ignore[attr-defined]
                RETENTION_BATCH_SIZE
            )
            query = sa.delete(record_table).where(record_table.id.in_(batch_subquery))  # type: ignore[attr-defined]
            result = await self.session.execute(query)
            batch_deleted = affected_row_count(result)

            if batch_deleted == 0:
                break

            total_deleted += batch_deleted
            logger.debug(
                f"Deleted batch of {batch_deleted} {record_type} (total: {total_deleted})"
            )

        if total_deleted > 0:
            logger.info(
                f"Deleted {total_deleted} old {record_type} based on retention policies"
            )
        else:
            logger.debug(f"No old {record_type} to delete based on retention policies")

        return total_deleted

    async def delete_old_questions(self) -> int:
        """
        Delete old questions using hierarchical retention policy resolution:
        1. Assistant-level retention_days (if set)
        2. Space-level retention_days (if set)
        3. Tenant-level conversation_retention_days (if enabled)
        4. None (keep forever)

        Help-assistant runs (e.g. Prompt Guide) are intentionally NOT excluded
        here. Those conversations live in the regular questions table and the
        helper assistant ships a ``data_retention_days`` policy, so they are
        purged on the same schedule as any other assistant's data. Retention is
        a data-lifecycle concern (delete old rows) — distinct from the
        conversation-visibility invariant that hides helper sessions from
        listings / insights / analytics (sessions_repo, analysis_repo,
        token_usage). Preview counts and the delete both include helper rows,
        so they stay consistent with each other.

        Returns:
            Number of questions deleted
        """
        return await self._delete_old_records(
            record_table=Questions,
            entity_table=Assistants,
            entity_retention_col=Assistants.data_retention_days,
            entity_fk_col=Assistants.space_id,
            record_fk_col=Questions.assistant_id,
            record_type="questions",
        )

    async def delete_old_app_runs(self) -> int:
        """
        Delete old app runs using hierarchical retention policy resolution:
        1. App-level retention_days (if set)
        2. Space-level retention_days (if set)
        3. Tenant-level conversation_retention_days (if enabled)
        4. None (keep forever)

        Returns:
            Number of app runs deleted
        """
        return await self._delete_old_records(
            record_table=AppRuns,
            entity_table=Apps,
            entity_retention_col=Apps.data_retention_days,
            entity_fk_col=Apps.space_id,
            record_fk_col=AppRuns.app_id,
            record_type="app runs",
        )

    async def delete_old_sessions(self) -> int:
        """
        Delete orphaned sessions that have no questions.

        Sessions without questions are deleted after ORPHANED_SESSION_CLEANUP_DAYS.
        Uses batch deletion to prevent transaction timeouts on large datasets.

        Returns:
            Number of sessions deleted
        """
        logger.info(
            f"Starting deletion of orphaned sessions older than {ORPHANED_SESSION_CLEANUP_DAYS} day(s)"
        )

        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(
            0, 0, 0, ORPHANED_SESSION_CLEANUP_DAYS
        )

        # Build base subquery to identify orphaned sessions (will be limited per batch)
        base_subquery = (
            sa.select(Sessions.id)
            .outerjoin(Questions, Sessions.id == Questions.session_id)
            .where(sa.and_(Sessions.created_at < cutoff_expr, Questions.id.is_(None)))
        )

        # Batch deletion to prevent transaction timeouts on large datasets
        total_deleted = 0
        while True:
            # ORDER BY ensures deterministic batch selection
            batch_subquery = base_subquery.order_by(Sessions.id).limit(
                RETENTION_BATCH_SIZE
            )
            query = sa.delete(Sessions).where(Sessions.id.in_(batch_subquery))
            result = await self.session.execute(query)
            batch_deleted = affected_row_count(result)

            if batch_deleted == 0:
                break

            total_deleted += batch_deleted
            logger.debug(
                f"Deleted batch of {batch_deleted} orphaned sessions (total: {total_deleted})"
            )

        if total_deleted > 0:
            logger.info(f"Deleted {total_deleted} orphaned sessions")
        else:
            logger.debug("No orphaned sessions to delete")

        return total_deleted

    def _build_due_builder_session_retention_query(
        self, *, now: datetime
    ) -> sa.Select[tuple[UUID]]:
        effective_retention_days = self._build_effective_retention_days(sa.null())
        return (
            sa.select(BuilderSessions.id.label("session_id"))
            .join(Spaces, BuilderSessions.space_id == Spaces.id)
            .outerjoin(
                AuditRetentionPolicy, Spaces.tenant_id == AuditRetentionPolicy.tenant_id
            )
            .where(
                sa.and_(
                    BuilderSessions.status.in_(
                        RETENTION_ELIGIBLE_BUILDER_SESSION_STATUS_VALUES
                    ),
                    _builder_session_has_no_fresh_send_lock(now),
                    effective_retention_days.isnot(None),
                    BuilderSessions.updated_at
                    < sa.literal(now)
                    - sa.func.make_interval(0, 0, 0, effective_retention_days),
                )
            )
        )

    async def count_expired_builder_sessions(self, *, now: datetime) -> int:
        candidate_subquery = self._build_due_builder_session_retention_query(
            now=now
        ).subquery()
        count = await self.session.scalar(
            sa.select(sa.func.count()).select_from(candidate_subquery)
        )
        return count or 0

    async def delete_expired_builder_sessions(self, *, now: datetime) -> int:
        logger.info("Starting deletion of expired Builder sessions")
        base_subquery = self._build_due_builder_session_retention_query(now=now)

        total_deleted = 0
        while True:
            batch_subquery = base_subquery.order_by(
                BuilderSessions.updated_at,
                BuilderSessions.id,
            ).limit(RETENTION_BATCH_SIZE)
            result = await self.session.execute(
                sa.delete(BuilderSessions).where(BuilderSessions.id.in_(batch_subquery))
            )
            batch_deleted = affected_row_count(result)
            if batch_deleted == 0:
                break

            total_deleted += batch_deleted
            logger.debug(
                "Deleted batch of %s expired Builder sessions (total: %s)",
                batch_deleted,
                total_deleted,
            )

        if total_deleted > 0:
            logger.info(
                "Deleted %s expired Builder sessions",
                total_deleted,
            )
        else:
            logger.debug("No expired Builder sessions to delete")

        return total_deleted

    async def get_affected_questions_count_for_assistant(
        self, assistant_id: UUID, retention_days: int
    ) -> int:
        """Get count of questions that would be deleted for a specific assistant."""
        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        query = sa.select(sa.func.count(Questions.id)).where(
            sa.and_(
                Questions.assistant_id == assistant_id,
                Questions.created_at < cutoff_expr,
            )
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_affected_app_runs_count_for_app(
        self, app_id: UUID, retention_days: int
    ) -> int:
        """Get count of app runs that would be deleted for a specific app."""
        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        query = sa.select(sa.func.count(AppRuns.id)).where(
            sa.and_(AppRuns.app_id == app_id, AppRuns.created_at < cutoff_expr)
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def _purge_all_old_flow_run_history(
        self, *, now: datetime
    ) -> FlowRunHistoryPurgeResult:
        total_result = FlowRunHistoryPurgeResult()

        while True:
            batch_result = await self.purge_old_flow_run_history_batch(
                now=now,
                limit=RETENTION_BATCH_SIZE,
            )
            total_result = total_result.add(batch_result)
            if batch_result.counts.flow_runs_lock_deferred > 0:
                break
            if (
                batch_result.counts.flow_runs_purged == 0
                and batch_result.counts.flow_runs_considered == 0
            ):
                break
            # A nondeferred recheck rejection is mirrored by the next selector,
            # so this loop advances without polling the same ineligible run.

        return total_result

    async def purge_soft_deleted_flow_template_assets(
        self,
        *,
        limit: int,
    ) -> FlowTemplateAssetPurgeCounts:
        return await FlowRunHistoryPurgeRepository(
            self.session
        ).purge_soft_deleted_template_assets(limit=limit)

    async def purge_old_flow_run_history_batch(
        self, *, now: datetime, limit: int
    ) -> FlowRunHistoryPurgeResult:
        run_ids = await self._select_flow_run_history_purge_batch(
            now=now,
            limit=limit,
        )
        return await FlowRunHistoryPurgeRepository(self.session).purge_run_history(
            run_ids
        )

    async def count_blocked_flow_run_history_purge_candidates(
        self, *, now: datetime
    ) -> FlowRunHistoryPurgeBlockedCounts:
        due_runs = self._build_due_flow_run_history_purge_query(now=now).subquery()
        run_id_col = due_runs.c.run_id
        undelivered_audit_exists = flow_run_undelivered_audit_exists(run_id_col)
        unresolved_webhook_exists = flow_run_unresolved_webhook_exists(run_id_col)
        active_rerun_exists = flow_run_active_rerun_exists(run_id_col)

        undelivered_audit_count, unresolved_webhook_count, active_rerun_count = (
            await self.session.execute(
                sa.select(
                    sa.func.count().filter(undelivered_audit_exists),
                    sa.func.count().filter(
                        sa.not_(undelivered_audit_exists),
                        unresolved_webhook_exists,
                    ),
                    sa.func.count().filter(
                        sa.not_(undelivered_audit_exists),
                        sa.not_(unresolved_webhook_exists),
                        active_rerun_exists,
                    ),
                ).select_from(due_runs)
            )
        ).one()

        return FlowRunHistoryPurgeBlockedCounts(
            skipped_undelivered_audit=undelivered_audit_count,
            skipped_unresolved_webhook=unresolved_webhook_count,
            skipped_active_rerun=active_rerun_count,
        )

    async def _select_flow_run_history_purge_batch(
        self, *, now: datetime, limit: int
    ) -> list[UUID]:
        retention_anchor = self._flow_run_history_retention_anchor()
        stmt = (
            self._build_due_flow_run_history_purge_query(now=now)
            .where(sa.not_(flow_run_undelivered_audit_exists(FlowRuns.id)))
            .where(sa.not_(flow_run_unresolved_webhook_exists(FlowRuns.id)))
            .where(sa.not_(flow_run_active_rerun_exists(FlowRuns.id)))
            .order_by(retention_anchor, FlowRuns.id)
            .limit(limit)
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    @staticmethod
    def _flow_run_history_retention_anchor() -> Any:
        return sa.func.coalesce(FlowRuns.finished_at, FlowRuns.created_at)

    def _build_due_flow_run_history_purge_query(
        self, *, now: datetime
    ) -> sa.Select[tuple[UUID]]:
        anchor = self._flow_run_history_retention_anchor()
        envelope = self.flow_run_history_retention_sql_envelope(
            organization_days=(
                Tenants.flow_run_history_retention_days.__clause_element__()
            ),
            classification_days=(
                FlowClassificationRetentionPolicies.data_retention_days.__clause_element__()
            ),
            space_days=Spaces.data_retention_days.__clause_element__(),
            flow_days=Flows.data_retention_days.__clause_element__(),
            organization_minimum_days=(
                Tenants.flow_run_history_minimum_retention_days.__clause_element__()
            ),
            classification_minimum_days=(
                FlowClassificationRetentionPolicies.minimum_retention_days.__clause_element__()
            ),
            organization_no_purge=(
                Tenants.flow_run_history_no_purge.__clause_element__()
            ),
            classification_no_purge=(
                FlowClassificationRetentionPolicies.no_purge.__clause_element__()
            ),
        )
        eligibility = envelope.eligibility(anchor=anchor, at=now)
        return (
            sa.select(FlowRuns.id.label("run_id"))
            .join(Flows, FlowRuns.flow_id == Flows.id)
            .join(Spaces, Flows.space_id == Spaces.id)
            .join(Tenants, FlowRuns.tenant_id == Tenants.id)
            .outerjoin(
                FlowClassificationRetentionPolicies,
                sa.and_(
                    FlowClassificationRetentionPolicies.security_classification_id
                    == Spaces.security_classification_id,
                    FlowClassificationRetentionPolicies.tenant_id == Spaces.tenant_id,
                ),
            )
            .where(
                sa.and_(
                    FlowRuns.status.in_(TERMINAL_FLOW_RUN_STATUS_VALUES),
                    # Constant lower bound for ix_flow_runs_terminal_retention_anchor;
                    # safe because every retention source is >= MIN_RETENTION_DAYS.
                    anchor
                    <= sa.literal(now)
                    - sa.func.make_interval(0, 0, 0, MIN_RETENTION_DAYS),
                    eligibility.eligible,
                )
            )
        )

    async def redact_old_flow_debug_evidence(
        self, *, now: datetime
    ) -> FlowDebugRedactionCounts:
        total_counts = FlowDebugRedactionCounts()

        async for terminal_runs in self._iter_flow_debug_retention_rows(
            older_than=now - timedelta(days=1)
        ):
            debug_actions: dict[UUID, _FlowRuntimeRetentionAction] = {}

            for row in terminal_runs:
                anchor = row["retention_anchor"]
                if anchor is None:
                    continue
                run_id = cast(UUID, row["run_id"])
                tenant_id = cast(UUID, row["tenant_id"])
                trace_id = cast(UUID, row["trace_id"])
                policy = resolve_flow_retention_policy(row["flow_settings"])
                debug_retention_days = policy.debug_evidence_days()
                if debug_retention_days is not None and anchor <= now - timedelta(
                    days=debug_retention_days
                ):
                    debug_actions[run_id] = _FlowRuntimeRetentionAction(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        trace_id=trace_id,
                        cutoff=now - timedelta(days=debug_retention_days),
                        policy_source=(
                            "tenant.flow_settings.retention_policy."
                            "run_debug_evidence_days"
                        ),
                        cleanup_timestamp=now,
                    )

            if debug_actions:
                debug_counts = await self._cleanup_old_flow_debug_evidence(
                    debug_actions
                )
                total_counts = FlowDebugRedactionCounts(
                    debug_step_results=(
                        total_counts.debug_step_results
                        + debug_counts["debug_step_results"]
                    ),
                    debug_step_attempts=(
                        total_counts.debug_step_attempts
                        + debug_counts["debug_step_attempts"]
                    ),
                    debug_provider_calls=(
                        total_counts.debug_provider_calls
                        + debug_counts["debug_provider_calls"]
                    ),
                    debug_resolved_input_aggregates=(
                        total_counts.debug_resolved_input_aggregates
                        + debug_counts["debug_resolved_input_aggregates"]
                    ),
                    debug_resolved_input_edges=(
                        total_counts.debug_resolved_input_edges
                        + debug_counts["debug_resolved_input_edges"]
                    ),
                )

        return total_counts

    async def _iter_flow_debug_retention_rows(self, *, older_than: datetime):
        anchor = sa.func.coalesce(FlowRuns.finished_at, FlowRuns.created_at)
        last_run_id: UUID | None = None
        while True:
            stmt = (
                sa.select(
                    FlowRuns.id.label("run_id"),
                    FlowRuns.tenant_id.label("tenant_id"),
                    FlowRuns.trace_id.label("trace_id"),
                    anchor.label("retention_anchor"),
                    Tenants.flow_settings.label("flow_settings"),
                )
                .join(Tenants, FlowRuns.tenant_id == Tenants.id)
                .where(
                    sa.and_(
                        FlowRuns.status.in_(TERMINAL_FLOW_RUN_STATUS_VALUES),
                        anchor < older_than,
                        FlowRuns.id > last_run_id
                        if last_run_id is not None
                        else sa.true(),
                    )
                )
                .order_by(FlowRuns.id)
                .limit(RETENTION_BATCH_SIZE)
            )
            result = await self.session.execute(stmt)
            rows = [dict(row) for row in result.mappings().all()]
            if not rows:
                break
            last_run_id = cast(UUID, rows[-1]["run_id"])
            yield rows

    async def _cleanup_old_flow_debug_evidence(
        self, actions_by_run_id: dict[UUID, _FlowRuntimeRetentionAction]
    ) -> FlowRuntimeCleanupCounts:
        if not actions_by_run_id:
            return _empty_flow_runtime_cleanup_counts()

        step_result_stmt = sa.select(
            FlowStepResults.id,
            FlowStepResults.flow_run_id,
            FlowStepResults.input_payload_json,
            FlowStepResults.effective_prompt,
            FlowStepResults.output_payload_json,
            FlowStepResults.model_parameters_json,
        ).where(FlowStepResults.flow_run_id.in_(set(actions_by_run_id)))
        step_result_rows = await self.session.execute(step_result_stmt)
        debug_step_results = 0
        for row in step_result_rows.fetchall():
            action = actions_by_run_id[row.flow_run_id]
            pruned_output = _prune_debug_payload(row.output_payload_json)
            object_id = str(row.id)
            has_marker = has_retention_tombstone(
                pruned_output,
                data_class="run_debug_evidence",
                object_type="flow_step_result",
                object_id=object_id,
                retention_state="retention_purged",
            )
            counts = _debug_tombstone_counts(row, row.output_payload_json)
            needs_update = (
                any(
                    value is not None
                    for value in (
                        row.input_payload_json,
                        row.effective_prompt,
                        row.model_parameters_json,
                    )
                )
                or pruned_output != row.output_payload_json
                or (counts is not None and not has_marker)
            )
            if not needs_update:
                continue
            output_payload = (
                append_retention_tombstone(
                    pruned_output,
                    _build_retention_tombstone(
                        action=action,
                        data_class="run_debug_evidence",
                        object_type="flow_step_result",
                        object_id=object_id,
                        retention_state="retention_purged",
                        counts=counts,
                    ),
                )
                if counts is not None and not has_marker
                else pruned_output
            )
            result = await self.session.execute(
                sa.update(FlowStepResults)
                .where(FlowStepResults.id == row.id)
                .values(
                    input_payload_json=None,
                    effective_prompt=None,
                    output_payload_json=output_payload,
                    model_parameters_json=None,
                )
            )
            debug_step_results += affected_row_count(result)

        attempt_stmt = (
            sa.select(
                FlowStepAttempts.id,
                FlowStepAttempts.flow_run_id,
                FlowStepAttempts.provenance_json,
                FlowStepAttempts.input_payload_json,
                FlowStepAttempts.output_payload_json,
            )
            .where(
                FlowStepAttempts.flow_run_id.in_(set(actions_by_run_id)),
                sa.or_(
                    FlowStepAttempts.provenance_json.is_not(None),
                    FlowStepAttempts.input_payload_json.is_not(None),
                    FlowStepAttempts.output_payload_json.is_not(None),
                    sa.exists().where(
                        FlowProviderCalls.flow_step_attempt_id == FlowStepAttempts.id
                    ),
                    sa.exists().where(
                        FlowStepAttemptResolvedInputs.flow_step_attempt_id
                        == FlowStepAttempts.id
                    ),
                ),
            )
            .with_for_update(of=FlowStepAttempts)
        )
        attempt_rows = await self.session.execute(attempt_stmt)
        locked_attempts = attempt_rows.fetchall()
        attempt_ids = [row.id for row in locked_attempts]

        provider_call_counts: dict[UUID, int] = {}
        provider_call_usage: dict[UUID, FlowRunTokenUsage] = {}
        resolved_input_counts: dict[UUID, tuple[int, int]] = {}
        if attempt_ids:
            # Provider calls reference the resolved-input row; delete them first.
            deleted_provider_calls = (
                sa.delete(FlowProviderCalls)
                .where(FlowProviderCalls.flow_step_attempt_id.in_(attempt_ids))
                .returning(
                    FlowProviderCalls.flow_step_attempt_id,
                    FlowProviderCalls.status,
                    FlowProviderCalls.num_tokens_input,
                    FlowProviderCalls.num_tokens_output,
                    FlowProviderCalls.input_source,
                    FlowProviderCalls.output_source,
                )
                .cte("deleted_flow_provider_calls")
            )
            provider_call_rows = await self.session.stream(
                sa.select(
                    deleted_provider_calls.c.flow_step_attempt_id,
                    deleted_provider_calls.c.status,
                    deleted_provider_calls.c.num_tokens_input,
                    deleted_provider_calls.c.num_tokens_output,
                    deleted_provider_calls.c.input_source,
                    deleted_provider_calls.c.output_source,
                ).execution_options(yield_per=RETENTION_BATCH_SIZE)
            )
            async for provider_call in provider_call_rows:
                attempt_id = provider_call.flow_step_attempt_id
                provider_call_counts[attempt_id] = (
                    provider_call_counts.get(attempt_id, 0) + 1
                )
                call_usage = FlowRunTokenUsage.from_provider_calls(
                    (
                        FlowProviderCallTokenUsage(
                            status=provider_call.status,
                            num_tokens_input=provider_call.num_tokens_input,
                            num_tokens_output=provider_call.num_tokens_output,
                            input_source=provider_call.input_source,
                            output_source=provider_call.output_source,
                        ),
                    )
                )
                if call_usage is not None:
                    combined_usage = FlowRunTokenUsage.combine(
                        usage
                        for usage in (provider_call_usage.get(attempt_id), call_usage)
                        if usage is not None
                    )
                    assert combined_usage is not None
                    provider_call_usage[attempt_id] = combined_usage

            resolved_input_delete_result = await self.session.execute(
                sa.delete(FlowStepAttemptResolvedInputs)
                .where(
                    FlowStepAttemptResolvedInputs.flow_step_attempt_id.in_(attempt_ids)
                )
                .returning(
                    FlowStepAttemptResolvedInputs.flow_step_attempt_id,
                    FlowStepAttemptResolvedInputs.resolved_input_edge_count,
                )
            )
            for attempt_id, edge_count in resolved_input_delete_result:
                aggregate_count, previous_edge_count = resolved_input_counts.get(
                    attempt_id, (0, 0)
                )
                resolved_input_counts[attempt_id] = (
                    aggregate_count + 1,
                    previous_edge_count + edge_count,
                )

        debug_step_attempts = 0
        for row in locked_attempts:
            action = actions_by_run_id[row.flow_run_id]
            previous_counts = parse_attempt_retention_counts(
                row.provenance_json,
                tenant_id=action.tenant_id,
                run_id=row.flow_run_id,
                attempt_id=row.id,
            )
            provenance_to_clear = (
                None if previous_counts is not None else row.provenance_json
            )
            newly_cleared_field_count = sum(
                value is not None
                for value in (
                    provenance_to_clear,
                    row.input_payload_json,
                    row.output_payload_json,
                )
            )
            provider_call_count = provider_call_counts.get(row.id, 0)
            (
                resolved_input_aggregate_count,
                resolved_input_edge_count,
            ) = resolved_input_counts.get(row.id, (0, 0))
            if (
                newly_cleared_field_count == 0
                and provider_call_count == 0
                and resolved_input_aggregate_count == 0
            ):
                continue
            previous_cleared_field_count = (
                previous_counts.cleared_field_count
                if previous_counts is not None
                else 0
            )
            previous_provider_call_count = (
                previous_counts.provider_call_count
                if previous_counts is not None
                else 0
            )
            previous_resolved_input_aggregate_count = (
                previous_counts.resolved_input_aggregate_count
                if previous_counts is not None
                else 0
            )
            previous_resolved_input_edge_count = (
                previous_counts.resolved_input_edge_count
                if previous_counts is not None
                else 0
            )
            new_token_usage = provider_call_usage.get(row.id)
            previous_token_usage = (
                previous_counts.token_usage if previous_counts is not None else None
            )
            previous_token_usage_state = (
                previous_counts.token_usage_state
                if previous_counts is not None
                else "not_recorded"
            )
            if (
                previous_provider_call_count > 0
                and previous_token_usage_state == "unknown"
            ):
                token_usage = None
                token_usage_state = "unknown"
            else:
                token_usage = FlowRunTokenUsage.combine(
                    usage
                    for usage in (previous_token_usage, new_token_usage)
                    if usage is not None
                )
                token_usage_state = (
                    "recorded" if token_usage is not None else "not_recorded"
                )
            marker = _build_attempt_retention_marker(
                action=action,
                object_id=str(row.id),
                counts=RunDebugAttemptRetentionCounts(
                    cleared_field_count=(
                        previous_cleared_field_count + newly_cleared_field_count
                    ),
                    provider_call_count=(
                        previous_provider_call_count + provider_call_count
                    ),
                    resolved_input_aggregate_count=(
                        previous_resolved_input_aggregate_count
                        + resolved_input_aggregate_count
                    ),
                    resolved_input_edge_count=(
                        previous_resolved_input_edge_count + resolved_input_edge_count
                    ),
                    token_usage_state=token_usage_state,
                    token_usage=token_usage,
                ),
            )
            attempt_result = await self.session.execute(
                sa.update(FlowStepAttempts)
                .where(FlowStepAttempts.id == row.id)
                .values(
                    provenance_json=marker,
                    input_payload_json=None,
                    output_payload_json=None,
                )
            )
            debug_step_attempts += affected_row_count(attempt_result)

        deleted_provider_calls = sum(provider_call_counts.values())
        deleted_resolved_input_aggregates = sum(
            aggregate_count for aggregate_count, _ in resolved_input_counts.values()
        )
        deleted_resolved_input_edges = sum(
            edge_count for _, edge_count in resolved_input_counts.values()
        )

        counts = _empty_flow_runtime_cleanup_counts()
        counts["debug_step_results"] = debug_step_results
        counts["debug_step_attempts"] = debug_step_attempts
        counts["debug_provider_calls"] = deleted_provider_calls
        counts["debug_resolved_input_aggregates"] = deleted_resolved_input_aggregates
        counts["debug_resolved_input_edges"] = deleted_resolved_input_edges
        return counts

    async def get_affected_questions_count_for_space(
        self, space_id: UUID, retention_days: int
    ) -> int:
        """Get count of questions that would be deleted across all assistants in a space."""
        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        query = (
            sa.select(sa.func.count(Questions.id))
            .join(Assistants, Questions.assistant_id == Assistants.id)
            .where(
                sa.and_(
                    Assistants.space_id == space_id,
                    Questions.created_at < cutoff_expr,
                    # Only count questions that don't have assistant-level retention
                    # (those would use their own retention policy)
                    Assistants.data_retention_days.is_(None),
                )
            )
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_affected_app_runs_count_for_space(
        self, space_id: UUID, retention_days: int
    ) -> int:
        """Get count of app runs that would be deleted across all apps in a space."""
        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        query = (
            sa.select(sa.func.count(AppRuns.id))
            .join(Apps, AppRuns.app_id == Apps.id)
            .where(
                sa.and_(
                    Apps.space_id == space_id,
                    AppRuns.created_at < cutoff_expr,
                    # Only count app runs that don't have app-level retention
                    Apps.data_retention_days.is_(None),
                )
            )
        )

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_affected_total_count_for_tenant(
        self, tenant_id: UUID, retention_days: int
    ) -> dict[str, int]:
        """Get count of questions and app runs that would be deleted tenant-wide."""
        # Use DB time (sa.func.now()) for consistency with deletion logic
        # make_interval signature: (years, months, weeks, days, hours, mins, secs)
        cutoff_expr = sa.func.now() - sa.func.make_interval(0, 0, 0, retention_days)

        # Count questions without assistant or space level retention
        questions_query = (
            sa.select(sa.func.count(Questions.id))
            .join(Assistants, Questions.assistant_id == Assistants.id)
            .join(Spaces, Assistants.space_id == Spaces.id)
            .where(
                sa.and_(
                    Spaces.tenant_id == tenant_id,
                    Questions.created_at < cutoff_expr,
                    Assistants.data_retention_days.is_(None),
                    Spaces.data_retention_days.is_(None),
                )
            )
        )

        # Count app runs without app or space level retention
        app_runs_query = (
            sa.select(sa.func.count(AppRuns.id))
            .join(Apps, AppRuns.app_id == Apps.id)
            .join(Spaces, Apps.space_id == Spaces.id)
            .where(
                sa.and_(
                    Spaces.tenant_id == tenant_id,
                    AppRuns.created_at < cutoff_expr,
                    Apps.data_retention_days.is_(None),
                    Spaces.data_retention_days.is_(None),
                )
            )
        )

        questions_result = await self.session.execute(questions_query)
        app_runs_result = await self.session.execute(app_runs_query)

        questions_count = questions_result.scalar() or 0
        app_runs_count = app_runs_result.scalar() or 0

        return {
            "questions": questions_count,
            "app_runs": app_runs_count,
            "total": questions_count + app_runs_count,
        }


def _retention_anchor_due(
    *,
    anchor: sa.ColumnExpressionArgument[datetime],
    retention_days: int | None,
    previewed_at: datetime,
) -> sa.ColumnElement[bool]:
    if retention_days is None:
        return sa.false()
    return anchor <= sa.literal(previewed_at) - sa.func.make_interval(
        0,
        0,
        0,
        retention_days,
    )


def _retention_deadline(
    *,
    anchor: sa.ColumnExpressionArgument[datetime],
    retention_days: int | None,
) -> sa.ColumnElement[datetime | None]:
    if retention_days is None:
        return cast(sa.ColumnElement[datetime | None], sa.null())
    return cast(
        sa.ColumnElement[datetime | None],
        anchor + sa.func.make_interval(0, 0, 0, retention_days),
    )


def _flow_retention_data_impact_from_row(
    row: RowMapping,
) -> FlowRetentionDataImpact:
    def optional_datetime(key: str) -> datetime | None:
        value = row[key]
        return value if isinstance(value, datetime) else None

    return FlowRetentionDataImpact(
        current_eligible_count=_retention_row_int(row, "current_eligible_count"),
        proposed_eligible_count=_retention_row_int(row, "proposed_eligible_count"),
        newly_eligible_count=_retention_row_int(row, "newly_eligible_count"),
        no_longer_eligible_count=_retention_row_int(
            row,
            "no_longer_eligible_count",
        ),
        proposed_eligible_bytes=_retention_row_int(row, "proposed_eligible_bytes"),
        newly_eligible_bytes=_retention_row_int(row, "newly_eligible_bytes"),
        earliest_proposed_anchor=optional_datetime("earliest_proposed_anchor"),
        latest_proposed_anchor=optional_datetime("latest_proposed_anchor"),
        earliest_proposed_delete_after_at=optional_datetime(
            "earliest_proposed_delete_after_at"
        ),
        latest_proposed_delete_after_at=optional_datetime(
            "latest_proposed_delete_after_at"
        ),
        earliest_proposed_minimum_not_before_at=optional_datetime(
            "earliest_proposed_minimum_not_before_at"
        ),
        latest_proposed_minimum_not_before_at=optional_datetime(
            "latest_proposed_minimum_not_before_at"
        ),
    )


def _retention_row_int(row: RowMapping, key: str) -> int:
    value = row[key]
    return value if isinstance(value, int) else 0


def _prune_debug_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    payload_dict = cast(dict[str, Any], payload)
    pruned: dict[str, Any] = dict(payload_dict)
    pruned.pop("template_fill_debug", None)
    return pruned


def _debug_tombstone_counts(
    row: Any, output_payload: Any
) -> RunDebugStepResultRetentionCounts | None:
    cleared_fields = sum(
        1
        for value in (
            row.input_payload_json,
            row.effective_prompt,
            row.model_parameters_json,
        )
        if value is not None
    )
    pruned_output_keys = int(
        isinstance(output_payload, dict) and "template_fill_debug" in output_payload
    )
    if cleared_fields == 0 and pruned_output_keys == 0:
        return None
    return RunDebugStepResultRetentionCounts(
        cleared_field_count=cleared_fields,
        pruned_output_key_count=pruned_output_keys,
    )


def _build_retention_tombstone(
    *,
    action: _FlowRuntimeRetentionAction,
    data_class: FlowRetentionDataClass,
    object_type: FlowRetentionObjectType,
    object_id: str,
    retention_state: FlowRetentionState,
    counts: FlowRetentionTombstoneCounts,
) -> FlowRetentionTombstone:
    return FlowRetentionTombstone(
        tenant_id=str(action.tenant_id),
        run_id=str(action.run_id),
        trace_id=str(action.trace_id),
        data_class=data_class,
        object_type=object_type,
        object_id=object_id,
        policy_source=action.policy_source,
        cutoff=action.cutoff,
        actor_source=FLOW_RETENTION_ACTOR_SOURCE,
        counts=counts,
        timestamp=action.cleanup_timestamp,
        retention_state=retention_state,
    )


def _build_attempt_retention_marker(
    *,
    action: _FlowRuntimeRetentionAction,
    object_id: str,
    counts: RunDebugAttemptRetentionCounts,
) -> dict[str, Any]:
    return FlowAttemptRetentionMarker(
        tombstone=_build_retention_tombstone(
            action=action,
            data_class="run_debug_evidence",
            object_type="flow_step_attempt",
            object_id=object_id,
            retention_state="retention_purged",
            counts=counts,
        )
    ).to_payload()
