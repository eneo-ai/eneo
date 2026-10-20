"""Authoring: create, update, publish and delete flows in a space.

The MCP tools and the REST router both call this service; ``channel`` says
which one, for the audit trail. Validation errors are returned as one
``BadRequestException`` whose message lists every problem, since the model
repairs a definition from that text in the same turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.flows.definition import (
    DocumentStep,
    FlowDefinition,
    FlowDefinitionError,
    LlmStep,
    StepKind,
    TranscribeStep,
    assign_step_ids,
    validate_definition,
)
from eneo.flows.flow_assembler import (
    definition_from_json,
    definition_to_json,
    flow_public,
    flow_revision_public,
    flow_revision_summary_public,
    flow_sparse_public,
)
from eneo.flows.flow_models import (
    FlowFinalOutputContractPublic,
    FlowPublic,
    FlowRevisionPublic,
    FlowRevisionSummaryPublic,
    FlowRunContractPublic,
    FlowRunContractStepPublic,
    FlowSparsePublic,
    PrincipalType,
)
from eneo.main.exceptions import (
    BadRequestException,
    FlowConversationConflictException,
    NotFoundException,
    UnauthorizedException,
)

if TYPE_CHECKING:
    from eneo.actors.actor_manager import ActorManager
    from eneo.audit.application.audit_service import AuditService
    from eneo.completion_models.application.completion_model_crud_service import (
        CompletionModelCRUDService,
    )
    from eneo.database.tables.flow_tables import FlowRevisions, Flows
    from eneo.flows.flow_repo import FlowRepository
    from eneo.spaces.space import Space
    from eneo.spaces.space_repo import SpaceRepository
    from eneo.users.user import UserInDB

# Step kinds whose runners are not shipped yet; publishing refuses them so a
# run can never reach a step that cannot execute.
UNAVAILABLE_STEP_KINDS = (StepKind.DOCUMENT, StepKind.TRANSCRIBE)
MAX_REVISION_PAGE = 100
NOTE_MAX_LENGTH = 500
DEFAULT_FLOW_NAME = "Nytt flöde"


class FlowService:
    def __init__(
        self,
        user: UserInDB,
        repo: FlowRepository,
        space_repo: SpaceRepository,
        actor_manager: ActorManager,
        completion_model_crud_service: CompletionModelCRUDService,
        audit_service: AuditService,
    ):
        self.user = user
        self.repo = repo
        self.space_repo = space_repo
        self.actor_manager = actor_manager
        self.completion_model_crud_service = completion_model_crud_service
        self.audit_service = audit_service

    # --- Authorization ---

    async def authorize_space(self, space_id: UUID, action: str = "read") -> Space:
        space = await self.space_repo.one(space_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        checks = {
            "read": actor.can_read_flows,
            "create": actor.can_create_flows,
            "edit": actor.can_edit_flows,
            "delete": actor.can_delete_flows,
            "publish": actor.can_publish_flows,
        }
        if not checks[action]():
            raise UnauthorizedException(
                f"You do not have permission to {action} flows in this space."
            )
        return space

    async def _require_flow(self, flow_id: UUID) -> Flows:
        flow = await self.repo.get_flow(flow_id, self.user.tenant_id)
        if flow is None:
            raise NotFoundException("Flow not found")
        return flow

    # --- Validation ---

    @staticmethod
    def _space_problems(definition: FlowDefinition, space: Space) -> list[str]:
        """Problems only the space can judge: models, collections, websites."""
        problems: list[str] = []
        for step in definition.steps:
            where = f"step '{step.key}'"
            if isinstance(step, LlmStep):
                if step.model_id is not None and not space.is_completion_model_in_space(
                    step.model_id
                ):
                    problems.append(
                        f"{where} model_id {step.model_id} is not available in this "
                        "space (omit model_id to use the space default)"
                    )
                for collection_id in step.knowledge.collection_ids:
                    try:
                        space.get_collection(collection_id)
                    except NotFoundException:
                        problems.append(
                            f"{where} knowledge collection {collection_id} is not "
                            "in this space"
                        )
                for website_id in step.knowledge.website_ids:
                    try:
                        space.get_website(website_id)
                    except NotFoundException:
                        problems.append(
                            f"{where} knowledge website {website_id} is not in "
                            "this space"
                        )
            elif isinstance(step, TranscribeStep):
                model_id = step.transcription_model_id
                if model_id is not None and not space.is_transcription_model_in_space(
                    model_id
                ):
                    problems.append(
                        f"{where} transcription_model_id {model_id} is not available "
                        "in this space"
                    )
                mapping = step.speaker_mapping
                if (
                    mapping is not None
                    and mapping.model_id is not None
                    and not space.is_completion_model_in_space(mapping.model_id)
                ):
                    problems.append(
                        f"{where} speaker_mapping.model_id {mapping.model_id} is not "
                        "available in this space"
                    )
        if space.get_default_completion_model() is None and any(
            isinstance(step, LlmStep) and step.model_id is None
            for step in definition.steps
        ):
            problems.append(
                "the space has no default completion model; set model_id on each "
                "llm step"
            )
        return problems

    def _validate(self, definition: FlowDefinition, space: Space) -> None:
        problems: list[str] = []
        try:
            validate_definition(definition)
        except FlowDefinitionError as exc:
            problems.extend(exc.errors)
        problems.extend(self._space_problems(definition, space))
        if problems:
            raise BadRequestException(
                "The flow definition has problems:\n- " + "\n- ".join(problems)
            )

    @staticmethod
    def _unavailable_kinds(definition: FlowDefinition) -> list[str]:
        return [
            f"step '{step.key}' has kind '{step.kind}'"
            for step in definition.steps
            if step.kind in UNAVAILABLE_STEP_KINDS
        ]

    # --- Audit ---

    async def _audit(
        self,
        action: ActionType,
        flow: Flows,
        description: str,
        *,
        channel: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=action,
            entity_type=EntityType.FLOW,
            entity_id=flow.id,
            description=description,
            metadata=AuditMetadata.standard(
                actor=self.user,
                target=flow,
                extra={"channel": channel, **(extra or {})},
            ),
        )

    # --- Public API ---

    async def _has_unpublished_changes(self, flow: Flows) -> bool:
        if flow.published_version is None:
            return True
        version = await self.repo.get_version(flow.id, flow.published_version)
        return version is None or version.definition != flow.definition

    async def _to_public(self, flow: Flows) -> FlowPublic:
        return flow_public(
            flow,
            has_unpublished_changes=await self._has_unpublished_changes(flow),
            revision=await self.repo.latest_revision_number(flow.id),
        )

    # --- Revisions ---

    async def _add_revision(
        self, flow: Flows, *, channel: str, note: str | None
    ) -> FlowRevisions:
        """Keep the flow as it is now as its next revision."""
        number = await self.repo.latest_revision_number(flow.id) + 1
        return await self.repo.add_revision(
            flow_id=flow.id,
            revision=number,
            name=flow.name,
            description=flow.description,
            definition=flow.definition,
            principal_type=PrincipalType.USER.value,
            principal_user_id=self.user.id,
            channel=channel,
            note=(note or "").strip()[:NOTE_MAX_LENGTH] or None,
        )

    async def _require_revision(self, flow_id: UUID, revision: int) -> FlowRevisions:
        row = await self.repo.get_revision(flow_id, revision)
        if row is None:
            raise NotFoundException("Flow revision not found")
        return row

    async def list_revisions(
        self, flow_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[FlowRevisionSummaryPublic], int]:
        """The flow's history, newest first, each row with what it changed."""
        flow = await self._require_flow(flow_id)
        await self.authorize_space(flow.space_id)
        limit = max(1, min(limit, MAX_REVISION_PAGE))
        rows, total = await self.repo.list_revisions(
            flow.id, limit=limit, offset=max(0, offset)
        )
        published = await self.repo.versions_by_revision(flow.id)
        # The oldest row on the page compares against the revision before it.
        older = (
            await self.repo.get_revision(flow.id, rows[-1].revision - 1)
            if rows and rows[-1].revision > 1
            else None
        )
        previous_of: list[Optional[FlowRevisions]] = [*rows[1:], older]
        return [
            flow_revision_summary_public(row, previous, published.get(row.revision))
            for row, previous in zip(rows, previous_of)
        ], total

    async def get_revision(self, flow_id: UUID, revision: int) -> FlowRevisionPublic:
        flow = await self._require_flow(flow_id)
        await self.authorize_space(flow.space_id)
        row = await self._require_revision(flow.id, revision)
        previous = (
            await self.repo.get_revision(flow.id, revision - 1)
            if revision > 1
            else None
        )
        published = await self.repo.versions_by_revision(flow.id)
        return flow_revision_public(row, previous, published.get(row.revision))

    async def restore_revision(
        self, flow_id: UUID, revision: int, *, channel: str = "api"
    ) -> FlowPublic:
        """Make an older revision the draft again, as a new revision.

        The restored steps keep the ids they had, so run history and review
        checkpoints of a step that was removed in between find it again.
        """
        flow = await self._require_flow(flow_id)
        await self.authorize_space(flow.space_id, "edit")
        row = await self._require_revision(flow.id, revision)
        description = row.description
        if description is None and flow.description is not None:
            description = ""
        return await self.update_flow(
            flow.id,
            name=row.name,
            description=description,
            definition=definition_from_json(row.definition),
            channel=channel,
            note=f"Restored revision {revision}",
            restored_from=revision,
        )

    async def create_flow(
        self,
        *,
        space_id: UUID,
        name: str,
        description: str | None,
        definition: FlowDefinition,
        conversation_id: UUID | None = None,
        channel: str = "api",
    ) -> FlowPublic:
        space = await self.authorize_space(space_id, "create")
        self._validate(definition, space)
        definition = assign_step_ids(definition)
        flow = await self.repo.add_flow(
            name=name,
            description=description,
            definition=definition_to_json(definition),
            space_id=space_id,
            tenant_id=self.user.tenant_id,
            user_id=self.user.id,
            conversation_id=conversation_id,
        )
        await self._add_revision(flow, channel=channel, note=None)
        await self._audit(
            ActionType.FLOW_CREATED,
            flow,
            "Created flow",
            channel=channel,
            extra={"step_count": len(definition.steps), "revision": 1},
        )
        return await self._to_public(flow)

    async def create_draft(
        self, *, space_id: UUID, name: str | None, channel: str = "api"
    ) -> FlowPublic:
        """An empty flow (no inputs, no steps) the space's flows chat then fills."""
        return await self.create_flow(
            space_id=space_id,
            name=(name or "").strip() or DEFAULT_FLOW_NAME,
            description=None,
            definition=FlowDefinition(),
            channel=channel,
        )

    async def bind_conversation(self, flow_id: UUID, session_id: UUID) -> FlowPublic:
        """Bind the flow to the chat that authors it.

        A flow has one chat: binding the same chat again is a no-op, another
        chat a conflict. The session must be the caller's own and talk to the
        space's flows authoring assistant.
        """
        flow = await self._require_flow(flow_id)
        await self.authorize_space(flow.space_id, "edit")
        if flow.conversation_id == session_id:
            return await self._to_public(flow)
        if flow.conversation_id is not None:
            raise FlowConversationConflictException(
                "The flow is already bound to another chat."
            )
        binding = await self.repo.get_session_binding(session_id)
        if binding is None:
            raise NotFoundException("Session not found")
        api_key_id = self.user.active_api_key.id if self.user.active_api_key else None
        owns = (binding.user_id is not None and binding.user_id == self.user.id) or (
            api_key_id is not None and binding.api_key_id == api_key_id
        )
        if not owns:
            raise UnauthorizedException("The session is not yours.")
        if binding.assistant_id is None or not await self.repo.is_authoring_assistant(
            binding.assistant_id, flow.space_id
        ):
            raise BadRequestException("The session is not a flows chat of this space.")
        if not await self.repo.bind_conversation(flow.id, session_id):
            raise FlowConversationConflictException(
                "The flow is already bound to another chat."
            )
        return await self._to_public(await self._require_flow(flow.id))

    async def update_flow(
        self,
        flow_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        definition: FlowDefinition | None = None,
        conversation_id: UUID | None = None,
        channel: str = "api",
        note: str | None = None,
        restored_from: int | None = None,
    ) -> FlowPublic:
        """Replace name, description and/or definition.

        Every change is kept as a new revision with ``note`` (one line on what
        changed and why); a call that changes nothing keeps no revision.
        ``conversation_id`` binds the flow to the chat it is edited from, but
        only when it has none yet: a flow keeps its first authoring chat.
        ``restored_from`` names the revision a restore copied; its steps keep
        the ids they had.
        """
        flow = await self._require_flow(flow_id)
        space = await self.authorize_space(flow.space_id, "edit")
        if conversation_id is not None and flow.conversation_id is None:
            await self.repo.set_conversation_id(flow.id, conversation_id)
        definition_json: Optional[dict[str, Any]] = None
        if definition is not None:
            self._validate(definition, space)
            previous = definition_from_json(flow.definition)
            definition = assign_step_ids(
                definition, previous, keep_unknown_ids=restored_from is not None
            )
            definition_json = definition_to_json(definition)
        changed = [
            field
            for field, value, current in (
                ("name", name, flow.name),
                ("description", description, flow.description),
                ("definition", definition_json, flow.definition),
            )
            if value is not None and value != current
        ]
        if not changed:
            return await self._to_public(flow)
        await self.repo.update_flow(
            flow.id, name=name, description=description, definition=definition_json
        )
        refreshed = await self._require_flow(flow.id)
        kept = await self._add_revision(refreshed, channel=channel, note=note)
        extra: dict[str, Any] = {"changed": changed, "revision": kept.revision}
        if restored_from is not None:
            extra["restored_from"] = restored_from
        await self._audit(
            ActionType.FLOW_UPDATED,
            refreshed,
            "Updated flow",
            channel=channel,
            extra=extra,
        )
        return await self._to_public(refreshed)

    async def get_flow(self, flow_id: UUID) -> FlowPublic:
        flow = await self._require_flow(flow_id)
        await self.authorize_space(flow.space_id)
        return await self._to_public(flow)

    async def flow_for_conversation(self, conversation_id: UUID) -> FlowPublic | None:
        """The flow a chat builds; a chat builds exactly one, or none yet."""
        flow = await self.repo.get_flow_by_conversation(
            conversation_id, self.user.tenant_id
        )
        if flow is None:
            return None
        await self.authorize_space(flow.space_id)
        return await self._to_public(flow)

    async def list_flows(self, space_id: UUID) -> list[FlowSparsePublic]:
        await self.authorize_space(space_id)
        rows = await self.repo.list_flows(space_id, self.user.tenant_id)
        return [flow_sparse_public(row.flow, row.last_run) for row in rows]

    async def publish_flow(self, flow_id: UUID, channel: str = "api") -> FlowPublic:
        """Freeze the draft as the next version; runs execute that snapshot."""
        flow = await self._require_flow(flow_id)
        space = await self.authorize_space(flow.space_id, "publish")
        definition = definition_from_json(flow.definition)
        if not definition.steps:
            raise BadRequestException("a flow needs at least one step to be published")
        self._validate(definition, space)
        unavailable = self._unavailable_kinds(definition)
        if unavailable:
            raise BadRequestException(
                "This version of Eneo cannot run document or transcribe steps yet, "
                "so the flow cannot be published: "
                + "; ".join(unavailable)
                + ". Replace them with llm, compose or review steps for now."
            )
        if flow.published_version is not None:
            current = await self.repo.get_version(flow.id, flow.published_version)
            if current is not None and current.definition == flow.definition:
                return await self._to_public(flow)
        version = (flow.published_version or 0) + 1
        await self.repo.add_version(
            flow_id=flow.id,
            version=version,
            definition=flow.definition,
            published_by_user_id=self.user.id,
            revision=await self.repo.latest_revision_number(flow.id) or None,
        )
        refreshed = await self._require_flow(flow.id)
        await self._audit(
            ActionType.FLOW_PUBLISHED,
            refreshed,
            f"Published flow version {version}",
            channel=channel,
            extra={"version": version},
        )
        return await self._to_public(refreshed)

    async def delete_flow(self, flow_id: UUID, channel: str = "api") -> None:
        flow = await self._require_flow(flow_id)
        await self.authorize_space(flow.space_id, "delete")
        await self.repo.soft_delete_flow(flow.id)
        await self._audit(
            ActionType.FLOW_DELETED, flow, "Deleted flow", channel=channel
        )

    async def get_published_definition(
        self, flow_id: UUID
    ) -> tuple[int, FlowDefinition]:
        flow = await self._require_flow(flow_id)
        await self.authorize_space(flow.space_id)
        if flow.published_version is None:
            raise BadRequestException("Flow is not published.")
        version = await self.repo.get_version(flow.id, flow.published_version)
        if version is None:
            raise NotFoundException("Published flow version not found")
        return version.version, definition_from_json(version.definition)

    async def get_run_contract(self, flow_id: UUID) -> FlowRunContractPublic:
        version, definition = await self.get_published_definition(flow_id)
        reviews = [
            FlowRunContractStepPublic(
                step_id=step.id, key=step.key, name=step.name, kind=StepKind(step.kind)
            )
            for step in definition.steps
            if step.kind == StepKind.REVIEW and step.id is not None
        ]
        final: Optional[FlowFinalOutputContractPublic] = None
        for step in reversed(definition.steps):
            if step.kind == StepKind.REVIEW:
                continue
            if isinstance(step, LlmStep):
                output_type = step.output.type
            elif isinstance(step, DocumentStep):
                output_type = step.format.value
            elif isinstance(step, TranscribeStep):
                output_type = "transcript"
            else:
                output_type = "text"
            final = FlowFinalOutputContractPublic(
                kind=StepKind(step.kind), output_type=output_type
            )
            break
        return FlowRunContractPublic(
            flow_id=flow_id,
            published_flow_version=version,
            form_fields=definition.form_fields,
            steps_requiring_review=reviews,
            final_output=final,
        )
