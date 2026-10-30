"""Create a draft flow from an authoring spec, as a flow package installs one."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel

from eneo.flows.application.flow_draft_materialization import (
    compile_flow_draft_changeset,
)
from eneo.flows.application.flow_draft_materialization_executor import (
    FlowDraftMaterializer,
    index_and_validate_changeset_resource_bindings,
)
from eneo.flows.application.flow_service import FlowService
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore
from eneo.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
    ResourceSlotRef,
)
from eneo.flows.flow_validators import validate_step_count

if TYPE_CHECKING:
    from eneo.flows.flow_template_asset_service import FlowTemplateAssetService


class FlowPackageAuthoringOrigin(BaseModel):
    kind: Literal["flow_package"] = "flow_package"
    package_id: str
    package_version: str
    content_checksum: str


class TemplateImportIntent(BaseModel):
    """Verified template bytes to create within the new Flow's transaction."""

    slot_ref: ResourceSlotRef
    filename: str
    content: bytes


class CreateFlowAuthoringCommand(BaseModel):
    kind: Literal["create"] = "create"
    space_id: UUID
    spec: FlowDraftSpecCore
    origin: FlowPackageAuthoringOrigin
    resource_bindings: tuple[LocalResourceBinding, ...] = ()
    default_transcription_model_id: UUID | None = None
    template_imports: tuple[TemplateImportIntent, ...] = ()


@dataclass(frozen=True, slots=True)
class FlowAuthoringResult:
    flow_id: UUID
    flow_name: str
    draft_revision: int
    steps_created: int


class FlowAuthoringCommandService:
    def __init__(self, materializer: FlowDraftMaterializer | None = None) -> None:
        self._materializer = materializer or FlowDraftMaterializer()

    async def apply(
        self,
        *,
        command: CreateFlowAuthoringCommand,
        flow_service: FlowService,
        template_asset_service: "FlowTemplateAssetService | None" = None,
    ) -> FlowAuthoringResult:
        changeset = compile_flow_draft_changeset(
            command.spec,
            default_transcription_model_id=command.default_transcription_model_id,
        )
        # Before anything is written: the materializer creates assistants ahead
        # of the flow, so a spec over the limit must not get that far.
        validate_step_count(len(changeset.compiled_steps))
        index_and_validate_changeset_resource_bindings(
            changeset=changeset,
            resource_bindings=command.resource_bindings,
        )
        _assert_active_transaction(flow_service)
        materialized = await self._materializer.execute(
            changeset=changeset,
            flow_service=flow_service,
            space_id=command.space_id,
            resource_bindings=command.resource_bindings,
            binding_source=FlowResourceBindingSource.PACKAGE_IMPORT,
            template_imports=command.template_imports,
            template_asset_service=template_asset_service,
        )
        return FlowAuthoringResult(
            flow_id=materialized.flow_id,
            flow_name=materialized.flow_name,
            draft_revision=materialized.draft_revision,
            steps_created=materialized.steps_created,
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


__all__ = [
    "CreateFlowAuthoringCommand",
    "FlowAuthoringCommandService",
    "FlowAuthoringResult",
    "FlowPackageAuthoringOrigin",
    "TemplateImportIntent",
]
