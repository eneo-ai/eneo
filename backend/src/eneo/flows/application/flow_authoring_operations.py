"""Shared authorized authoring operations for REST and loopback MCP.

The existing core access policies, service validation, snapshots and audit remain
one path. Callers own a transaction; exceptions must reach its context manager.
A caller that opens it with ``authoring_transaction`` has the change's audit
entries logged after the commit; otherwise an operation logs them once every
check that can refuse the change has passed.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import replace
from typing import Any, cast
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.access_denial_code import AccessDenialCode
from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_definition_access import (
    flow_permissions,
    require_flow_current_definition_access,
    require_flow_edit_access,
    require_flow_publish_access,
    require_flow_unpublish_access,
)
from eneo.flows.api.flow_models import (
    FlowCreateRequest,
    FlowEditorAssistantChange,
    FlowEditorStepPatch,
    FlowEditorUpdateRequest,
    FlowPublic,
    FlowStepCreateRequest,
    FlowUpdateRequest,
)
from eneo.flows.application.flow_step_structure import (
    READ_COLUMNS,
    PlacedStep,
    StepStructure,
    form_field_change,
    restructure_steps,
)
from eneo.flows.domain.canonical_json_hash import json_values_differ
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import (
    FlowUnauthorizedException,
)
from eneo.flows.flow_authoring_name import FlowNameTakenError
from eneo.flows.flow_evidence_policy import flow_evidence_metadata_facts
from eneo.flows.http_transport import redact_persisted_config
from eneo.flows.infrastructure.flow_repo import DraftRevisionReservation
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    ConflictException,
    NotFoundException,
)
from eneo.main.models import NOT_PROVIDED, NotProvided
from eneo.prompts.api.prompt_models import PromptCreate

_FLOW_NAME_TAKEN_MESSAGE = "A flow with this name already exists in this space."


def _flow_name_taken_conflict() -> ConflictException:
    return ConflictException(
        _FLOW_NAME_TAKEN_MESSAGE, code=FlowApiErrorCode.FLOW_NAME_TAKEN.value
    )


def _classification_override_step_orders(flow_data: FlowUpdateRequest) -> list[int]:
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
    scope_filter = flow_access_context.get_scope_filter(request)
    actor = await flow_access_context.resolve_space_actor(
        request,
        container,
        space_id=flow_in.space_id,
        required_access=FlowApiAction.EDIT,
        scope_mismatch_message=(
            f"API key is scoped to space '{scope_filter.space_id}'. "
            f"Cannot create flow in space '{flow_in.space_id}'."
        ),
    )
    if not actor.can_create_flows():
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
            metadata_json=flow_in.metadata_json,
        )
    except FlowNameTakenError as exc:
        raise _flow_name_taken_conflict() from exc

    created_flow_id = created.require_persisted_id()
    audit, owns_audit = _change_audit(container)
    audit.add(
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
    if owns_audit:
        await audit.log()

    return assembler.to_public(
        created,
        permissions=flow_permissions(
            container,
            flow=created,
            actor=actor,
            scope_filter=scope_filter,
        ),
    )


async def get_flow(id: UUID, request: Request, container: Container) -> FlowPublic:
    access_context = await require_flow_current_definition_access(
        request,
        container,
        flow_id=id,
    )
    return _flow_public(container, access_context.flow, access_context)


async def update_flow(
    id: UUID,
    request: Request,
    flow_in: FlowUpdateRequest,
    container: Container,
) -> FlowPublic:
    """A manual update. ``steps``, when sent, replaces the step list: a step
    that keeps its id is moved there, one without an id is new, and a saved
    step left out is removed. Reads of moved, renamed and removed steps and
    of renamed form fields follow the change as in the editor update."""

    access = await require_flow_edit_access(request, container, flow_id=id)
    # Without the editor's own revision the write is fenced on the one this
    # request was authorized at, which is also the state the audit entry
    # compares against.
    expected_revision = (
        access.flow.draft_revision
        if flow_in.expected_revision is None
        else flow_in.expected_revision
    )
    reservation = await container.flow_service().reserve_draft_revision(
        flow_id=id, expected_revision=expected_revision
    )
    audit, owns_audit = _change_audit(container)
    definition = flow_in.model_copy(update={"expected_revision": expected_revision})
    replaces_steps = "steps" in flow_in.model_fields_set
    placed = (
        _replacement_placement(flow_in, access.flow.steps)
        if replaces_steps
        # Rewritten as a client reads them, so their credentials stay the
        # stored ones when the save resolves the sentinels.
        else [PlacedStep(step=_as_read(step), saved=step) for step in access.flow.steps]
    )
    structure = await _follow_reads(
        placed=placed,
        saved=access.flow,
        definition=definition,
        rewritten_prompts=frozenset(),
        reservation=reservation,
        container=container,
        audit=audit,
    )
    steps_override = None
    if (
        placed is not None
        and structure is not None
        and (replaces_steps or _rewrites_steps(placed, structure.steps))
    ):
        steps_override = structure.steps
    updated = await _write_definition(
        access,
        definition,
        container,
        audit=audit,
        steps_override=steps_override,
    )
    if owns_audit:
        await audit.log()
    return updated


async def _write_definition(
    access_context: flow_access_context.FlowAccessContext,
    flow_in: FlowUpdateRequest,
    container: Container,
    *,
    audit: _AuditEntries,
    unchanged_step_ids: frozenset[UUID] = frozenset(),
    steps_override: list[FlowStep] | None = None,
) -> FlowPublic:
    assembler = FlowAssembler()
    payload = flow_in.model_dump(exclude_unset=True)
    steps = None
    if "steps" in payload:
        steps = [assembler.to_domain_step_for_update(step) for step in flow_in.steps]

    if steps_override is not None:
        steps = steps_override
    if unchanged_step_ids and steps is None:
        steps = access_context.flow.steps

    flow_id = access_context.flow.require_persisted_id()
    try:
        updated = await container.flow_service().update_flow(
            flow_id=flow_id,
            name=payload.get("name", NOT_PROVIDED),
            description=payload.get("description", NOT_PROVIDED),
            steps=steps,
            metadata_json=payload.get("metadata_json", NOT_PROVIDED),
            expected_revision=flow_in.expected_revision,
            unchanged_step_ids=unchanged_step_ids,
        )
    except FlowNameTakenError as exc:
        raise _flow_name_taken_conflict() from exc

    updated_flow_id = updated.require_persisted_id()
    user = container.user()
    audit.add(
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
        audit.add(
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

    return _flow_public(container, updated, access_context)


async def publish_flow(
    id: UUID,
    request: Request,
    container: Container,
    *,
    expected_revision: int | None = None,
) -> FlowPublic:
    access = await require_flow_publish_access(request, container, flow_id=id)
    if expected_revision is not None:
        await container.flow_service().reserve_draft_revision(
            flow_id=id, expected_revision=expected_revision
        )

    published = await container.flow_service().publish_flow(flow_id=id)
    user = container.user()
    audit, owns_audit = _change_audit(container)
    audit.add(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_PUBLISHED,
        entity_type=EntityType.FLOW,
        entity_id=id,
        description=f"Published flow '{published.name}' as version {published.published_version}",
        metadata=AuditMetadata.standard(actor=user, target=published),
    )
    if owns_audit:
        await audit.log()
    return _flow_public(container, published, access)


async def unpublish_flow(
    id: UUID,
    request: Request,
    container: Container,
    *,
    expected_revision: int | None = None,
) -> FlowPublic:
    access = await require_flow_unpublish_access(request, container, flow_id=id)
    if expected_revision is not None:
        await container.flow_service().reserve_draft_revision(
            flow_id=id, expected_revision=expected_revision
        )

    unpublished = await container.flow_service().unpublish_flow(flow_id=id)
    user = container.user()
    audit, owns_audit = _change_audit(container)
    audit.add(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_UNPUBLISHED,
        entity_type=EntityType.FLOW,
        entity_id=id,
        description=f"Unpublished flow '{unpublished.name}'",
        metadata=AuditMetadata.standard(actor=user, target=unpublished),
    )
    if owns_audit:
        await audit.log()
    return _flow_public(container, unpublished, access)


def _flow_public(
    container: Container,
    flow: Flow,
    access: flow_access_context.FlowAccessContext,
) -> FlowPublic:
    """``flow`` with the permissions of the caller the access was checked for."""

    actor = access.actor
    assert actor is not None, "a resolved flow access context carries its actor"
    return FlowAssembler().to_public(
        flow,
        permissions=flow_permissions(
            container, flow=flow, actor=actor, scope_filter=access.scope_filter
        ),
    )


async def apply_editor_update(
    id: UUID, request: Request, update: "FlowEditorUpdateRequest", container: Container
) -> FlowPublic:
    """Reserve the core revision before any child write; one commit and audit.

    Exceptions must escape the caller's transaction. A failed definition
    validation therefore also rolls back assistant changes, and the audit
    entries of the change are logged only once every check has passed.
    """
    from eneo.flows.api.flow_assistant_router import flow_assistant_update_command

    access = await require_flow_edit_access(request, container, flow_id=id)
    service = container.flow_service()
    reservation = await service.reserve_draft_revision(
        flow_id=id, expected_revision=update.expected_revision
    )
    audit, owns_audit = _change_audit(container)
    user = container.user()
    copies = _copy_on_write_changes(update, access.flow.steps)
    for change in update.assistants:
        if change in copies:
            continue
        assistant, _ = await service.update_reserved_flow_assistant(
            reservation=reservation,
            assistant_id=change.assistant_id,
            update=flow_assistant_update_command(change.changes),
            classification_judged_by_flow_update=True,
        )
        audit.add(
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
    replaces_steps = "steps" in definition.model_fields_set
    changed = {change.step_id: change.changes for change in update.step_edits}
    saved_by_id = {step.id: step for step in access.flow.steps if step.id is not None}
    placed_ids: set[UUID] = (
        {slot.step_id for slot in update.step_order if slot.step_id is not None}
        if update.step_order is not None
        else set()
    )
    if (changed.keys() | placed_ids) - saved_by_id.keys():
        raise NotFoundException("Step not found.")
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
        new_flow_steps.append(
            new_flow_step(
                new_step.configuration,
                assistant_id=assistant.id,
                # Numbered with the others below.
                step_order=len(access.flow.steps) + index + 1,
                name=new_step.name,
            )
        )
        audit.add(
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
    edits_steps = bool(changed or update.new_steps or update.step_order is not None)
    if replaces_steps:
        placed = _replacement_placement(definition, access.flow.steps)
    elif edits_steps:
        placed = sparse_placement(
            update=update,
            changed=changed,
            saved_steps=access.flow.steps,
            new_steps=new_flow_steps,
        )
    else:
        placed = [PlacedStep(step=step, saved=step) for step in access.flow.steps]
    if placed is not None:
        # A step that gets its own copy of a shared assistant reads the
        # prompt the change gives the copy, not the shared one.
        copied_prompts = {
            change.step_id
            for change in copies
            if "prompt" in change.changes.model_fields_set
        }
        placed = [
            replace(item, prompt_written=True)
            if item.saved is not None and item.saved.id in copied_prompts
            else item
            for item in placed
        ]
    structure = await _follow_reads(
        placed=placed,
        saved=access.flow,
        definition=definition,
        rewritten_prompts=frozenset(
            change.assistant_id
            for change in update.assistants
            if change not in copies and "prompt" in change.changes.model_fields_set
        ),
        reservation=reservation,
        container=container,
        audit=audit,
    )
    steps_override = None
    if (
        placed is not None
        and structure is not None
        and (
            replaces_steps
            or edits_steps
            or copies
            or _rewrites_steps(placed, structure.steps)
        )
    ):
        steps_override = await _give_steps_their_copies(
            structure,
            copies=copies,
            reservation=reservation,
            container=container,
            audit=audit,
        )
    # With no step edit, explicitly retain saved rows. This also validates the
    # updated assistant against its final step configuration, without cleaning
    # inactive settings the editor never changed.
    unchanged_ids: frozenset[UUID] = (
        frozenset(
            step.id
            for step in access.flow.steps
            if step.id is not None and step.id not in changed
        )
        if not replaces_steps
        else frozenset()
    )
    updated = await _write_definition(
        access,
        definition,
        container,
        audit=audit,
        unchanged_step_ids=unchanged_ids,
        steps_override=steps_override,
    )
    if owns_audit:
        await audit.log()
    return updated


def _copy_on_write_changes(
    update: "FlowEditorUpdateRequest", saved_steps: list[FlowStep]
) -> list[FlowEditorAssistantChange]:
    """The assistant changes that name a step whose assistant other steps
    share: that step gets its own copy with the change. A change naming a
    step that does not use the assistant is refused."""

    saved_by_id = {step.id: step for step in saved_steps if step.id is not None}
    copies: list[FlowEditorAssistantChange] = []
    for change in update.assistants:
        if change.step_id is None:
            continue
        step = saved_by_id.get(change.step_id)
        if step is None or step.assistant_id != change.assistant_id:
            raise NotFoundException("Step not found.")
        if any(
            other.id != step.id and other.assistant_id == step.assistant_id
            for other in saved_steps
        ):
            copies.append(change)
    return copies


async def _give_steps_their_copies(
    structure: StepStructure,
    *,
    copies: list[FlowEditorAssistantChange],
    reservation: DraftRevisionReservation,
    container: Container,
    audit: _AuditEntries,
) -> list[FlowStep]:
    """``structure``'s steps, each step a change names pointing at its own copy
    of the assistant it shared, the change applied to the copy. The copy
    starts from the shared assistant as this edit has written it, its reads
    that followed the change included."""

    from eneo.flows.api.flow_assistant_router import flow_assistant_update_command

    if not copies:
        return structure.steps
    service = container.flow_service()
    user = container.user()
    steps = list(structure.steps)
    for change in copies:
        index = next(
            (index for index, step in enumerate(steps) if step.id == change.step_id),
            None,
        )
        if index is None:
            # The same edit removes the step.
            raise NotFoundException("Step not found.")
        copy, _ = await service.copy_reserved_flow_assistant(
            reservation=reservation, assistant_id=change.assistant_id
        )
        copy, _ = await service.update_reserved_flow_assistant(
            reservation=reservation,
            assistant_id=copy.id,
            update=flow_assistant_update_command(change.changes),
            classification_judged_by_flow_update=True,
        )
        steps[index] = steps[index].model_copy(update={"assistant_id": copy.id})
        flow_id = reservation.flow_id
        audit.add(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.ASSISTANT_CREATED,
            entity_type=EntityType.ASSISTANT,
            entity_id=copy.id,
            description=(
                f"Gave step {steps[index].step_order} of flow {flow_id} its own copy "
                f"of the assistant '{copy.name}' it shared, with its change"
            ),
            metadata=AuditMetadata.standard(
                actor=user,
                target=copy,
                extra={
                    "flow_id": str(flow_id),
                    "origin": "flow_managed",
                    "step_id": str(change.step_id),
                    "copied_from": str(change.assistant_id),
                },
            ),
        )
    return steps


class _AuditEntries:
    """The audit entries of one authoring change, logged only once the change
    is saved: a refused change, which its transaction rolls back, leaves no
    entry behind."""

    def __init__(self, container: Container) -> None:
        self._container = container
        self._entries: list[dict[str, Any]] = []

    def add(self, **entry: Any) -> None:
        self._entries.append(entry)

    def __bool__(self) -> bool:
        return bool(self._entries)

    async def log(self) -> None:
        audit_service = self._container.audit_service()
        entries, self._entries = self._entries, []
        for entry in entries:
            await audit_service.log_async(**entry)


_HELD_AUDIT: ContextVar[_AuditEntries | None] = ContextVar(
    "held_flow_authoring_audit", default=None
)


@asynccontextmanager
async def authoring_transaction(container: Container) -> AsyncGenerator[None]:
    """One authoring change in a transaction of its own, for a caller that has
    none open. The audit entries of the change are held while it runs and
    logged once the transaction has committed; a change that is refused, and
    rolled back, logs none."""

    entries = _AuditEntries(container)
    session = cast(AsyncSession, container.session())
    token = _HELD_AUDIT.set(entries)
    try:
        async with session.begin():
            yield
    finally:
        _HELD_AUDIT.reset(token)
    if entries:
        # Whether the tenant logs an action is read from the database, in a
        # transaction of its own: the session does not begin one by itself.
        async with session.begin():
            await entries.log()


def _change_audit(container: Container) -> tuple[_AuditEntries, bool]:
    """Where an operation puts its audit entries: those of the surrounding
    ``authoring_transaction``, logged after its commit, or its own, which it
    logs once every check has passed (``True``)."""

    held = _HELD_AUDIT.get()
    if held is not None:
        return held, False
    return _AuditEntries(container), True


def _as_read(step: FlowStep) -> FlowStep:
    """A saved step as a client reads it: stored credentials as sentinels."""

    return step.model_copy(
        update={
            "input_config": redact_persisted_config(step.input_config),
            "output_config": redact_persisted_config(step.output_config),
        },
        deep=True,
    )


def _replacement_placement(
    flow_in: FlowUpdateRequest, saved_steps: list[FlowStep]
) -> list[PlacedStep] | None:
    """The steps a full replacement sends, at the places their step orders
    give them. A read column a step sends as its client read it is the saved
    one, so its reads follow the change; one it sends changed is written as
    given. None when the steps cannot be placed (an unknown or repeated id,
    step orders that are not 1 to n): the save refuses those itself."""

    assembler = FlowAssembler()
    requested = [assembler.to_domain_step_for_update(step) for step in flow_in.steps]
    saved_by_id = {step.id: step for step in saved_steps if step.id is not None}
    ids = [step.id for step in requested if step.id is not None]
    if len(ids) != len(set(ids)) or any(step_id not in saved_by_id for step_id in ids):
        return None
    ordered = sorted(requested, key=lambda step: step.step_order)
    if [step.step_order for step in ordered] != list(range(1, len(ordered) + 1)):
        return None
    placed: list[PlacedStep] = []
    for step in ordered:
        saved = saved_by_id.get(step.id) if step.id is not None else None
        if saved is None:
            placed.append(PlacedStep(step=step))
            continue
        read = _as_read(saved)
        placed.append(
            PlacedStep(
                step=step,
                saved=saved,
                written_columns=frozenset(
                    column
                    for column in READ_COLUMNS
                    if json_values_differ(getattr(step, column), getattr(read, column))
                ),
            )
        )
    return placed


def new_flow_step(
    configuration: FlowEditorStepPatch,
    *,
    assistant_id: UUID,
    step_order: int,
    name: str | None,
) -> FlowStep:
    """A new step of an editor update, as its request validates it."""

    step_request = FlowStepCreateRequest.model_validate(
        {
            **configuration.model_dump(exclude_unset=True),
            "assistant_id": assistant_id,
            "step_order": step_order,
            "user_description": name,
        }
    )
    return FlowAssembler().to_domain_step(step_request)


def sparse_placement(
    *,
    update: "FlowEditorUpdateRequest",
    changed: Mapping[UUID, FlowEditorStepPatch],
    saved_steps: list[FlowStep],
    new_steps: list[FlowStep],
) -> list[PlacedStep]:
    """The steps of an editor update in their new order: sparse edits on the
    saved steps, new steps where ``step_order`` places them (else last)."""

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
        return [saved_place(step.id) for step in saved_steps if step.id is not None] + [
            PlacedStep(step=step) for step in new_steps
        ]
    return [
        saved_place(slot.step_id)
        if slot.step_id is not None
        else PlacedStep(step=new_steps[cast(int, slot.new_step)])
        for slot in update.step_order
    ]


def _rewrites_steps(placed: list[PlacedStep], steps: list[FlowStep]) -> bool:
    return any(
        json_values_differ(getattr(item.step, column), getattr(step, column))
        for item, step in zip(placed, steps, strict=True)
        for column in READ_COLUMNS
    )


async def _follow_reads(
    *,
    placed: list[PlacedStep] | None,
    saved: Flow,
    definition: FlowUpdateRequest,
    rewritten_prompts: frozenset[UUID],
    reservation: DraftRevisionReservation,
    container: Container,
    audit: _AuditEntries,
) -> StepStructure | None:
    """The steps in their new order with every kept read following the
    change: moved and removed steps, renamed steps, renamed and removed run
    form fields. The prompts whose reads follow it are written in the same
    reservation. None when the steps cannot be placed."""

    if placed is None:
        return None
    metadata = (
        definition.metadata_json
        if "metadata_json" in definition.model_fields_set
        and not isinstance(definition.metadata_json, NotProvided)
        else saved.metadata_json
    )
    form_fields = (
        form_field_change(
            saved_metadata=saved.metadata_json,
            metadata=metadata,
            renames=definition.form_field_renames,
        )
        if "metadata_json" in definition.model_fields_set
        or definition.form_field_renames
        else None
    )
    kept = [item for item in placed if item.saved is not None]
    moves_steps = len(kept) != len(saved.steps) or any(
        item.saved is not None and item.saved.step_order != position
        for position, item in enumerate(placed, start=1)
    )
    renames_steps = any(
        (item.step.user_description or "").strip()
        != (cast(FlowStep, item.saved).user_description or "").strip()
        for item in kept
    )
    service = container.flow_service()
    stored = (
        await service.get_flow_assistant_prompts(
            await service.get_flow(saved.require_persisted_id())
        )
        if moves_steps
        or renames_steps
        or (form_fields is not None and form_fields.changes_reads)
        else {}
    )
    structure = restructure_steps(
        placed,
        prompts={assistant_id: prompt.text for assistant_id, prompt in stored.items()},
        rewritten_prompts=rewritten_prompts,
        saved_steps=saved.steps,
        form_fields=form_fields,
    )
    user = container.user()
    flow_id = saved.require_persisted_id()
    for assistant_id, text in structure.changed_prompts.items():
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
        audit.add(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.ASSISTANT_UPDATED,
            entity_type=EntityType.ASSISTANT,
            entity_id=assistant.id,
            description=(
                f"Rewrote the step and form field reads in the prompt of "
                f"'{assistant.name}' for flow {flow_id}"
            ),
            metadata=AuditMetadata.standard(
                actor=user,
                target=assistant,
                extra={
                    "flow_id": str(flow_id),
                    "origin": "flow_managed",
                    "reasons": sorted(structure.causes),
                },
            ),
        )
    return structure
