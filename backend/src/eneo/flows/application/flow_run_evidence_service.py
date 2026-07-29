from __future__ import annotations

import asyncio
from collections.abc import Sequence
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
    StepAttemptProvenanceSize,
)
from eneo.flows.infrastructure.flow_run_rerun_repo import FlowRunRerunRepository
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
# An interactive view bounds what it loads by rows, stored bytes, AND exact
# recorded passage bytes: stored jsonb is a compressed floor, so highly
# compressible passage text could pass a stored-byte guard and still expand
# far beyond it in memory. Current attempts are admitted first and consume
# the budgets first; when even a current attempt does not fit, the response
# says so rather than pretending it never existed. Memory-protection
# invariants for one request, not operator policy.
RUN_VIEW_MAX_LOADED_ATTEMPTS = 500
RUN_VIEW_MAX_LOADED_STORED_BYTES = 32 * 1024 * 1024
RUN_VIEW_MAX_LOADED_PASSAGE_BYTES = 64 * 1024 * 1024
# Recovery guidance travels in the error context because clients read the
# typed response body; a server-side hint field they never receive is not
# remediation.
_EVIDENCE_EXPORT_TOO_LARGE_HINT = (
    "Inspect this run's knowledge evidence in the run view, which pages "
    "it, or lower the retained-passage policy for future runs. An export "
    "never returns a partial document."
)


class FlowRunEvidenceService:
    """Owns Flow run evidence assembly, export, and artifact file access.

    Step-result inspection, token usage, and lifecycle mutations remain outside this service.
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
        version = await self.flow_version_repo.get(
            flow_id=resolved_run.flow_id,
            version=resolved_run.flow_version,
            tenant_id=self.user.tenant_id,
        )
        # Size the stored attempt provenance before loading any of it. An
        # export that cannot possibly fit refuses here, before the expensive
        # fetch; an oversized interactive view narrows what it loads instead.
        provenance_size = await self.flow_run_repo.measure_step_attempt_provenance(
            run_id=resolved_run.id,
            tenant_id=self.user.tenant_id,
        )
        attempt_limit: int | None = None
        history_byte_budget: int | None = None
        passage_byte_budget: int | None = None
        if access_kind == "evidence_view":
            if (
                provenance_size.attempt_count > RUN_VIEW_MAX_LOADED_ATTEMPTS
                or provenance_size.stored_provenance_bytes
                > RUN_VIEW_MAX_LOADED_STORED_BYTES
                or provenance_size.recorded_passage_bytes
                > RUN_VIEW_MAX_LOADED_PASSAGE_BYTES
                or provenance_size.corrupt_passage_aggregates > 0
            ):
                attempt_limit = RUN_VIEW_MAX_LOADED_ATTEMPTS
                history_byte_budget = RUN_VIEW_MAX_LOADED_STORED_BYTES
                passage_byte_budget = RUN_VIEW_MAX_LOADED_PASSAGE_BYTES
        else:
            self._refuse_export_beyond_preflight(
                provenance_size,
                detail=("raw" if access_kind == "evidence_export_raw" else "redacted"),
            )
        async with asyncio.TaskGroup() as task_group:
            step_results_task = task_group.create_task(
                self.flow_run_repo.list_step_results(
                    run_id=resolved_run.id,
                    tenant_id=self.user.tenant_id,
                )
            )
            step_attempts_task = task_group.create_task(
                self.flow_run_repo.list_step_attempts(
                    run_id=resolved_run.id,
                    tenant_id=self.user.tenant_id,
                    limit=attempt_limit,
                    history_byte_budget=history_byte_budget,
                    passage_byte_budget=passage_byte_budget,
                )
            )
            rerun_operations_task = task_group.create_task(
                self.flow_run_rerun_repo.list_rerun_operations_for_run(
                    run_id=resolved_run.id,
                    tenant_id=self.user.tenant_id,
                )
            )
            rerun_invalidated_steps_task = task_group.create_task(
                self.flow_run_rerun_repo.list_rerun_invalidated_steps_for_run(
                    run_id=resolved_run.id,
                    tenant_id=self.user.tenant_id,
                )
            )
            review_checkpoints_task = task_group.create_task(
                self.flow_run_review_checkpoint_repo.list_review_checkpoints_for_run(
                    run_id=resolved_run.id,
                    tenant_id=self.user.tenant_id,
                )
            )
            result_files_task = task_group.create_task(
                self.flow_run_repo.list_result_files(
                    run_id=resolved_run.id,
                    tenant_id=self.user.tenant_id,
                )
            )
            provider_calls_task = task_group.create_task(
                self.provider_call_repo.list_evidence_page(
                    run_id=resolved_run.id,
                    tenant_id=self.user.tenant_id,
                    limit=provider_call_limit,
                )
            )
        step_results = step_results_task.result()
        attempt_page = step_attempts_task.result()
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
                # The totals and the admitted set come from one statement, so
                # these counts describe one snapshot and are always true.
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
        rerun_operations = rerun_operations_task.result()
        rerun_invalidated_steps = rerun_invalidated_steps_task.result()
        review_checkpoints = review_checkpoints_task.result()
        result_files = result_files_task.result()
        provider_calls = provider_calls_task.result()
        webhook_deliveries = (
            await self.webhook_delivery_repo.list_run_delivery_statuses(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
            )
        )
        runtime_input_file_metadata_by_step_result_id = {}
        if step_results:
            runtime_input_file_metadata_by_step_result_id = await self.flow_run_repo.list_current_step_input_file_metadata_by_step_result_id(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
                step_results=step_results,
            )
        return build_evidence_bundle(
            run=resolved_run,
            version=version,
            step_results=step_results,
            step_attempts=step_attempts,
            result_files=result_files,
            rerun_operations=rerun_operations,
            rerun_invalidated_steps=rerun_invalidated_steps,
            review_checkpoints=review_checkpoints,
            webhook_deliveries=webhook_deliveries,
            provider_calls=provider_calls,
            runtime_input_file_metadata_by_step_result_id=(
                runtime_input_file_metadata_by_step_result_id
            ),
            knowledge_evidence_view=knowledge_evidence_view,
        )

    def _rag_evidence_policy(self) -> FlowRagEvidencePolicy:
        tenant = getattr(self.user, "tenant", None)
        return resolve_flow_rag_evidence_policy(
            cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None))
        )

    @staticmethod
    def _refuse_export_beyond_preflight(
        provenance_size: StepAttemptProvenanceSize,
        *,
        detail: EvidenceExportDetail,
    ) -> None:
        """Refuse an export that cannot fit, before loading any provenance.

        Two independent guards, each reported as what it actually measured. A
        raw export refuses on the exact recorded passage total, which every
        RAG payload stores about itself — a redacted export withholds text and
        is judged only after load, by what it will actually carry. Both kinds
        refuse on the stored size of all provenance, because loading it is a
        cost the passage limit cannot see; stored jsonb is a compressed floor,
        so exceeding that guard understates the real cost, never overstates it.
        """
        if provenance_size.corrupt_passage_aggregates > 0:
            # An export is the exact record. A corrupt size aggregate means the
            # load cannot be bounded or the content proven, so the export
            # refuses rather than guessing — for either export kind.
            raise FileTooLargeException(
                "Flow evidence export cannot be produced: recorded passage "
                "evidence has unreadable size aggregates.",
                code=FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE.value,
                context={
                    "limit": "corrupt_passage_evidence",
                    "corrupt_passage_aggregates": (
                        provenance_size.corrupt_passage_aggregates
                    ),
                    "detail": detail,
                    "hint": _EVIDENCE_EXPORT_TOO_LARGE_HINT,
                },
            )
        if provenance_size.recorded_passage_bytes > EVIDENCE_EXPORT_MAX_PASSAGE_BYTES:
            # Applies to redacted exports too: withholding happens after the
            # load, so retained passage bytes are the load cost either way.
            raise FileTooLargeException(
                "Flow evidence export contains more recorded passage text "
                "than an export document may carry.",
                code=FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE.value,
                context={
                    "limit": "recorded_passage_bytes",
                    "recorded_passage_bytes": (provenance_size.recorded_passage_bytes),
                    "max_passage_bytes": EVIDENCE_EXPORT_MAX_PASSAGE_BYTES,
                    "detail": detail,
                    "hint": _EVIDENCE_EXPORT_TOO_LARGE_HINT,
                },
            )
        if (
            provenance_size.stored_provenance_bytes
            > EVIDENCE_EXPORT_MAX_STORED_PROVENANCE_BYTES
        ):
            raise FileTooLargeException(
                "Flow evidence export would load more stored provenance than "
                "one request may materialize.",
                code=FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE.value,
                context={
                    "limit": "stored_provenance_bytes",
                    "stored_provenance_bytes": (
                        provenance_size.stored_provenance_bytes
                    ),
                    "max_stored_provenance_bytes": (
                        EVIDENCE_EXPORT_MAX_STORED_PROVENANCE_BYTES
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
                "limit": "provider_call_events",
                "provider_call_count": provider_calls.total_count,
                "max_provider_call_events": PROVIDER_CALL_EXPORT_MAX_EVENTS,
                "hint": (
                    "Page this run's provider-call events through the "
                    "provider-calls endpoint."
                ),
            },
        )
