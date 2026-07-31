from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from eneo.files.file_models import File
from eneo.files.file_repo import FileRepository
from eneo.flows.application.flow_run_access_policy import (
    FlowRunAccessKind,
    FlowRunAccessPolicy,
)
from eneo.flows.application.flow_run_evidence import (
    EvidenceExportDetail,
    EvidenceLimitIdentifier,
    EvidenceSectionIdentifier,
    RunViewEvidenceLogicalByteOmission,
    RunViewEvidenceOmission,
    RunViewEvidenceParentOmission,
    RunViewEvidenceRowOmission,
    RunViewPassageOmission,
    exported_passage_bytes,
    omit_passages_beyond_view_budget,
    withhold_attempt_passages,
)
from eneo.flows.application.flow_run_evidence_bundle import (
    EvidenceBundle,
    RedactedEvidenceBundle,
    build_evidence_bundle,
    redact_evidence_bundle,
)
from eneo.flows.application.flow_run_evidence_export_manifest import (
    EvidenceExportContext,
    evidence_export_actor_from_principal,
)
from eneo.flows.application.flow_run_export_json import render_evidence_json_export
from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRun,
    FlowStepAttempt,
)
from eneo.flows.domain.provider_call import ProviderCallEvidencePage
from eneo.flows.domain.rag_evidence_policy import (
    FlowRagEvidencePolicy,
    resolve_flow_rag_evidence_policy,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.infrastructure.flow_provider_call_repo import (
    FlowProviderCallNotFoundError,
    FlowProviderCallRepository,
)
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunRepository,
    StepAttemptEvidenceSize,
)
from eneo.flows.infrastructure.flow_run_rerun_repo import (
    FlowRunRerunEvidenceAdmissionReason,
    FlowRunRerunRepository,
)
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRepository,
)
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.principal import FlowPrincipal
from eneo.main.exceptions import (
    FileTooLargeException,
    NotFoundException,
    ResourceGoneException,
    UnauthorizedException,
)
from eneo.users.user import UserInDB

EMBEDDED_PROVIDER_CALL_LIMIT = 100
PROVIDER_CALL_PAGE_MAX_LIMIT = 500
PROVIDER_CALL_EXPORT_MAX_EVENTS = 10_000
# An export refuses rather than truncates, so this is a hard boundary on the
# whole document, not a tenant policy. It sits well above the per-run view
# budget so an export stays possible for runs the view has to trim.
EVIDENCE_EXPORT_MAX_PASSAGE_BYTES = 64 * 1024 * 1024
# A separate materialization guard, distinct from the passage limit above and
# never reported as one: it bounds the stored size of ALL provenance a single
# request may load — RAG or not — because loading is the cost the passage
# limit alone cannot see. Stored jsonb is a compressed floor on serialized
# size, so exceeding this guard means the real cost is at least this large.
EVIDENCE_EXPORT_MAX_STORED_PROVENANCE_BYTES = 256 * 1024 * 1024
# Fan-out ceilings keep every emitted section finite even when its rows carry
# no JSON. They are fixed synchronous-export invariants, not tenant policy.
EVIDENCE_EXPORT_DEFAULT_FAN_OUT_ROW_CEILING = 10_000
# Complete raw and redacted route measurements, including validation, hashing,
# redaction and indented JSON rendering, peaked below twelve times the logical
# projection size. Keep the admitted projection below one twelfth of the fixed
# per-request memory budget so those copies cannot exhaust the worker.
EVIDENCE_EXPORT_REQUEST_MEMORY_BUDGET_BYTES = 256 * 1024 * 1024
EVIDENCE_EXPORT_MEASURED_PEAK_MEMORY_MULTIPLIER = 12
# Fixed fields on the widest row projection serialize to about 1 KiB once UUIDs,
# timestamps, keys and punctuation are included. Double that measured shape to
# charge section containers and the debug projection before applying the peak
# multiplier above.
EVIDENCE_EXPORT_SERIALIZED_ROW_FLOOR_BYTES = 2 * 1024
EVIDENCE_EXPORT_MAX_AGGREGATE_STORED_JSON_BYTES = 256 * 1024 * 1024
EVIDENCE_EXPORT_MAX_AGGREGATE_LOGICAL_JSON_BYTES = (
    EVIDENCE_EXPORT_REQUEST_MEMORY_BUDGET_BYTES
    // EVIDENCE_EXPORT_MEASURED_PEAK_MEMORY_MULTIPLIER
)
# An interactive view bounds what it loads by rows, logical bytes, AND exact
# recorded passage bytes. Current attempts are admitted first and consume
# the budgets first; when even a current attempt does not fit, the response
# says so rather than pretending it never existed. Memory-protection
# invariants for one request, not operator policy.
RUN_VIEW_MAX_LOADED_ATTEMPTS = 500
RUN_VIEW_MAX_LOADED_LOGICAL_BYTES = 32 * 1024 * 1024
RUN_VIEW_MAX_LOADED_PASSAGE_BYTES = 64 * 1024 * 1024
RUN_VIEW_MAX_LOADED_SECTION_ROWS = 500
RUN_VIEW_MAX_LOADED_SECTION_LOGICAL_BYTES = 16 * 1024 * 1024
# Recovery guidance travels in the error context because clients read the
# typed response body; a server-side hint field they never receive is not
# remediation.
_EVIDENCE_EXPORT_TOO_LARGE_HINT = (
    "Inspect this run in the run view, page provider-call events where "
    "available, or reduce retained evidence for future runs. An export never "
    "returns a partial document."
)


@dataclass(frozen=True, slots=True)
class _EvidenceSectionUsage:
    section: EvidenceSectionIdentifier
    row_count: int
    stored_json_bytes: int
    logical_json_bytes: int


class FlowRunEvidenceService:
    """Owns Flow run evidence assembly, export, and artifact file access.

    Provider-call storage owns token aggregation; this service attaches that
    projection to evidence exports. Step-result inspection and lifecycle
    mutations remain outside this service.
    """

    def __init__(
        self,
        *,
        user: UserInDB,
        flow_repo: FlowRepository,
        flow_run_repo: FlowRunRepository,
        provider_call_repo: FlowProviderCallRepository,
        flow_run_rerun_repo: FlowRunRerunRepository,
        flow_run_review_checkpoint_repo: FlowRunReviewCheckpointRepository,
        flow_version_repo: FlowVersionRepository,
        file_repo: FileRepository,
        webhook_delivery_repo: FlowRunWebhookDeliveryRepository,
        access_policy: FlowRunAccessPolicy | None = None,
    ):
        self.user = user
        self.flow_run_repo = flow_run_repo
        self.provider_call_repo = provider_call_repo
        self.flow_run_rerun_repo = flow_run_rerun_repo
        self.flow_run_review_checkpoint_repo = flow_run_review_checkpoint_repo
        self.flow_version_repo = flow_version_repo
        self.file_repo = file_repo
        self.webhook_delivery_repo = webhook_delivery_repo
        self.access_policy = access_policy or FlowRunAccessPolicy(
            user=user,
            flow_repo=flow_repo,
            flow_run_repo=flow_run_repo,
        )

    @staticmethod
    def _raise_artifact_content_unavailable(*, run_id: UUID, file_id: UUID) -> None:
        raise ResourceGoneException(
            "Artifact content has been purged by retention policy.",
            code=FlowApiErrorCode.RUN_ARTIFACT_CONTENT_UNAVAILABLE.value,
            context={"run_id": str(run_id), "file_id": str(file_id)},
        )

    async def get_run(
        self,
        *,
        run_id: UUID,
        flow_id: UUID | None = None,
        access_kind: FlowRunAccessKind = "evidence_view",
    ) -> FlowRun:
        return await self.access_policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind=access_kind,
        )

    async def get_run_artifact_file(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        file_id: UUID,
    ) -> File:
        run = await self.access_policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind="artifact",
        )
        result_file = await self.flow_run_repo.get_result_file(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
            file_id=file_id,
        )
        if result_file is None:
            raise NotFoundException(
                f"File {file_id} is not a downloadable artifact of run {run_id}.",
                code=FlowApiErrorCode.RUN_ARTIFACT_NOT_FOUND.value,
            )
        if not result_file.content_available:
            self._raise_artifact_content_unavailable(run_id=run_id, file_id=file_id)

        file = await self.file_repo.get_by_id(file_id=file_id)
        if file.tenant_id != self.user.tenant_id:
            raise UnauthorizedException(
                "You do not have access to this artifact.",
                code="forbidden_action",
                context={"auth_layer": "domain_policy"},
            )
        if file.blob is None and file.text is None:
            self._raise_artifact_content_unavailable(run_id=run_id, file_id=file_id)
        return file

    async def get_redacted_evidence_bundle(
        self, *, run_id: UUID, run: FlowRun | None = None
    ) -> RedactedEvidenceBundle:
        return await self._get_redacted_evidence_bundle(
            run_id=run_id,
            access_kind="evidence_view",
            run=run,
        )

    async def list_provider_calls(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        limit: int,
        after_event_id: UUID | None = None,
        attempt_id: UUID | None = None,
        run: FlowRun | None = None,
    ) -> ProviderCallEvidencePage:
        resolved_run = (
            run
            if run is not None
            else await self.access_policy.load_run(
                run_id=run_id,
                flow_id=flow_id,
                access_kind="evidence_view",
            )
        )
        if run is not None:
            if resolved_run.id != run_id or resolved_run.flow_id != flow_id:
                self.access_policy.deny_run_access(auth_layer="flow_run_argument")
            await self.access_policy.ensure_can_access_run(
                resolved_run,
                access_kind="evidence_view",
            )
        try:
            return await self.provider_call_repo.list_evidence_page(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
                limit=limit,
                after_event_id=after_event_id,
                attempt_id=attempt_id,
            )
        except FlowProviderCallNotFoundError as exc:
            raise NotFoundException(
                "Provider-call evidence cursor not found.",
                code="not_found",
            ) from exc

    async def export_evidence_json(
        self,
        *,
        run_id: UUID,
        detail: str = "redacted",
        run: FlowRun | None = None,
        export_reason: str = "support_debug",
    ) -> FlowPersistedJsonObject:
        actor = evidence_export_actor_from_principal(FlowPrincipal.from_user(self.user))
        if detail == "raw":
            bundle = await self._get_evidence_bundle(
                run_id=run_id,
                access_kind="evidence_export_raw",
                run=run,
                provider_call_limit=PROVIDER_CALL_EXPORT_MAX_EVENTS + 1,
            )
            self._enforce_provider_call_export_limit(bundle.provider_calls)
            return render_evidence_json_export(
                bundle=bundle,
                context=EvidenceExportContext(
                    detail_mode="raw",
                    export_reason=export_reason,
                    actor=actor,
                ),
            )
        bundle = await self._get_redacted_evidence_bundle(
            run_id=run_id,
            access_kind="evidence_export_redacted",
            run=run,
            provider_call_limit=PROVIDER_CALL_EXPORT_MAX_EVENTS + 1,
        )
        self._enforce_provider_call_export_limit(bundle.provider_calls)
        return render_evidence_json_export(
            bundle=bundle,
            context=EvidenceExportContext(
                detail_mode="redacted",
                export_reason=export_reason,
                actor=actor,
            ),
        )

    async def _get_redacted_evidence_bundle(
        self,
        *,
        run_id: UUID,
        access_kind: FlowRunAccessKind,
        run: FlowRun | None = None,
        provider_call_limit: int = EMBEDDED_PROVIDER_CALL_LIMIT,
    ) -> RedactedEvidenceBundle:
        bundle = await self._get_evidence_bundle(
            run_id=run_id,
            access_kind=access_kind,
            run=run,
            provider_call_limit=provider_call_limit,
        )
        return redact_evidence_bundle(bundle)

    async def _get_evidence_bundle(
        self,
        *,
        run_id: UUID,
        access_kind: FlowRunAccessKind,
        run: FlowRun | None = None,
        provider_call_limit: int = EMBEDDED_PROVIDER_CALL_LIMIT,
    ) -> EvidenceBundle:
        resolved_run = (
            run
            if run is not None
            else await self.access_policy.load_run(
                run_id=run_id,
                access_kind=access_kind,
            )
        )
        if run is not None:
            if resolved_run.id != run_id:
                self.access_policy.deny_run_access(auth_layer="flow_run_argument")
            # A caller-provided run is a cache hint, not an authorization proof.
            await self.access_policy.ensure_can_access_run(
                resolved_run,
                access_kind=access_kind,
            )
        if access_kind != "evidence_view":
            await self._refuse_export_rows_before_size_measurement(
                run_id=resolved_run.id,
                detail=("raw" if access_kind == "evidence_export_raw" else "redacted"),
            )
        measurement_candidate_limit = (
            RUN_VIEW_MAX_LOADED_SECTION_ROWS + 1
            if access_kind == "evidence_view"
            else EVIDENCE_EXPORT_DEFAULT_FAN_OUT_ROW_CEILING + 1
        )
        run_measurements = await self.flow_run_repo.measure_evidence_sections(
            run_id=resolved_run.id,
            tenant_id=self.user.tenant_id,
            candidate_limit=measurement_candidate_limit,
        )
        version_measurement = await self.flow_version_repo.measure_definition_evidence(
            flow_id=resolved_run.flow_id,
            version=resolved_run.flow_version,
            tenant_id=self.user.tenant_id,
        )
        attempt_evidence_size = await self.flow_run_repo.measure_step_attempt_evidence(
            run_id=resolved_run.id,
            tenant_id=self.user.tenant_id,
            candidate_limit=measurement_candidate_limit,
        )
        rerun_measurements = await self.flow_run_rerun_repo.measure_evidence_sections(
            run_id=resolved_run.id,
            tenant_id=self.user.tenant_id,
            candidate_limit=measurement_candidate_limit,
        )
        review_measurement = (
            await self.flow_run_review_checkpoint_repo.measure_evidence(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
                candidate_limit=measurement_candidate_limit,
            )
        )
        provider_call_measurement = await self.provider_call_repo.measure_evidence(
            run_id=resolved_run.id,
            tenant_id=self.user.tenant_id,
            candidate_limit=(
                provider_call_limit + 1
                if access_kind == "evidence_view"
                else PROVIDER_CALL_EXPORT_MAX_EVENTS + 1
            ),
        )
        webhook_measurement = await self.webhook_delivery_repo.measure_evidence(
            run_id=resolved_run.id,
            tenant_id=self.user.tenant_id,
            candidate_limit=measurement_candidate_limit,
        )
        section_usages = (
            _EvidenceSectionUsage(
                section="run",
                row_count=run_measurements.run_row_count,
                stored_json_bytes=run_measurements.run_stored_json_bytes,
                logical_json_bytes=run_measurements.run_logical_json_bytes,
            ),
            _EvidenceSectionUsage(
                section="definition_snapshot",
                row_count=version_measurement.row_count,
                stored_json_bytes=version_measurement.stored_json_bytes,
                logical_json_bytes=version_measurement.logical_json_bytes,
            ),
            _EvidenceSectionUsage(
                section="step_results",
                row_count=run_measurements.step_result_row_count,
                stored_json_bytes=run_measurements.step_result_stored_json_bytes,
                logical_json_bytes=run_measurements.step_result_logical_json_bytes,
            ),
            _EvidenceSectionUsage(
                section="step_attempts",
                row_count=attempt_evidence_size.attempt_count,
                stored_json_bytes=attempt_evidence_size.stored_json_bytes,
                logical_json_bytes=attempt_evidence_size.logical_json_bytes,
            ),
            _EvidenceSectionUsage(
                section="result_files",
                row_count=run_measurements.result_file_row_count,
                stored_json_bytes=0,
                logical_json_bytes=run_measurements.result_file_logical_json_bytes,
            ),
            _EvidenceSectionUsage(
                section="runtime_input_files",
                row_count=run_measurements.runtime_input_file_row_count,
                stored_json_bytes=0,
                logical_json_bytes=(
                    run_measurements.runtime_input_file_logical_json_bytes
                ),
            ),
            _EvidenceSectionUsage(
                section="rerun_operations",
                row_count=rerun_measurements.operation_row_count,
                stored_json_bytes=rerun_measurements.operation_stored_json_bytes,
                logical_json_bytes=rerun_measurements.operation_logical_json_bytes,
            ),
            _EvidenceSectionUsage(
                section="rerun_invalidated_steps",
                row_count=rerun_measurements.invalidated_step_row_count,
                stored_json_bytes=(
                    rerun_measurements.invalidated_step_stored_json_bytes
                ),
                logical_json_bytes=(
                    rerun_measurements.invalidated_step_logical_json_bytes
                ),
            ),
            _EvidenceSectionUsage(
                section="review_checkpoints",
                row_count=review_measurement.row_count,
                stored_json_bytes=review_measurement.stored_json_bytes,
                logical_json_bytes=review_measurement.logical_json_bytes,
            ),
            _EvidenceSectionUsage(
                section="webhook_deliveries",
                row_count=webhook_measurement.row_count,
                stored_json_bytes=0,
                logical_json_bytes=0,
            ),
            _EvidenceSectionUsage(
                section="provider_calls",
                row_count=provider_call_measurement.row_count,
                stored_json_bytes=0,
                logical_json_bytes=provider_call_measurement.logical_json_bytes,
            ),
        )
        attempt_limit: int | None = None
        logical_byte_budget: int | None = None
        passage_byte_budget: int | None = None
        view_omissions: list[RunViewEvidenceOmission] = []
        if access_kind == "evidence_view":
            if (
                attempt_evidence_size.attempt_count > RUN_VIEW_MAX_LOADED_ATTEMPTS
                or attempt_evidence_size.stored_provenance_bytes
                > RUN_VIEW_MAX_LOADED_LOGICAL_BYTES
                or attempt_evidence_size.logical_json_bytes
                > RUN_VIEW_MAX_LOADED_LOGICAL_BYTES
                or attempt_evidence_size.recorded_passage_bytes
                > RUN_VIEW_MAX_LOADED_PASSAGE_BYTES
                or attempt_evidence_size.corrupt_passage_aggregates > 0
            ):
                attempt_limit = RUN_VIEW_MAX_LOADED_ATTEMPTS
                logical_byte_budget = RUN_VIEW_MAX_LOADED_LOGICAL_BYTES
                passage_byte_budget = RUN_VIEW_MAX_LOADED_PASSAGE_BYTES
        else:
            self._refuse_export_beyond_preflight(
                attempt_evidence_size,
                section_usages=section_usages,
                detail=("raw" if access_kind == "evidence_export_raw" else "redacted"),
            )
        is_view = access_kind == "evidence_view"
        view_read_kwargs = (
            {
                "limit": RUN_VIEW_MAX_LOADED_SECTION_ROWS,
                "logical_byte_budget": RUN_VIEW_MAX_LOADED_SECTION_LOGICAL_BYTES,
            }
            if is_view
            else {}
        )
        version = await self.flow_version_repo.get(
            flow_id=resolved_run.flow_id,
            version=resolved_run.flow_version,
            tenant_id=self.user.tenant_id,
        )
        step_results = await self.flow_run_repo.list_step_results(
            run_id=resolved_run.id,
            tenant_id=self.user.tenant_id,
            **view_read_kwargs,
        )
        if is_view:
            self._record_view_omission(
                omissions=view_omissions,
                usage=self._section_usage(section_usages, "step_results"),
                returned_count=len(step_results),
                row_limit=RUN_VIEW_MAX_LOADED_SECTION_ROWS,
            )
        attempt_page = await self.flow_run_repo.list_step_attempts(
            run_id=resolved_run.id,
            tenant_id=self.user.tenant_id,
            limit=attempt_limit,
            logical_byte_budget=logical_byte_budget,
            passage_byte_budget=passage_byte_budget,
        )
        step_attempts = withhold_attempt_passages(
            attempt_page.attempts,
            disclosure=await self.access_policy.passage_disclosure_for_run(
                resolved_run,
                access_kind=access_kind,
            ),
        )
        # A run's attempt count is unbounded, so an interactive view caps the
        # passage text it returns. An export must never quietly return a subset
        # of retained evidence, so it is capped by an explicit failure instead.
        knowledge_evidence_view: RunViewPassageOmission | None = None
        if access_kind == "evidence_view":
            step_attempts, knowledge_evidence_view = omit_passages_beyond_view_budget(
                step_attempts,
                step_results=step_results,
                byte_budget=(
                    self._rag_evidence_policy().max_recorded_passage_bytes_per_run_view
                ),
                count_truncated=attempt_page.count_truncated,
                # The totals and the admitted set come from one statement, so
                # these exact or lower-bound counts describe one snapshot.
                attempts_not_loaded=max(
                    0, attempt_page.total_count - len(step_attempts)
                ),
                corrupt_passage_aggregates=attempt_page.corrupt_passage_aggregates,
                current_attempts_not_loaded=max(
                    0,
                    attempt_page.current_total - attempt_page.current_admitted,
                ),
                current_step_orders_not_loaded=(
                    attempt_page.current_step_orders_not_loaded
                ),
            )
            if (
                knowledge_evidence_view.passages_omitted == 0
                and knowledge_evidence_view.attempts_not_loaded == 0
                and knowledge_evidence_view.corrupt_passage_aggregates == 0
                and knowledge_evidence_view.current_attempts_not_loaded == 0
                and not knowledge_evidence_view.count_truncated
            ):
                # The public contract says this summary is absent when the
                # view returned everything; an all-zero object would read as
                # a narrowing that never happened.
                knowledge_evidence_view = None
        else:
            self._enforce_passage_export_limit(
                step_attempts,
                detail=("raw" if access_kind == "evidence_export_raw" else "redacted"),
            )
        resolved_input_edges_by_attempt_id = (
            await self.flow_run_repo.list_resolved_input_edges_by_attempt_id(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
                attempt_ids=tuple(attempt.id for attempt in step_attempts),
            )
        )
        rerun_admission_reason: FlowRunRerunEvidenceAdmissionReason | None = None
        if is_view:
            rerun_admission = (
                await self.flow_run_rerun_repo.list_rerun_operations_for_evidence_view(
                    run_id=resolved_run.id,
                    tenant_id=self.user.tenant_id,
                    limit=RUN_VIEW_MAX_LOADED_SECTION_ROWS,
                    logical_byte_budget=RUN_VIEW_MAX_LOADED_SECTION_LOGICAL_BYTES,
                )
            )
            rerun_operations = list(rerun_admission.operations)
            rerun_admission_reason = rerun_admission.omission_reason
        else:
            rerun_operations = (
                await self.flow_run_rerun_repo.list_rerun_operations_for_run(
                    run_id=resolved_run.id,
                    tenant_id=self.user.tenant_id,
                )
            )
        if is_view:
            self._record_view_omission(
                omissions=view_omissions,
                usage=self._section_usage(section_usages, "rerun_operations"),
                returned_count=len(rerun_operations),
                row_limit=RUN_VIEW_MAX_LOADED_SECTION_ROWS,
                admission_reason=rerun_admission_reason,
            )
        admitted_operation_ids = (
            [item.id for item in rerun_operations]
            if access_kind == "evidence_view"
            else None
        )
        rerun_invalidated_steps = (
            await self.flow_run_rerun_repo.list_rerun_invalidated_steps_for_run(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
                operation_ids=admitted_operation_ids,
                **view_read_kwargs,
            )
        )
        if is_view:
            rerun_usage = self._section_usage(section_usages, "rerun_operations")
            self._record_view_omission(
                omissions=view_omissions,
                usage=self._section_usage(section_usages, "rerun_invalidated_steps"),
                returned_count=len(rerun_invalidated_steps),
                row_limit=RUN_VIEW_MAX_LOADED_SECTION_ROWS,
                parent_omitted=len(rerun_operations) < rerun_usage.row_count,
            )
        review_checkpoints = (
            await self.flow_run_review_checkpoint_repo.list_review_checkpoints_for_run(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
                **view_read_kwargs,
            )
        )
        if is_view:
            self._record_view_omission(
                omissions=view_omissions,
                usage=self._section_usage(section_usages, "review_checkpoints"),
                returned_count=len(review_checkpoints),
                row_limit=RUN_VIEW_MAX_LOADED_SECTION_ROWS,
            )
        result_files = await self.flow_run_repo.list_result_files(
            run_id=resolved_run.id,
            tenant_id=self.user.tenant_id,
            **view_read_kwargs,
        )
        if is_view:
            self._record_view_omission(
                omissions=view_omissions,
                usage=self._section_usage(section_usages, "result_files"),
                returned_count=len(result_files),
                row_limit=RUN_VIEW_MAX_LOADED_SECTION_ROWS,
            )
        if is_view:
            provider_calls = await self.provider_call_repo.list_evidence_page(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
                limit=provider_call_limit,
                total_count_limit=provider_call_limit + 1,
                logical_byte_budget=RUN_VIEW_MAX_LOADED_SECTION_LOGICAL_BYTES,
            )
        else:
            provider_calls = await self.provider_call_repo.list_evidence_page(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
                limit=provider_call_limit,
            )
        if is_view:
            self._record_view_omission(
                omissions=view_omissions,
                usage=self._section_usage(section_usages, "provider_calls"),
                returned_count=provider_calls.count,
                row_limit=provider_call_limit,
            )
        webhook_deliveries = (
            await self.webhook_delivery_repo.list_run_delivery_statuses(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
                **({"limit": RUN_VIEW_MAX_LOADED_SECTION_ROWS} if is_view else {}),
            )
        )
        if is_view:
            self._record_view_omission(
                omissions=view_omissions,
                usage=self._section_usage(section_usages, "webhook_deliveries"),
                returned_count=len(webhook_deliveries),
                row_limit=RUN_VIEW_MAX_LOADED_SECTION_ROWS,
            )
        runtime_input_file_metadata_by_step_result_id = {}
        if step_results:
            runtime_input_file_metadata_by_step_result_id = await self.flow_run_repo.list_current_step_input_file_metadata_by_step_result_id(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
                step_results=step_results,
                **view_read_kwargs,
            )
        token_usage_by_run_id = await self.provider_call_repo.list_token_usage_for_runs(
            run_ids=[resolved_run.id],
            tenant_id=self.user.tenant_id,
        )
        if is_view:
            step_result_usage = self._section_usage(section_usages, "step_results")
            self._record_view_omission(
                omissions=view_omissions,
                usage=self._section_usage(section_usages, "runtime_input_files"),
                returned_count=sum(
                    len(files)
                    for files in runtime_input_file_metadata_by_step_result_id.values()
                ),
                row_limit=RUN_VIEW_MAX_LOADED_SECTION_ROWS,
                parent_omitted=len(step_results) < step_result_usage.row_count,
            )
        return build_evidence_bundle(
            run=resolved_run,
            version=version,
            step_results=step_results,
            step_attempts=step_attempts,
            resolved_input_edges_by_attempt_id=resolved_input_edges_by_attempt_id,
            result_files=result_files,
            rerun_operations=rerun_operations,
            rerun_invalidated_steps=rerun_invalidated_steps,
            review_checkpoints=review_checkpoints,
            webhook_deliveries=webhook_deliveries,
            provider_calls=provider_calls,
            token_usage=token_usage_by_run_id.get(resolved_run.id),
            runtime_input_file_metadata_by_step_result_id=(
                runtime_input_file_metadata_by_step_result_id
            ),
            knowledge_evidence_view=knowledge_evidence_view,
            omissions=view_omissions,
        )

    def _rag_evidence_policy(self) -> FlowRagEvidencePolicy:
        tenant = getattr(self.user, "tenant", None)
        return resolve_flow_rag_evidence_policy(
            cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None))
        )

    async def _refuse_export_rows_before_size_measurement(
        self, *, run_id: UUID, detail: EvidenceExportDetail
    ) -> None:
        ceiling = EVIDENCE_EXPORT_DEFAULT_FAN_OUT_ROW_CEILING
        run_counts = await self.flow_run_repo.measure_evidence_row_counts(
            run_id=run_id,
            tenant_id=self.user.tenant_id,
            ceiling=ceiling,
        )
        rerun_counts = await self.flow_run_rerun_repo.measure_evidence_row_counts(
            run_id=run_id,
            tenant_id=self.user.tenant_id,
            ceiling=ceiling,
        )
        counts: tuple[tuple[EvidenceSectionIdentifier, int, int], ...] = (
            ("step_results", run_counts.step_results, ceiling),
            ("step_attempts", run_counts.step_attempts, ceiling),
            ("result_files", run_counts.result_files, ceiling),
            ("runtime_input_files", run_counts.runtime_input_files, ceiling),
            ("rerun_operations", rerun_counts.operations, ceiling),
            ("rerun_operations", rerun_counts.nested_overrides, ceiling),
            ("rerun_invalidated_steps", rerun_counts.invalidated_steps, ceiling),
            (
                "review_checkpoints",
                await self.flow_run_review_checkpoint_repo.measure_evidence_row_count(
                    run_id=run_id,
                    tenant_id=self.user.tenant_id,
                    ceiling=ceiling,
                ),
                ceiling,
            ),
            (
                "webhook_deliveries",
                await self.webhook_delivery_repo.measure_evidence_row_count(
                    run_id=run_id,
                    tenant_id=self.user.tenant_id,
                    ceiling=ceiling,
                ),
                ceiling,
            ),
            (
                "provider_calls",
                await self.provider_call_repo.measure_evidence_row_count(
                    run_id=run_id,
                    tenant_id=self.user.tenant_id,
                    ceiling=PROVIDER_CALL_EXPORT_MAX_EVENTS,
                ),
                PROVIDER_CALL_EXPORT_MAX_EVENTS,
            ),
        )
        for section, row_count, section_ceiling in counts:
            if row_count <= section_ceiling:
                continue
            limit_kind: EvidenceLimitIdentifier = (
                "provider_call_events"
                if section == "provider_calls"
                else "section_rows"
            )
            raise FileTooLargeException(
                "Flow evidence export contains too many rows in one section.",
                code=FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE.value,
                context={
                    "section": section,
                    "limit": limit_kind,
                    "section_row_count": row_count,
                    "max_section_rows": section_ceiling,
                    "detail": detail,
                    "hint": _EVIDENCE_EXPORT_TOO_LARGE_HINT,
                },
            )

    @staticmethod
    def _section_usage(
        section_usages: Sequence[_EvidenceSectionUsage],
        section: EvidenceSectionIdentifier,
    ) -> _EvidenceSectionUsage:
        return next(usage for usage in section_usages if usage.section == section)

    @staticmethod
    def _record_view_omission(
        *,
        omissions: list[RunViewEvidenceOmission],
        usage: _EvidenceSectionUsage,
        returned_count: int,
        row_limit: int,
        parent_omitted: bool = False,
        admission_reason: FlowRunRerunEvidenceAdmissionReason | None = None,
    ) -> None:
        rows_omitted = max(0, usage.row_count - returned_count)
        if rows_omitted == 0:
            return
        count_truncated = usage.row_count > row_limit
        if parent_omitted:
            omissions.append(
                RunViewEvidenceParentOmission(
                    section=usage.section,
                    rows_omitted=rows_omitted,
                    count_truncated=count_truncated,
                )
            )
            return
        if admission_reason == "logical_bytes":
            omissions.append(
                RunViewEvidenceLogicalByteOmission(
                    section=usage.section,
                    rows_omitted=rows_omitted,
                    count_truncated=count_truncated,
                )
            )
            return
        if admission_reason == "row_limit":
            omissions.append(
                RunViewEvidenceRowOmission(
                    section=usage.section,
                    rows_omitted=rows_omitted,
                    count_truncated=count_truncated,
                )
            )
            return
        if returned_count < min(usage.row_count, row_limit):
            omissions.append(
                RunViewEvidenceLogicalByteOmission(
                    section=usage.section,
                    rows_omitted=rows_omitted,
                    count_truncated=count_truncated,
                )
            )
            return
        omissions.append(
            RunViewEvidenceRowOmission(
                section=usage.section,
                rows_omitted=rows_omitted,
                count_truncated=count_truncated,
            )
        )

    @staticmethod
    def _refuse_export_beyond_preflight(
        attempt_evidence_size: StepAttemptEvidenceSize,
        *,
        section_usages: Sequence[_EvidenceSectionUsage],
        detail: EvidenceExportDetail,
    ) -> None:
        """Refuse an export that cannot fit before loading attempt evidence.

        Raw and redacted exports both enforce the exact retained passage total
        before load. After disclosure and redaction, the carried-text guard
        independently checks what the export will contain. Both export kinds
        also enforce the stored size of all attempt provenance because loading it
        is a cost the passage limit cannot see; stored jsonb is a compressed
        floor, so exceeding that guard understates the real cost.
        """
        if attempt_evidence_size.corrupt_passage_aggregates > 0:
            # An export is the exact record. A corrupt size aggregate means the
            # load cannot be bounded or the content proven, so the export
            # refuses rather than guessing — for either export kind.
            raise FileTooLargeException(
                "Flow evidence export cannot be produced: recorded passage "
                "evidence has unreadable size aggregates.",
                code=FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE.value,
                context={
                    "section": "step_attempts",
                    "limit": "corrupt_passage_evidence",
                    "corrupt_passage_aggregates": (
                        attempt_evidence_size.corrupt_passage_aggregates
                    ),
                    "detail": detail,
                    "hint": _EVIDENCE_EXPORT_TOO_LARGE_HINT,
                },
            )
        if (
            attempt_evidence_size.recorded_passage_bytes
            > EVIDENCE_EXPORT_MAX_PASSAGE_BYTES
        ):
            # Applies to redacted exports too: withholding happens after the
            # load, so retained passage bytes are the load cost either way.
            raise FileTooLargeException(
                "Flow evidence export contains more recorded passage text "
                "than an export document may carry.",
                code=FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE.value,
                context={
                    "section": "step_attempts",
                    "limit": "recorded_passage_bytes",
                    "recorded_passage_bytes": (
                        attempt_evidence_size.recorded_passage_bytes
                    ),
                    "max_passage_bytes": EVIDENCE_EXPORT_MAX_PASSAGE_BYTES,
                    "detail": detail,
                    "hint": _EVIDENCE_EXPORT_TOO_LARGE_HINT,
                },
            )
        if (
            attempt_evidence_size.stored_provenance_bytes
            > EVIDENCE_EXPORT_MAX_STORED_PROVENANCE_BYTES
        ):
            raise FileTooLargeException(
                "Flow evidence export would load more stored provenance than "
                "one request may materialize.",
                code=FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE.value,
                context={
                    "section": "step_attempts",
                    "limit": "stored_provenance_bytes",
                    "stored_provenance_bytes": (
                        attempt_evidence_size.stored_provenance_bytes
                    ),
                    "max_stored_provenance_bytes": (
                        EVIDENCE_EXPORT_MAX_STORED_PROVENANCE_BYTES
                    ),
                    "detail": detail,
                    "hint": _EVIDENCE_EXPORT_TOO_LARGE_HINT,
                },
            )
        aggregate_stored_json_bytes = sum(
            usage.stored_json_bytes for usage in section_usages
        )
        if (
            aggregate_stored_json_bytes
            > EVIDENCE_EXPORT_MAX_AGGREGATE_STORED_JSON_BYTES
        ):
            raise FileTooLargeException(
                "Flow evidence export would load more stored JSON than one "
                "request may materialize.",
                code=FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE.value,
                context={
                    "section": "whole_bundle",
                    "limit": "aggregate_stored_json_bytes",
                    "aggregate_stored_json_bytes": aggregate_stored_json_bytes,
                    "max_aggregate_stored_json_bytes": (
                        EVIDENCE_EXPORT_MAX_AGGREGATE_STORED_JSON_BYTES
                    ),
                    "detail": detail,
                    "hint": _EVIDENCE_EXPORT_TOO_LARGE_HINT,
                },
            )
        aggregate_logical_json_bytes = sum(
            usage.logical_json_bytes
            + usage.row_count * EVIDENCE_EXPORT_SERIALIZED_ROW_FLOOR_BYTES
            for usage in section_usages
        )
        if (
            aggregate_logical_json_bytes
            > EVIDENCE_EXPORT_MAX_AGGREGATE_LOGICAL_JSON_BYTES
        ):
            raise FileTooLargeException(
                "Flow evidence export would expand more JSON than one request "
                "may materialize.",
                code=FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE.value,
                context={
                    "section": "whole_bundle",
                    "limit": "aggregate_logical_json_bytes",
                    "aggregate_logical_json_bytes": aggregate_logical_json_bytes,
                    "max_aggregate_logical_json_bytes": (
                        EVIDENCE_EXPORT_MAX_AGGREGATE_LOGICAL_JSON_BYTES
                    ),
                    "detail": detail,
                    "hint": _EVIDENCE_EXPORT_TOO_LARGE_HINT,
                },
            )

    @staticmethod
    def _enforce_passage_export_limit(
        step_attempts: Sequence[FlowStepAttempt],
        *,
        detail: EvidenceExportDetail,
    ) -> None:
        """An export carries all retained passages, or refuses — never a subset.

        The interactive view trims its response to stay readable; an export is
        the record of what is actually retained, so silently returning less
        would misrepresent the evidence. The measure is what this export will
        actually carry: a redacted export withholds some text and is not
        charged for it. Too large is an explicit, typed failure that names the
        exceeded limit and what the caller can do instead.
        """
        carried_bytes = exported_passage_bytes(step_attempts, detail=detail)
        if carried_bytes <= EVIDENCE_EXPORT_MAX_PASSAGE_BYTES:
            return
        raise FileTooLargeException(
            "Flow evidence export contains more recorded passage text than an "
            "export document may carry.",
            code=FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE.value,
            context={
                "section": "step_attempts",
                "limit": "recorded_passage_bytes",
                "recorded_passage_bytes": carried_bytes,
                "max_passage_bytes": EVIDENCE_EXPORT_MAX_PASSAGE_BYTES,
                "detail": detail,
                "hint": _EVIDENCE_EXPORT_TOO_LARGE_HINT,
            },
        )

    @staticmethod
    def _enforce_provider_call_export_limit(
        provider_calls: ProviderCallEvidencePage,
    ) -> None:
        if provider_calls.total_count <= PROVIDER_CALL_EXPORT_MAX_EVENTS:
            return
        raise FileTooLargeException(
            "Flow evidence export contains too many provider-call events.",
            code=FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE.value,
            context={
                "section": "provider_calls",
                "limit": "provider_call_events",
                "provider_call_count": provider_calls.total_count,
                "max_provider_call_events": PROVIDER_CALL_EXPORT_MAX_EVENTS,
                "hint": (
                    "Page this run's provider-call events through the "
                    "provider-calls endpoint."
                ),
            },
        )
