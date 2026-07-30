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
    from eneo.flows.application.flow_authoring_command import TemplateAttachmentIntent

_TEMPLATE_RESOURCE_SLOT = "document-template"
_MAX_DIAGNOSTIC_PLACEHOLDERS = 8
_MAX_DIAGNOSTIC_PLACEHOLDER_LENGTH = 80


@dataclass(frozen=True, slots=True)
class MaterializedTemplateAttachment:
    changeset: FlowDraftChangeSet
    binding: LocalResourceBinding


async def materialize_template_attachment(
    *,
    intent: TemplateAttachmentIntent,
    changeset: FlowDraftChangeSet,
    flow_id: UUID,
    template_asset_service: FlowTemplateAssetService,
) -> MaterializedTemplateAttachment:
    """Replace an approved attachment intent with one local template asset."""

    terminal_index, terminal_step = _terminal_template_step(
        changeset=changeset,
        plan_step_ref=intent.terminal_plan_step_ref,
    )
    approved_placeholders = _approved_placeholder_names(terminal_step)
    asset = await template_asset_service.create_from_existing_attached_file(
        flow_id=flow_id,
        file_id=intent.file_id,
    )
    actual_placeholders = frozenset(asset.placeholders)
    if actual_placeholders != approved_placeholders:
        missing = sorted(approved_placeholders - actual_placeholders)
        added = sorted(actual_placeholders - approved_placeholders)
        raise BadRequestException(
            "The selected DOCX template no longer matches the approved Flow plan. Generate a new proposal and approve it before applying.",
            code="architecture_materialization_failed",
            context={
                "reason": "template_placeholder_contract_changed",
                "approved_count": len(approved_placeholders),
                "actual_count": len(actual_placeholders),
                "missing_placeholders": _bounded_names(missing),
                "added_placeholders": _bounded_names(added),
            },
        )

    compiled_steps = list(changeset.compiled_steps)
    compiled_steps[terminal_index] = terminal_step.model_copy(
        update={
            "output_config": {
                **(terminal_step.output_config or {}),
                "template_asset_id": str(asset.id),
            }
        }
    )
    resolved_changeset = changeset.model_copy(update={"compiled_steps": compiled_steps})
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
        changeset=resolved_changeset,
        binding=binding,
    )


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
