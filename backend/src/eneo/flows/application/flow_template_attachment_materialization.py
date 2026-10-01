from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import UUID

from eneo.flows.application.flow_draft_materialization import (
    FlowDraftChangeSet,
    FlowDraftCompiledStep,
)
from eneo.flows.enums import FlowOutputMode
from eneo.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from eneo.flows.flow_template_asset_service import FlowTemplateAssetService
from eneo.main.exceptions import BadRequestException

if TYPE_CHECKING:
    from eneo.flows.application.flow_authoring_command import (
        TemplateAttachmentIntent,
        TemplateImportIntent,
    )

_TEMPLATE_RESOURCE_SLOT = "document-template"
_MAX_DIAGNOSTIC_PLACEHOLDERS = 8
_MAX_DIAGNOSTIC_PLACEHOLDER_LENGTH = 80


@dataclass(frozen=True, slots=True)
class MaterializedTemplateAttachment:
    changeset: FlowDraftChangeSet
    binding: LocalResourceBinding


def approved_template_placeholders(
    *,
    changeset: FlowDraftChangeSet,
    plan_step_ref: str,
) -> frozenset[str]:
    """The placeholder names the plan approved for its terminal template step:
    what an attachment reads from the plan before it reads any file."""

    _, terminal_step = _terminal_template_step(
        changeset=changeset, plan_step_ref=plan_step_ref
    )
    return _approved_placeholder_names(terminal_step)


def attach_template_asset(
    *,
    changeset: FlowDraftChangeSet,
    plan_step_ref: str,
    asset_id: UUID,
) -> FlowDraftChangeSet:
    """The changeset with the asset's identity on its terminal template step:
    the one change an attachment makes to the plan's steps."""

    terminal_index, terminal_step = _terminal_template_step(
        changeset=changeset, plan_step_ref=plan_step_ref
    )
    compiled_steps = list(changeset.compiled_steps)
    compiled_steps[terminal_index] = terminal_step.model_copy(
        update={
            "output_config": {
                **(terminal_step.output_config or {}),
                "template_asset_id": str(asset_id),
            }
        }
    )
    return changeset.model_copy(update={"compiled_steps": compiled_steps})


def require_template_placeholder_contract(
    *,
    approved: frozenset[str],
    actual: frozenset[str],
) -> None:
    """The template file must hold exactly the placeholders the plan approved."""

    if actual == approved:
        return
    missing = sorted(approved - actual)
    added = sorted(actual - approved)
    raise BadRequestException(
        "The selected DOCX template no longer matches the approved Flow plan. Generate a new proposal and approve it before applying.",
        code="architecture_materialization_failed",
        context={
            "reason": "template_placeholder_contract_changed",
            "approved_count": len(approved),
            "actual_count": len(actual),
            "missing_placeholders": _bounded_names(missing),
            "added_placeholders": _bounded_names(added),
        },
    )


async def materialize_template_attachment(
    *,
    intent: TemplateAttachmentIntent,
    changeset: FlowDraftChangeSet,
    flow_id: UUID,
    template_asset_service: FlowTemplateAssetService,
) -> MaterializedTemplateAttachment:
    """Replace an approved attachment intent with one local template asset."""

    approved_placeholders = approved_template_placeholders(
        changeset=changeset, plan_step_ref=intent.terminal_plan_step_ref
    )
    asset = await template_asset_service.create_from_existing_attached_file(
        flow_id=flow_id,
        file_id=intent.file_id,
    )
    require_template_placeholder_contract(
        approved=approved_placeholders, actual=frozenset(asset.placeholders)
    )

    binding = LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind.TEMPLATE_ASSET,
            slot=_TEMPLATE_RESOURCE_SLOT,
            label=asset.name,
        ),
        local_kind=LocalResourceKind.TEMPLATE_ASSET,
        local_id=asset.id,
    )
    return MaterializedTemplateAttachment(
        changeset=attach_template_asset(
            changeset=changeset,
            plan_step_ref=intent.terminal_plan_step_ref,
            asset_id=asset.id,
        ),
        binding=binding,
    )


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


def _terminal_template_step(
    *,
    changeset: FlowDraftChangeSet,
    plan_step_ref: str,
) -> tuple[int, FlowDraftCompiledStep]:
    for index, step in enumerate(changeset.compiled_steps):
        if step.plan_step_ref != plan_step_ref:
            continue
        if (
            index != len(changeset.compiled_steps) - 1
            or step.output_mode is not FlowOutputMode.TEMPLATE_FILL
        ):
            break
        return index, step
    raise BadRequestException(
        "The template attachment intent does not target the terminal template-fill step.",
        code="architecture_materialization_failed",
        context={"reason": "template_attachment_target_invalid"},
    )


def _approved_placeholder_names(
    terminal_step: FlowDraftCompiledStep,
) -> frozenset[str]:
    output_config = terminal_step.output_config or {}
    raw_bindings = output_config.get("bindings")
    if not isinstance(raw_bindings, dict):
        raise BadRequestException(
            "The approved template-fill step is missing its placeholder binding contract. Generate a new proposal and try again.",
            code="architecture_materialization_failed",
            context={"reason": "template_binding_contract_missing"},
        )
    bindings = cast(dict[object, object], raw_bindings)
    if any(
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(expression, str)
        or not expression.strip()
        for name, expression in bindings.items()
    ):
        raise BadRequestException(
            "The approved template-fill step has an invalid placeholder binding contract. Generate a new proposal and try again.",
            code="architecture_materialization_failed",
            context={"reason": "template_binding_contract_invalid"},
        )
    return frozenset(cast(str, name) for name in bindings)


def _bounded_names(names: list[str]) -> list[str]:
    return [
        name[:_MAX_DIAGNOSTIC_PLACEHOLDER_LENGTH]
        for name in names[:_MAX_DIAGNOSTIC_PLACEHOLDERS]
    ]
