"""Turn the Word templates a flow package carries into the new flow's own
template assets."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from uuid import UUID

from eneo.flows.application.flow_draft_materialization import FlowDraftChangeSet
from eneo.flows.enums import FlowOutputMode
from eneo.flows.flow_resource_bindings import LocalResourceBinding, LocalResourceKind
from eneo.flows.flow_template_asset_service import FlowTemplateAssetService
from eneo.main.exceptions import BadRequestException

if TYPE_CHECKING:
    from eneo.flows.application.flow_authoring_command import TemplateImportIntent


async def materialize_template_imports(
    *,
    intents: tuple[TemplateImportIntent, ...],
    changeset: FlowDraftChangeSet,
    flow_id: UUID,
    template_asset_service: FlowTemplateAssetService,
) -> tuple[FlowDraftChangeSet, tuple[LocalResourceBinding, ...]]:
    steps = list(changeset.compiled_steps)
    bindings: list[LocalResourceBinding] = []
    for intent in intents:
        indexes = [
            index
            for index, step in enumerate(steps)
            if (step.output_config or {}).get("template_ref") == intent.slot_ref.ref
        ]
        if not indexes or any(
            steps[index].output_mode is not FlowOutputMode.TEMPLATE_FILL
            for index in indexes
        ):
            raise BadRequestException(
                "The imported Word template has no matching template-fill step."
            )
        asset = await template_asset_service.create_asset_from_bytes(
            flow_id=flow_id, filename=intent.filename, content=intent.content
        )
        for index in indexes:
            config = dict(steps[index].output_config or {})
            raw_bindings = config.get("bindings")
            if not isinstance(raw_bindings, dict) or set(
                cast(dict[str, object], raw_bindings)
            ) != set(asset.placeholders):
                raise BadRequestException(
                    "The imported Word template fields do not match the flow mappings."
                )
            config.pop("template_ref")
            config.update(
                {
                    "template_asset_id": str(asset.id),
                    "template_name": asset.name,
                    "template_checksum": asset.checksum,
                    "placeholders": list(asset.placeholders),
                }
            )
            steps[index] = steps[index].model_copy(update={"output_config": config})
        bindings.append(
            LocalResourceBinding(
                slot_ref=intent.slot_ref,
                local_kind=LocalResourceKind.TEMPLATE_ASSET,
                local_id=asset.id,
            )
        )
    return changeset.model_copy(update={"compiled_steps": steps}), tuple(bindings)
