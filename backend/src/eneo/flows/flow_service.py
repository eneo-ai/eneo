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
    flow_sparse_public,
)
from eneo.flows.flow_models import (
    FlowFinalOutputContractPublic,
    FlowPublic,
    FlowRunContractPublic,
    FlowRunContractStepPublic,
    FlowSparsePublic,
)
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)

if TYPE_CHECKING:
    from eneo.actors.actor_manager import ActorManager
    from eneo.audit.application.audit_service import AuditService
    from eneo.completion_models.application.completion_model_crud_service import (
        CompletionModelCRUDService,
    )
    from eneo.database.tables.flow_tables import Flows
    from eneo.flows.flow_repo import FlowRepository
    from eneo.spaces.space import Space
    from eneo.spaces.space_repo import SpaceRepository
    from eneo.users.user import UserInDB

# Step kinds whose runners are not shipped yet; publishing refuses them so a
# run can never reach a step that cannot execute.
UNAVAILABLE_STEP_KINDS = (StepKind.DOCUMENT, StepKind.TRANSCRIBE)


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
            flow, has_unpublished_changes=await self._has_unpublished_changes(flow)
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
        await self._audit(
            ActionType.FLOW_CREATED,
            flow,
            "Created flow",
            channel=channel,
            extra={"step_count": len(definition.steps)},
        )
        return await self._to_public(flow)

    async def update_flow(
        self,
        flow_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        definition: FlowDefinition | None = None,
        conversation_id: UUID | None = None,
        channel: str = "api",
    ) -> FlowPublic:
        """Replace name, description and/or definition.

        ``conversation_id`` binds the flow to the chat it is edited from, but
        only when it has none yet: a flow keeps its first authoring chat.
        """
        flow = await self._require_flow(flow_id)
        space = await self.authorize_space(flow.space_id, "edit")
        if conversation_id is not None and flow.conversation_id is None:
            await self.repo.set_conversation_id(flow.id, conversation_id)
        definition_json: Optional[dict[str, Any]] = None
        if definition is not None:
            self._validate(definition, space)
            previous = definition_from_json(flow.definition)
            definition = assign_step_ids(definition, previous)
            definition_json = definition_to_json(definition)
        await self.repo.update_flow(
            flow.id, name=name, description=description, definition=definition_json
        )
        refreshed = await self._require_flow(flow.id)
        changed = [
            field
            for field, value in (
                ("name", name),
                ("description", description),
                ("definition", definition_json),
            )
            if value is not None
        ]
        await self._audit(
            ActionType.FLOW_UPDATED,
            refreshed,
            "Updated flow",
            channel=channel,
            extra={"changed": changed},
        )
        return await self._to_public(refreshed)

    async def get_flow(self, flow_id: UUID) -> FlowPublic:
        flow = await self._require_flow(flow_id)
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
