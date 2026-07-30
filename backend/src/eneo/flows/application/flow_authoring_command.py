from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, Field

from eneo.flows.application.flow_authoring_origin_policy import (
    FlowAuthoringOriginPolicy,
    NoopFlowAuthoringOriginPolicy,
)
from eneo.flows.application.flow_draft_materialization import (
    FlowDraftChangeSet,
    FlowDraftMaterializationProgress,
    FlowDraftStepChangeKind,
    compile_flow_draft_changeset,
)
from eneo.flows.application.flow_draft_materialization_executor import (
    FlowDraftMaterializer,
    index_and_validate_changeset_resource_bindings,
)
from eneo.flows.application.flow_service import FlowService
from eneo.flows.domain.flow import Flow
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
)
from eneo.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
)
from eneo.main.exceptions import BadRequestException

if TYPE_CHECKING:
    from eneo.flows.flow_template_asset_service import FlowTemplateAssetService


class AIBuilderFlowAuthoringOrigin(BaseModel):
    kind: Literal["ai_builder"] = "ai_builder"
    session_id: UUID
    plan_id: UUID
    spec_hash: str
    applied_at: datetime
    description_override_manual: bool = False


class FlowPackageAuthoringOrigin(BaseModel):
    kind: Literal["flow_package"] = "flow_package"
    package_id: str
    package_version: str
    content_checksum: str


FlowAuthoringOrigin: TypeAlias = Annotated[
    AIBuilderFlowAuthoringOrigin | FlowPackageAuthoringOrigin,
    Field(discriminator="kind"),
]


class TemplateAttachmentIntent(BaseModel):
    """Internal intent resolved into a Flow-owned asset during materialization."""

    file_id: UUID
    terminal_plan_step_ref: str


class CreateFlowAuthoringCommand(BaseModel):
    kind: Literal["create"] = "create"
    space_id: UUID
    spec: FlowDraftSpecCore
    origin: FlowAuthoringOrigin
    resource_bindings: tuple[LocalResourceBinding, ...] = ()
    default_transcription_model_id: UUID | None = None
    template_attachment_intent: TemplateAttachmentIntent | None = None


class EditFlowAuthoringCommand(BaseModel):
    kind: Literal["edit"] = "edit"
    space_id: UUID
    flow_id: UUID
    expected_revision: int
    spec: FlowDraftSpecCore
    removed_existing_step_refs: frozenset[str]
    origin: FlowAuthoringOrigin
    resource_bindings: tuple[LocalResourceBinding, ...] = ()
    default_transcription_model_id: UUID | None = None
    template_attachment_intent: TemplateAttachmentIntent | None = None


FlowAuthoringCommand: TypeAlias = Annotated[
    CreateFlowAuthoringCommand | EditFlowAuthoringCommand,
    Field(discriminator="kind"),
]


@dataclass(frozen=True, slots=True)
class FlowAuthoringStepPreview:
    ref: str
    change_kind: FlowDraftStepChangeKind


@dataclass(frozen=True, slots=True)
class FlowAuthoringPreview:
    kind: Literal["create", "edit"]
    flow_id: UUID | None
    base_revision: int | None
    spec_hash: str
    steps_created: int
    steps_updated: int
    steps_removed: int
    assistants_to_create: int
    assistants_to_update: int
    assistants_to_delete: int
    resource_bindings_count: int
    step_changes: tuple[FlowAuthoringStepPreview, ...]


@dataclass(frozen=True, slots=True)
class PreparedFlowAuthoring:
    command: FlowAuthoringCommand
    spec: FlowDraftSpecCore
    current_flow: Flow | None
    changeset: FlowDraftChangeSet
    preview: FlowAuthoringPreview


@dataclass(frozen=True, slots=True)
class FlowAuthoringResult:
    flow_id: UUID
    flow_name: str
    draft_revision: int
    steps_created: int
    steps_updated: int
    steps_removed: int
    command_spec_hash: str


class FlowAuthoringCommandService:
    def __init__(self, materializer: FlowDraftMaterializer | None = None) -> None:
        self._materializer = materializer or FlowDraftMaterializer()

    async def prepare(
        self,
        *,
        command: FlowAuthoringCommand,
        flow_service: FlowService,
        origin_policy: FlowAuthoringOriginPolicy | None = None,
    ) -> PreparedFlowAuthoring:
        current_flow = await _load_current_flow(
            command=command,
            flow_service=flow_service,
        )
        policy = origin_policy or NoopFlowAuthoringOriginPolicy()
        spec = policy.effective_spec(
            spec=command.spec,
            current_flow=current_flow,
        )
        changeset = compile_flow_draft_changeset(
            spec,
            current_flow,
            removed_existing_step_refs=_removed_existing_step_refs(command),
            default_transcription_model_id=command.default_transcription_model_id,
        )
        changeset = policy.stamp_metadata(
            changeset=changeset,
        )
        index_and_validate_changeset_resource_bindings(
            changeset=changeset,
            resource_bindings=command.resource_bindings,
        )
        return PreparedFlowAuthoring(
            command=command,
            spec=spec,
            current_flow=current_flow,
            changeset=changeset,
            preview=_build_preview(
                command=command,
                spec=spec,
                current_flow=current_flow,
                changeset=changeset,
            ),
        )

    async def apply(
        self,
        *,
        command: FlowAuthoringCommand,
        flow_service: FlowService,
        origin_policy: FlowAuthoringOriginPolicy | None = None,
        template_asset_service: "FlowTemplateAssetService | None" = None,
        progress_callback: Callable[[FlowDraftMaterializationProgress], None]
        | None = None,
    ) -> FlowAuthoringResult:
        prepared = await self.prepare(
            command=command,
            flow_service=flow_service,
            origin_policy=origin_policy,
        )
        return await self.apply_prepared(
            prepared=prepared,
            flow_service=flow_service,
            template_asset_service=template_asset_service,
            progress_callback=progress_callback,
        )

    async def apply_prepared(
        self,
        *,
        prepared: PreparedFlowAuthoring,
        flow_service: FlowService,
        template_asset_service: "FlowTemplateAssetService | None" = None,
        progress_callback: Callable[[FlowDraftMaterializationProgress], None]
        | None = None,
    ) -> FlowAuthoringResult:
        _assert_active_transaction(flow_service)
        materialized = await self._materializer.execute(
            changeset=prepared.changeset,
            flow_service=flow_service,
            space_id=prepared.command.space_id,
            flow_id=_target_flow_id(prepared.command),
            expected_revision=_expected_revision(prepared.command),
            resource_bindings=prepared.command.resource_bindings,
            binding_source=_binding_source_for_origin(prepared.command.origin),
            template_attachment_intent=(prepared.command.template_attachment_intent),
            template_asset_service=template_asset_service,
            progress_callback=progress_callback,
        )
        return FlowAuthoringResult(
            flow_id=materialized.flow_id,
            flow_name=materialized.flow_name,
            draft_revision=materialized.draft_revision,
            steps_created=materialized.steps_created,
            steps_updated=materialized.steps_updated,
            steps_removed=materialized.steps_removed,
            command_spec_hash=prepared.spec.spec_hash(),
        )


async def _load_current_flow(
    *,
    command: FlowAuthoringCommand,
    flow_service: FlowService,
) -> Flow | None:
    if command.kind == "create":
        return None

    current_flow = await flow_service.get_flow(command.flow_id)
    if current_flow.space_id != command.space_id:
        raise BadRequestException(
            "Flow space does not match the authoring command space.",
            code="flow_space_mismatch",
            context={
                "flow_id": str(command.flow_id),
                "flow_space_id": str(current_flow.space_id),
                "command_space_id": str(command.space_id),
            },
        )
    if current_flow.published_version is not None:
        raise BadRequestException(
            "Flow is currently published. Unpublish the flow before applying changes.",
            code="flow_is_published",
            context={
                "flow_id": str(current_flow.id),
                "published_version": current_flow.published_version,
            },
        )
    if current_flow.draft_revision != command.expected_revision:
        raise BadRequestException(
            "Flödet ändrades av en annan användare. "
            "Dina ändringar beräknas mot den nya versionen.",
            code="stale_revision",
            context={
                "flow_id": str(command.flow_id),
                "expected_revision": command.expected_revision,
                "actual_revision": current_flow.draft_revision,
            },
        )
    return current_flow


def _build_preview(
    *,
    command: FlowAuthoringCommand,
    spec: FlowDraftSpecCore,
    current_flow: Flow | None,
    changeset: FlowDraftChangeSet,
) -> FlowAuthoringPreview:
    return FlowAuthoringPreview(
        kind=command.kind,
        flow_id=_target_flow_id(command),
        base_revision=None if current_flow is None else current_flow.draft_revision,
        spec_hash=spec.spec_hash(),
        steps_created=sum(
            1
            for step in changeset.compiled_steps
            if step.change_kind == FlowDraftStepChangeKind.ADDED
        ),
        steps_updated=sum(
            1
            for step in changeset.compiled_steps
            if step.change_kind == FlowDraftStepChangeKind.MODIFIED
        ),
        steps_removed=len(changeset.assistants_to_delete),
        assistants_to_create=len(changeset.assistants_to_create),
        assistants_to_update=len(changeset.assistants_to_update),
        assistants_to_delete=len(changeset.assistants_to_delete),
        resource_bindings_count=len(command.resource_bindings),
        step_changes=tuple(
            FlowAuthoringStepPreview(
                ref=step.existing_step_ref or step.plan_step_ref,
                change_kind=step.change_kind,
            )
            for step in changeset.compiled_steps
        ),
    )


def _assert_active_transaction(flow_service: FlowService) -> None:
    try:
        transaction_is_active = flow_service.flow_repo.session.in_transaction()
    except AttributeError as exc:
        raise RuntimeError(
            "Flow authoring apply requires an inspectable transaction owner."
        ) from exc

    if transaction_is_active:
        return
    raise RuntimeError("Flow authoring apply requires an active transaction.")


def _removed_existing_step_refs(command: FlowAuthoringCommand) -> frozenset[str]:
    if command.kind == "create":
        return frozenset()
    return command.removed_existing_step_refs


def _target_flow_id(command: FlowAuthoringCommand) -> UUID | None:
    if command.kind == "create":
        return None
    return command.flow_id


def _expected_revision(command: FlowAuthoringCommand) -> int | None:
    if command.kind == "create":
        return None
    return command.expected_revision


def _binding_source_for_origin(
    origin: FlowAuthoringOrigin,
) -> FlowResourceBindingSource:
    if origin.kind == "ai_builder":
        return FlowResourceBindingSource.AI_BUILDER
    return FlowResourceBindingSource.PACKAGE_IMPORT


__all__ = [
    "AIBuilderFlowAuthoringOrigin",
    "CreateFlowAuthoringCommand",
    "EditFlowAuthoringCommand",
    "FlowAuthoringCommand",
    "FlowAuthoringCommandService",
    "FlowAuthoringOrigin",
    "FlowAuthoringPreview",
    "FlowAuthoringResult",
    "FlowAuthoringStepPreview",
    "FlowPackageAuthoringOrigin",
    "PreparedFlowAuthoring",
]
