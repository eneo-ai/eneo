from __future__ import annotations

import asyncio
from uuid import UUID

from intric.files.file_models import File
from intric.files.file_repo import FileRepository
from intric.flows.application.flow_run_access_policy import (
    FlowRunAccessKind,
    FlowRunAccessPolicy,
)
from intric.flows.domain.flow import FlowRun, JsonObject
from intric.flows.flow_run_evidence_bundle import (
    EvidenceBundle,
    RedactedEvidenceBundle,
    build_evidence_bundle,
    redact_evidence_bundle,
)
from intric.flows.flow_run_evidence_export_manifest import EvidenceExportContext
from intric.flows.flow_run_export_json import render_evidence_json_export
from intric.flows.infrastructure.flow_repo import FlowRepository
from intric.flows.infrastructure.flow_run_repo import FlowRunRepository
from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository
from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
    ResourceGoneException,
    UnauthorizedException,
)
from intric.users.user import UserInDB


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
        flow_version_repo: FlowVersionRepository,
        file_repo: FileRepository | None = None,
        access_policy: FlowRunAccessPolicy | None = None,
    ):
        self.user = user
        self.flow_run_repo = flow_run_repo
        self.flow_version_repo = flow_version_repo
        self.file_repo = file_repo
        self.access_policy = access_policy or FlowRunAccessPolicy(
            user=user,
            flow_repo=flow_repo,
            flow_run_repo=flow_run_repo,
        )

    @staticmethod
    def _raise_artifact_content_unavailable(*, run_id: UUID, file_id: UUID) -> None:
        raise ResourceGoneException(
            "Artifact content has been purged by retention policy.",
            code="flow_run_artifact_content_unavailable",
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
        if self.file_repo is None:
            raise BadRequestException(
                "Artifact download is not available in this context.",
                code="file_repo_unavailable",
            )

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
                code="flow_run_artifact_not_found",
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

    async def export_evidence_json(
        self,
        *,
        run_id: UUID,
        detail: str = "redacted",
        run: FlowRun | None = None,
        export_reason: str = "support_debug",
    ) -> JsonObject:
        if detail == "raw":
            bundle = await self._get_evidence_bundle(
                run_id=run_id,
                access_kind="evidence_export_raw",
                run=run,
            )
            return render_evidence_json_export(
                bundle=bundle,
                context=EvidenceExportContext(
                    detail_mode="raw",
                    export_reason=export_reason,
                    exported_by_user_id=str(self.user.id),
                ),
            )
        bundle = await self._get_redacted_evidence_bundle(
            run_id=run_id,
            access_kind="evidence_export_redacted",
            run=run,
        )
        return render_evidence_json_export(
            bundle=bundle,
            context=EvidenceExportContext(
                detail_mode="redacted",
                export_reason=export_reason,
                exported_by_user_id=str(self.user.id),
            ),
        )

    async def _get_redacted_evidence_bundle(
        self,
        *,
        run_id: UUID,
        access_kind: FlowRunAccessKind,
        run: FlowRun | None = None,
    ) -> RedactedEvidenceBundle:
        bundle = await self._get_evidence_bundle(
            run_id=run_id,
            access_kind=access_kind,
            run=run,
        )
        return redact_evidence_bundle(bundle)

    async def _get_evidence_bundle(
        self,
        *,
        run_id: UUID,
        access_kind: FlowRunAccessKind,
        run: FlowRun | None = None,
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
        (
            step_results,
            step_attempts,
            rerun_operations,
            rerun_invalidated_steps,
            review_checkpoints,
            result_files,
        ) = await asyncio.gather(
            self.flow_run_repo.list_step_results(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
            ),
            self.flow_run_repo.list_step_attempts(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
            ),
            self.flow_run_repo.list_rerun_operations_for_run(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
            ),
            self.flow_run_repo.list_rerun_invalidated_steps_for_run(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
            ),
            self.flow_run_repo.list_review_checkpoints_for_run(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
            ),
            self.flow_run_repo.list_result_files(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
            ),
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
        )
