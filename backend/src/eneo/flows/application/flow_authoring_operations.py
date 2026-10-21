"""Shared authorized authoring operations for REST and loopback MCP.

The existing core access policies, service validation, snapshots and audit remain
one path. Callers own a transaction; exceptions must reach its context manager.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import UUID

from fastapi import Request

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.access_denial_code import AccessDenialCode
from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_definition_access import (
    require_flow_current_definition_access,
    require_flow_edit_access,
    require_flow_publish_access,
    require_flow_unpublish_access,
)
from eneo.flows.api.flow_models import (
    FlowCreateRequest,
    FlowEditorStepPatch,
    FlowEditorUpdateRequest,
    FlowPublic,
    FlowStepCreateRequest,
    FlowUpdateRequest,
)
from eneo.flows.application.flow_step_structure import (
    PlacedStep,
    restructure_steps,
)
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import (
    FlowUnauthorizedException,
)
from eneo.flows.flow_authoring_name import FlowNameTakenError
from eneo.flows.flow_evidence_policy import flow_evidence_metadata_facts
from eneo.flows.infrastructure.flow_repo import DraftRevisionReservation
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    ConflictException,
    NotFoundException,
)
from eneo.main.models import NOT_PROVIDED
from eneo.prompts.api.prompt_models import PromptCreate

_FLOW_NAME_TAKEN_MESSAGE = "A flow with this name already exists in this space."


def _flow_name_taken_conflict() -> ConflictException:
    return ConflictException(
        _FLOW_NAME_TAKEN_MESSAGE, code=FlowApiErrorCode.FLOW_NAME_TAKEN.value
    )


def _classification_override_step_orders(
    flow_data: FlowCreateRequest | FlowUpdateRequest,
) -> list[int]:
    steps = flow_data.steps
    if not steps:
        return []
    return [
        step.step_order
        for step in steps
        if step.output_classification_override is not None
    ]


def _evidence_export_change(
    *,
    before: Mapping[str, object] | None,
    after: Mapping[str, object] | None,
) -> dict[str, object] | None:
    """Whether a flow's evidence may be exported is an access decision, so the
    audit entry says what the switch was and what it became."""

    old = flow_evidence_metadata_facts(before).export_allowed
    new = flow_evidence_metadata_facts(after).export_allowed
    if old == new:
        return None
    return {"evidence_export_allowed": {"old": old, "new": new}}


async def create_flow(
    request: Request, flow_in: FlowCreateRequest, container: Container
) -> FlowPublic:
    access_context = await flow_access_context.resolve_space_access_context(
        request,
        container,
        space_id=flow_in.space_id,
        required_access=FlowApiAction.EDIT,
        scope_mismatch_message=(
            f"API key is scoped to space '{flow_access_context.get_scope_filter(request).space_id}'. "
            f"Cannot create flow in space '{flow_in.space_id}'."
        ),
    )
    if not access_context.actor.can_create_flows():
        raise FlowUnauthorizedException(
            "You do not have permission to create flows in this space.",
            code=AccessDenialCode.INSUFFICIENT_SPACE_PERMISSION,
            context={"auth_layer": "space_membership"},
        )

    assembler = FlowAssembler()
    flow_service = container.flow_service()
    user = container.user()

    try:
        created = await flow_service.create_flow(
            space_id=flow_in.space_id,
            name=flow_in.name,
            description=flow_in.description,
            steps=[assembler.to_domain_step(step) for step in flow_in.steps],
            metadata_json=flow_in.metadata_json,
        )
    except FlowNameTakenError as exc:
        raise _flow_name_taken_conflict() from exc

    created_flow_id = created.require_persisted_id()
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_CREATED,
        entity_type=EntityType.FLOW,
        entity_id=created_flow_id,
        description=f"Created flow '{created.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=created,
            changes=_evidence_export_change(before=None, after=created.metadata_json),
        ),
    )
    overrides = _classification_override_step_orders(flow_in)
    if overrides:
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.FLOW_CLASSIFICATION_OVERRIDE,
            entity_type=EntityType.FLOW,
            entity_id=created_flow_id,
            description="Configured output classification overrides for flow steps.",
            metadata=AuditMetadata.standard(
                actor=user,
                target=created,
                changes={"step_orders": overrides},
            ),
        )

    return assembler.to_public(created)


async def get_flow(id: UUID, request: Request, container: Container) -> FlowPublic:
    access_context = await require_flow_current_definition_access(
        request,
        container,
        flow_id=id,
    )
    assembler = FlowAssembler()

    return assembler.to_public(access_context.flow)


async def update_flow(
    id: UUID,
    request: Request,
    flow_in: FlowUpdateRequest,
    container: Container,
    *,
    unchanged_step_ids: frozenset[UUID] = frozenset(),
    steps_override: list[FlowStep] | None = None,
) -> FlowPublic:
    access_context = await require_flow_edit_access(request, container, flow_id=id)

    assembler = FlowAssembler()
    payload = flow_in.model_dump(exclude_unset=True)
    steps = None
    if "steps" in payload:
        steps = [assembler.to_domain_step_for_update(step) for step in flow_in.steps]

    if steps_override is not None:
        steps = steps_override
    if unchanged_step_ids and steps is None:
        steps = access_context.flow.steps

    # Without the editor's own revision the write is fenced on the one this
    # request was authorized at, which is also the state the audit entry below
    # compares against.
    expected_revision = (
        access_context.flow.draft_revision
        if flow_in.expected_revision is None
        else flow_in.expected_revision
    )
    try:
        updated = await container.flow_service().update_flow(
            flow_id=id,
            name=payload.get("name", NOT_PROVIDED),
            description=payload.get("description", NOT_PROVIDED),
            steps=steps,
            metadata_json=payload.get("metadata_json", NOT_PROVIDED),
            expected_revision=expected_revision,
            unchanged_step_ids=unchanged_step_ids,
        )
    except FlowNameTakenError as exc:
        raise _flow_name_taken_conflict() from exc

    updated_flow_id = updated.require_persisted_id()
    user = container.user()
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_UPDATED,
        entity_type=EntityType.FLOW,
        entity_id=updated_flow_id,
        description=f"Updated flow '{updated.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=updated,
            changes=_evidence_export_change(
                before=access_context.flow.metadata_json,
                after=updated.metadata_json,
            ),
        ),
    )
    overrides = _classification_override_step_orders(flow_in)
    if overrides:
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.FLOW_CLASSIFICATION_OVERRIDE,
            entity_type=EntityType.FLOW,
            entity_id=updated_flow_id,
            description="Updated output classification overrides for flow steps.",
            metadata=AuditMetadata.standard(
                actor=user,
                target=updated,
                changes={"step_orders": overrides},
            ),
        )

    return assembler.to_public(updated)


async def publish_flow(
    id: UUID,
    request: Request,
    container: Container,
    *,
    expected_revision: int | None = None,
) -> FlowPublic:
    await require_flow_publish_access(request, container, flow_id=id)
    if expected_revision is not None:
        await container.flow_service().reserve_draft_revision(
            flow_id=id, expected_revision=expected_revision
        )

    published = await container.flow_service().publish_flow(flow_id=id)
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_PUBLISHED,
        entity_type=EntityType.FLOW,
        entity_id=id,
        description=f"Published flow '{published.name}' as version {published.published_version}",
        metadata=AuditMetadata.standard(actor=user, target=published),
    )
    return FlowAssembler().to_public(published)


async def unpublish_flow(
    id: UUID,
    request: Request,
    container: Container,
    *,
    expected_revision: int | None = None,
) -> FlowPublic:
    await require_flow_unpublish_access(request, container, flow_id=id)
    if expected_revision is not None:
        await container.flow_service().reserve_draft_revision(
            flow_id=id, expected_revision=expected_revision
        )

    unpublished = await container.flow_service().unpublish_flow(flow_id=id)
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_UNPUBLISHED,
        entity_type=EntityType.FLOW,
        entity_id=id,
        description=f"Unpublished flow '{unpublished.name}'",
        metadata=AuditMetadata.standard(actor=user, target=unpublished),
    )
    return FlowAssembler().to_public(unpublished)


async def apply_editor_update(
    id: UUID, request: Request, update: "FlowEditorUpdateRequest", container: Container
) -> FlowPublic:
    """Reserve the core revision before any child write; one commit and audit.

    Exceptions must escape the caller's transaction. A failed definition
    validation therefore also rolls back assistant and audit changes.
    """
    from eneo.flows.api.flow_assistant_router import flow_assistant_update_command

    access = await require_flow_edit_access(request, container, flow_id=id)
    service = container.flow_service()
    reservation = await service.reserve_draft_revision(
        flow_id=id, expected_revision=update.expected_revision
    )
    for change in update.assistants:
        assistant, _ = await service.update_reserved_flow_assistant(
            reservation=reservation,
            assistant_id=change.assistant_id,
            update=flow_assistant_update_command(change.changes),
            classification_judged_by_flow_update=True,
        )
        user = container.user()
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.ASSISTANT_UPDATED,
            entity_type=EntityType.ASSISTANT,
            entity_id=assistant.id,
            description=f"Updated flow-managed assistant '{assistant.name}' for flow {id}",
            metadata=AuditMetadata.standard(
                actor=user,
                target=assistant,
                extra={"flow_id": str(id), "origin": "flow_managed"},
            ),
        )
    definition = update.definition.model_copy(
        update={"expected_revision": update.expected_revision}
    )
    # With no step edit, explicitly retain saved rows. This also validates the
    # updated assistant against its final step configuration, without cleaning
    # inactive settings the editor never changed.
    changed = {change.step_id: change.changes for change in update.step_edits}
    saved_by_id = {step.id: step for step in access.flow.steps if step.id is not None}
    placed_ids: set[UUID] = (
        {slot.step_id for slot in update.step_order if slot.step_id is not None}
        if update.step_order is not None
        else set()
    )
    if (changed.keys() | placed_ids) - saved_by_id.keys():
        raise NotFoundException("Step not found.")
    overridden_steps = None
    if changed or update.new_steps or update.step_order is not None:
        new_flow_steps: list[FlowStep] = []
        for index, new_step in enumerate(update.new_steps):
            assistant, _ = await service.create_flow_assistant(
                flow_id=id, name=new_step.name
            )
            await service.update_reserved_flow_assistant(
                reservation=reservation,
                assistant_id=assistant.id,
                update=flow_assistant_update_command(new_step.assistant),
                classification_judged_by_flow_update=True,
            )
            step_request = FlowStepCreateRequest.model_validate(
                {
                    **new_step.configuration.model_dump(exclude_unset=True),
                    "assistant_id": assistant.id,
                    # Numbered with the others below.
                    "step_order": len(access.flow.steps) + index + 1,
                    "user_description": new_step.name,
                }
            )
            new_flow_steps.append(FlowAssembler().to_domain_step(step_request))
            user = container.user()
            await container.audit_service().log_async(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action=ActionType.ASSISTANT_CREATED,
                entity_type=EntityType.ASSISTANT,
                entity_id=assistant.id,
                description=f"Created a managed assistant for flow {id}",
                metadata=AuditMetadata.standard(
                    actor=user,
                    target=assistant,
                    extra={"flow_id": str(id), "origin": "flow_managed"},
                ),
            )
        overridden_steps = await _place_steps(
            update=update,
            changed=changed,
            saved_steps=access.flow.steps,
            new_steps=new_flow_steps,
            reservation=reservation,
            container=container,
            flow_id=id,
        )
    unchanged_ids: frozenset[UUID] = (
        frozenset(
            step.id
            for step in access.flow.steps
            if step.id is not None and step.id not in changed
        )
        if "steps" not in definition.model_fields_set
        else frozenset()
    )
    return await update_flow(
        id=id,
        request=request,
        flow_in=definition,
        container=container,
        unchanged_step_ids=unchanged_ids,
        steps_override=overridden_steps,
    )


async def _place_steps(
    *,
    update: "FlowEditorUpdateRequest",
    changed: Mapping[UUID, FlowEditorStepPatch],
    saved_steps: list[FlowStep],
    new_steps: list[FlowStep],
    reservation: DraftRevisionReservation,
    container: Container,
    flow_id: UUID,
) -> list[FlowStep]:
    """The steps in their new order, with the reads of moved steps following
    them, and the prompts that read moved steps renumbered in the same
    reservation."""

    saved_by_id = {step.id: step for step in saved_steps if step.id is not None}

    def saved_place(step_id: UUID) -> PlacedStep:
        saved = saved_by_id[step_id]
        patch = changed.get(step_id)
        if patch is None:
            return PlacedStep(step=saved, saved=saved)
        written = patch.model_dump(exclude_unset=True)
        return PlacedStep(
            step=FlowStep.model_validate({**saved.model_dump(), **written}),
            saved=saved,
            written_columns=frozenset(written),
        )

    if update.step_order is None:
        placed = [
            saved_place(step.id) for step in saved_steps if step.id is not None
        ] + [PlacedStep(step=step) for step in new_steps]
    else:
        placed = [
            saved_place(slot.step_id)
            if slot.step_id is not None
            else PlacedStep(step=new_steps[cast(int, slot.new_step)])
            for slot in update.step_order
        ]
    reordered = len(placed) - len(new_steps) != len(saved_steps) or any(
        item.saved is not None and item.saved.step_order != position
        for position, item in enumerate(placed, start=1)
    )
    service = container.flow_service()
    stored = (
        await service.get_flow_assistant_prompts(await service.get_flow(flow_id))
        if reordered
        else {}
    )
    rewritten = frozenset(
        change.assistant_id
        for change in update.assistants
        if "prompt" in change.changes.model_fields_set
    )
    structure = restructure_steps(
        placed,
        prompts={assistant_id: prompt.text for assistant_id, prompt in stored.items()},
        rewritten_prompts=rewritten,
    )
    user = container.user()
    for assistant_id, text in structure.renumbered_prompts.items():
        assistant, _ = await service.update_reserved_flow_assistant(
            reservation=reservation,
            assistant_id=assistant_id,
            update=AssistantUpdateCommand(
                prompt=PromptCreate(
                    text=text, description=stored[assistant_id].description
                )
            ),
            classification_judged_by_flow_update=True,
        )
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.ASSISTANT_UPDATED,
            entity_type=EntityType.ASSISTANT,
            entity_id=assistant.id,
            description=(
                f"Renumbered the step references in the prompt of '{assistant.name}' "
                f"for flow {flow_id}"
            ),
            metadata=AuditMetadata.standard(
                actor=user,
                target=assistant,
                extra={
                    "flow_id": str(flow_id),
                    "origin": "flow_managed",
                    "reason": "step_order_changed",
                },
            ),
        )
    return structure.steps
