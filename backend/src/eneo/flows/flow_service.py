"""Authoring: create, update, publish and delete flows in a space.

The MCP tools and the REST router both call this service; ``channel`` says
which one, for the audit trail. Validation errors are returned as one
``BadRequestException`` whose message lists every problem, since the model
repairs a definition from that text in the same turn.

The service also keeps the flow's files: the document templates its steps
name (pinned to the flow so the file lifecycle keeps them) and the runtime
uploads API consumers give a run before starting it.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_models import is_service_api_key
from eneo.flows.definition import (
    DocumentStep,
    FlowDefinition,
    FlowDefinitionError,
    FunctionStep,
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
    step_origins,
)
from eneo.flows.flow_models import (
    FlowEditorPublic,
    FlowFinalOutputContractPublic,
    FlowPublic,
    FlowRevisionPublic,
    FlowRevisionSummaryPublic,
    FlowRunContractPublic,
    FlowRunContractStepPublic,
    FlowSparsePublic,
    PrincipalType,
)
from eneo.flows.flow_runtime_paths import FlowRuntimePublic, build_flow_runtime_paths
from eneo.flows.speaker_service import configured_speaker_service
from eneo.main.config import get_settings
from eneo.main.exceptions import (
    BadRequestException,
    FlowConversationConflictException,
    FlowDefinitionProblemsException,
    FlowNotEditingException,
    FlowRevisionConflictException,
    FlowRuntimeFileInUseException,
    NotFoundException,
    UnauthorizedException,
)

if TYPE_CHECKING:
    from fastapi import UploadFile

    from eneo.actors.actor_manager import ActorManager
    from eneo.assistants.assistant_service import AssistantService
    from eneo.audit.application.audit_service import AuditService
    from eneo.completion_models.application.completion_model_crud_service import (
        CompletionModelCRUDService,
    )
    from eneo.database.tables.flow_tables import FlowRevisions, Flows
    from eneo.files.file_models import FilePublic
    from eneo.files.file_service import FileService
    from eneo.flows.flow_repo import FlowRepository
    from eneo.spaces.space import Space
    from eneo.spaces.space_repo import SpaceRepository
    from eneo.users.user import UserInDB
    from eneo.users.user_repo import UsersRepository

# Step kinds whose runners are not shipped yet; publishing refuses them so a
# run can never reach a step that cannot execute.
UNAVAILABLE_STEP_KINDS: tuple[StepKind, ...] = ()
# The capability a document step's provider is resolved through.
DOCUMENT_CAPABILITY = "file_creation"
# Forms the document provider can fill (Word content controls or {{placeholders}}).
TEMPLATE_EXTENSIONS = (".docx", ".txt", ".md")
TEMPLATE_ROLE = "template"
RUNTIME_UPLOAD_ROLE = "runtime_upload"
MAX_REVISION_PAGE = 100
NOTE_MAX_LENGTH = 500
DEFAULT_FLOW_NAME = "Nytt flöde"
# How far back a step's origin is looked for in the flow's history.
STEP_ORIGIN_WINDOW = 50


class FlowService:
    def __init__(
        self,
        user: UserInDB,
        repo: FlowRepository,
        space_repo: SpaceRepository,
        actor_manager: ActorManager,
        completion_model_crud_service: CompletionModelCRUDService,
        audit_service: AuditService,
        file_service: FileService,
        user_repo: UsersRepository,
        assistant_service: AssistantService,
    ):
        self.user = user
        self.repo = repo
        self.space_repo = space_repo
        self.actor_manager = actor_manager
        self.completion_model_crud_service = completion_model_crud_service
        self.audit_service = audit_service
        self.file_service = file_service
        self.user_repo = user_repo
        self.assistant_service = assistant_service

    # --- Principals ---

    @property
    def service_key_id(self) -> Optional[UUID]:
        """The key id when the caller is a service API key, else None.

        A service key is an automation principal: it runs published flows
        and reads what they produce, but never authors (flows are written by
        people, in their chat), and it owns no rows, so what it uploads is
        stored as the flow author's.
        """
        if is_service_api_key(self.user) and self.user.active_api_key is not None:
            return self.user.active_api_key.id
        return None

    async def flow_author(self, flow: Flows) -> UserInDB:
        """The person who built the flow, who stands in for a service principal."""
        author = (
            await self.user_repo.get_user_by_id(id=flow.user_id)
            if flow.user_id is not None
            else None
        )
        if author is None or author.tenant_id != self.user.tenant_id:
            raise BadRequestException(
                "The flow has no author to act as; a person in the space has to "
                "save it before an API key can use it."
            )
        return author

    def _transaction(self) -> contextlib.AbstractAsyncContextManager[object]:
        """A write block: the ambient transaction when one is open, else a new one
        (the runtime upload path runs outside one, since object-store uploads
        cannot be made inside a transaction)."""
        session = self.repo.session
        if session.in_transaction():
            return contextlib.nullcontext()
        return session.begin()

    # --- Authorization ---

    async def authorize_space(self, space_id: UUID, action: str = "read") -> Space:
        if action != "read" and self.service_key_id is not None:
            raise UnauthorizedException(
                "Service API keys run flows; they do not create, edit, publish "
                "or delete them."
            )
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
        # A draft is not a thing an automation can see: only published flows
        # exist for a service principal.
        if flow is None or (
            self.service_key_id is not None and flow.published_version is None
        ):
            raise NotFoundException("Flow not found")
        return flow

    async def can_operate_runs(self, space_id: UUID) -> bool:
        space = await self.authorize_space(space_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        return actor.can_operate_flow_runs()

    async def _lock_revision(
        self, flow_id: UUID, expected_revision: int | None
    ) -> Flows:
        flow = await self.repo.get_flow(flow_id, self.user.tenant_id, for_update=True)
        if flow is None:
            raise NotFoundException("Flow not found")
        if expected_revision is not None and (
            await self.repo.latest_revision_number(flow_id) != expected_revision
        ):
            raise FlowRevisionConflictException()
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
            raise FlowDefinitionProblemsException(problems)

    @staticmethod
    def _unavailable_kinds(definition: FlowDefinition) -> list[str]:
        return [
            f"step '{step.key}' has kind '{step.kind}'"
            for step in definition.steps
            if step.kind in UNAVAILABLE_STEP_KINDS
        ]

    @staticmethod
    def _document_steps(definition: FlowDefinition) -> list[DocumentStep]:
        return [step for step in definition.steps if isinstance(step, DocumentStep)]

    async def _template_problems(
        self, flow_id: Optional[UUID], definition: FlowDefinition
    ) -> list[str]:
        """Template files a document step names must be files the author
        attached (their own) or files already pinned to the flow, and forms
        the provider can fill."""
        problems: list[str] = []
        for step in self._document_steps(definition):
            file_id = step.template_file_id
            if file_id is None:
                continue
            where = f"step '{step.key}'"
            if (
                flow_id is not None
                and await self.repo.get_flow_file(flow_id, file_id, role=TEMPLATE_ROLE)
                is not None
            ):
                continue
            try:
                info = await self.file_service.get_file_by_id(file_id)
            except (NotFoundException, UnauthorizedException):
                problems.append(
                    f"{where} template_file_id {file_id} is not a file attached in "
                    "this chat (use the file_ref of an attached .docx, .txt or .md)"
                )
                continue
            if not info.name.lower().endswith(TEMPLATE_EXTENSIONS):
                problems.append(
                    f"{where} template file '{info.name}' is not a .docx, .txt or "
                    ".md form"
                )
        return problems

    async def _sync_template_files(
        self, flow_id: UUID, definition: FlowDefinition
    ) -> None:
        """Pin every template the definition names to the flow.

        A template a step stops naming stays pinned (a published version may
        still run with it); it only loses its step. The flow's deletion is
        what releases its files.
        """
        wanted: dict[UUID, Optional[UUID]] = {
            step.template_file_id: step.id
            for step in self._document_steps(definition)
            if step.template_file_id is not None
        }
        pinned = {
            row.file_id: row
            for row in await self.repo.list_flow_files(flow_id, role=TEMPLATE_ROLE)
        }
        for file_id, step_id in wanted.items():
            row = pinned.get(file_id)
            if row is None:
                await self.repo.add_flow_file(
                    flow_id=flow_id,
                    file_id=file_id,
                    role=TEMPLATE_ROLE,
                    step_id=step_id,
                    principal_type=PrincipalType.USER.value,
                    principal_user_id=self.user.id,
                )
            elif row.step_id != step_id:
                await self.repo.set_flow_file_step(
                    flow_id, file_id, role=TEMPLATE_ROLE, step_id=step_id
                )
        for file_id in pinned.keys() - wanted.keys():
            if pinned[file_id].step_id is not None:
                await self.repo.set_flow_file_step(
                    flow_id, file_id, role=TEMPLATE_ROLE, step_id=None
                )

    @staticmethod
    def _document_capability_problems(
        definition: FlowDefinition, space: Space
    ) -> list[str]:
        """A document or function step runs as a call of the space for a
        capability; the space must allow it (a personal space always does).
        A transcribe step needs a transcription model and, for speaker
        labels, the configured speaker service."""
        problems: list[str] = []
        needed: dict[str, list[str]] = {}
        for step in definition.steps:
            if isinstance(step, DocumentStep):
                needed.setdefault(DOCUMENT_CAPABILITY, []).append(step.key)
            elif isinstance(step, FunctionStep):
                needed.setdefault(step.purpose, []).append(step.key)
        for purpose, keys in needed.items():
            if space.is_personal() or purpose in space.enabled_capabilities:
                continue
            problems.append(
                f"the {purpose} function is not enabled in this space, which "
                f"step(s) {', '.join(keys)} need; enable it in the space settings"
            )
        for step in definition.steps:
            if not isinstance(step, TranscribeStep):
                continue
            if (
                step.transcription_model_id is None
                and space.get_default_transcription_model() is None
            ):
                problems.append(
                    f"step '{step.key}' needs a transcription model, but the space "
                    "has none enabled"
                )
            if step.speaker_labels and configured_speaker_service() is None:
                problems.append(
                    f"step '{step.key}' asks for speaker labels, but no speaker "
                    "service is configured for this Eneo (FLOW_SPEAKER_SERVICE_URL)"
                )
        return problems

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

    async def execution_bindings(
        self,
        definition: FlowDefinition,
        space: Space,
        expected: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from eneo.flows.execution_bindings import bind_execution

        return await bind_execution(definition, space, self.assistant_service, expected)

    async def _to_public(self, flow: Flows) -> FlowPublic:
        revisions = await self.repo.recent_revisions(flow.id, limit=STEP_ORIGIN_WINDOW)
        sessions = await self.repo.edit_sessions(flow.id)
        return flow_public(
            flow,
            has_unpublished_changes=await self._has_unpublished_changes(flow),
            revision=revisions[0].revision if revisions else 0,
            editing=any(row.user_id == self.user.id for row in sessions),
            editors=[
                FlowEditorPublic(
                    user_id=row.user_id,
                    username=row.username,
                    started_at=row.started_at,
                )
                for row in sessions
                if row.user_id != self.user.id
            ],
            step_origins=step_origins(flow.definition, revisions),
        )

    # --- Edit mode ---

    async def enter_edit_mode(self, flow_id: UUID) -> FlowPublic:
        """Start (or keep) the caller's edit mode on the flow.

        Anyone who may edit flows in the space may enter, also while others
        are editing: the revisions make concurrent changes visible and
        restorable, so there is no lock.
        """
        flow = await self._require_flow(flow_id)
        await self.authorize_space(flow.space_id, "edit")
        await self.repo.start_edit_session(flow.id, self.user.id)
        return await self._to_public(flow)

    async def leave_edit_mode(self, flow_id: UUID) -> FlowPublic:
        """End the caller's edit mode; nothing is saved (every change already
        is a revision) and leaving twice is fine."""
        flow = await self._require_flow(flow_id)
        await self.authorize_space(flow.space_id)
        await self.repo.end_edit_session(flow.id, self.user.id)
        return await self._to_public(flow)

    async def require_editing(self, flow: UUID | Flows) -> Flows:
        """The flow, provided the caller may edit it and is in edit mode on it.

        Every change from the panel and from the chat's write tools goes
        through here, so a flow a person is only viewing stays as it is.
        """
        row = flow if not isinstance(flow, UUID) else await self._require_flow(flow)
        await self.authorize_space(row.space_id, "edit")
        if not await self.repo.is_editing(row.id, self.user.id):
            raise FlowNotEditingException()
        return row

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
        self,
        flow_id: UUID,
        revision: int,
        *,
        channel: str = "api",
        expected_revision: int | None = None,
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
            expected_revision=expected_revision,
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
        problems = await self._template_problems(None, definition)
        if problems:
            raise FlowDefinitionProblemsException(problems)
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
        await self._sync_template_files(flow.id, definition)
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
        expected_revision: int | None = None,
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
        flow = await self._lock_revision(flow_id, expected_revision)
        if conversation_id is not None and flow.conversation_id is None:
            await self.repo.set_conversation_id(flow.id, conversation_id)
        definition_json: Optional[dict[str, Any]] = None
        if definition is not None:
            self._validate(definition, space)
            problems = await self._template_problems(flow.id, definition)
            if problems:
                raise FlowDefinitionProblemsException(problems)
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
        if definition is not None:
            await self._sync_template_files(flow.id, definition)
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
        operator = await self.can_operate_runs(space_id)
        rows = await self.repo.list_flows(
            space_id,
            self.user.tenant_id,
            principal_service_id=self.service_key_id,
            principal_user_id=self.user.id
            if not operator and self.service_key_id is None
            else None,
        )
        if self.service_key_id is not None:
            rows = [row for row in rows if row.flow.published_version is not None]
        return [flow_sparse_public(row.flow, row.last_run) for row in rows]

    async def publish_flow(
        self,
        flow_id: UUID,
        channel: str = "api",
        *,
        expected_revision: int | None = None,
    ) -> FlowPublic:
        """Freeze the draft as the next version; runs execute that snapshot."""
        flow = await self._require_flow(flow_id)
        space = await self.authorize_space(flow.space_id, "publish")
        flow = await self._lock_revision(flow_id, expected_revision)
        definition = definition_from_json(flow.definition)
        await self._require_runnable(flow, definition, space, action="published")
        bindings = await self.execution_bindings(definition, space)
        if flow.published_version is not None:
            current = await self.repo.get_version(flow.id, flow.published_version)
            if (
                current is not None
                and current.definition == flow.definition
                and current.runtime_bindings == bindings
            ):
                return await self._to_public(flow)
        version = await self.repo.next_version_number(flow.id)
        await self.repo.add_version(
            flow_id=flow.id,
            version=version,
            definition=flow.definition,
            runtime_bindings=bindings,
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

    async def unpublish_flow(
        self, flow_id: UUID, *, expected_revision: int
    ) -> FlowPublic:
        flow = await self._require_flow(flow_id)
        await self.authorize_space(flow.space_id, "publish")
        flow = await self._lock_revision(flow_id, expected_revision)
        if flow.published_version is not None:
            await self.repo.unpublish_flow(flow.id, self.user.tenant_id)
            await self._audit(
                ActionType.FLOW_UNPUBLISHED, flow, "Unpublished flow", channel="api"
            )
        return await self._to_public(await self._require_flow(flow.id))

    async def _require_runnable(
        self, flow: Flows, definition: FlowDefinition, space: Space, *, action: str
    ) -> None:
        """What a run needs beyond a valid shape: steps, runnable kinds, the
        template files and the document capability. Shared by publishing and
        test runs, so a draft that runs is a draft that can be published."""
        if not definition.steps:
            raise BadRequestException(f"a flow needs at least one step to be {action}")
        self._validate(definition, space)
        unavailable = self._unavailable_kinds(definition)
        if unavailable:
            raise BadRequestException(
                "This version of Eneo cannot run transcribe steps yet, so the "
                f"flow cannot be {action}: "
                + "; ".join(unavailable)
                + ". Replace them with llm, compose, document or review steps for now."
            )
        problems = await self._template_problems(flow.id, definition)
        problems.extend(self._document_capability_problems(definition, space))
        if problems:
            raise FlowDefinitionProblemsException(
                problems, lead=f"The flow cannot be {action}:"
            )

    async def get_runnable_draft(self, flow_id: UUID) -> FlowDefinition:
        """The draft as a test run executes it; needs edit rights and a draft
        that could be published as it is."""
        flow = await self._require_flow(flow_id)
        space = await self.authorize_space(flow.space_id, "edit")
        definition = definition_from_json(flow.definition)
        await self._require_runnable(flow, definition, space, action="test run")
        return definition

    async def delete_flow(self, flow_id: UUID, channel: str = "api") -> None:
        flow = await self._require_flow(flow_id)
        await self.authorize_space(flow.space_id, "delete")
        await self._lock_revision(flow_id, None)
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

    # --- Published runtime view (API consumers) ---

    async def get_published_runtime(self, flow_id: UUID) -> FlowRuntimePublic:
        """The flow's metadata and every run-side path, for a published flow."""
        flow = await self._require_flow(flow_id)
        await self.authorize_space(flow.space_id)
        if flow.published_version is None:
            raise NotFoundException("Published flow not found")
        return FlowRuntimePublic(
            id=flow.id,
            space_id=flow.space_id,
            name=flow.name,
            description=flow.description,
            published_version=flow.published_version,
            created_at=flow.created_at,
            updated_at=flow.updated_at,
            runtime_paths=build_flow_runtime_paths(
                flow.id, api_prefix=get_settings().api_prefix
            ),
        )

    # --- Runtime files (uploads a run is given) ---

    async def add_runtime_file(
        self, flow_id: UUID, upload: UploadFile, *, channel: str = "api"
    ) -> FilePublic:
        """Keep an upload for a run of this flow; the run request binds it to
        a file form field by id. Anyone who may run the flow may upload."""
        async with self._transaction():
            flow = await self._require_flow(flow_id)
            await self.authorize_space(flow.space_id)
            if flow.published_version is None:
                raise BadRequestException(
                    "Flow must be published before runtime files can be uploaded."
                )
            # The commit expires the row; keep what the audit entry needs.
            flow_name = flow.name
            service_id = self.service_key_id
            # A service principal owns no rows: its upload is the author's file.
            file_service = (
                self.file_service.as_user(await self.flow_author(flow))
                if service_id is not None
                else self.file_service
            )
        # The upload manages its own transactions (an object-store write
        # cannot happen inside one).
        file = await file_service.save_file(upload)
        async with self._transaction():
            await self.repo.add_flow_file(
                flow_id=flow_id,
                file_id=file.id,
                role=RUNTIME_UPLOAD_ROLE,
                principal_type=(
                    PrincipalType.SERVICE.value
                    if service_id is not None
                    else PrincipalType.USER.value
                ),
                principal_user_id=None if service_id is not None else self.user.id,
                principal_service_id=service_id,
            )
            await self.audit_service.log_async(
                tenant_id=self.user.tenant_id,
                user=self.user,
                action=ActionType.FILE_UPLOADED,
                entity_type=EntityType.FILE,
                entity_id=file.id,
                description=f"Uploaded runtime file '{file.name}' for flow '{flow_name}'",
                metadata=AuditMetadata.standard(
                    actor=self.user,
                    target=file,
                    extra={
                        "channel": channel,
                        "flow_id": str(flow_id),
                        "size_bytes": file.size,
                        "mimetype": file.mimetype,
                    },
                ),
            )
            return await file_service.get_public_file_by_id(file.id)

    async def delete_runtime_file(
        self, flow_id: UUID, file_id: UUID, *, channel: str = "api"
    ) -> None:
        """Remove an upload no run has used (409 once a run took it as input)."""
        flow = await self._require_flow(flow_id)
        await self.authorize_space(flow.space_id)
        row = await self.repo.get_flow_file(flow.id, file_id, role=RUNTIME_UPLOAD_ROLE)
        if row is None:
            raise NotFoundException("Runtime file not found for this flow")
        service_id = self.service_key_id
        if service_id is not None and row.principal_service_id != service_id:
            raise NotFoundException("Runtime file not found for this flow")
        if await self.repo.file_used_by_runs(file_id):
            raise FlowRuntimeFileInUseException(
                "The file was given to a run and stays with it."
            )
        await self.repo.delete_flow_file(flow.id, file_id, role=RUNTIME_UPLOAD_ROLE)
        file_service = (
            self.file_service.as_user(await self.flow_author(flow))
            if service_id is not None
            else self.file_service
        )
        file = await file_service.delete_file(file_id)
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.FILE_DELETED,
            entity_type=EntityType.FILE,
            entity_id=file_id,
            description=f"Deleted runtime file '{file.name}' of flow '{flow.name}'",
            metadata=AuditMetadata.standard(
                actor=self.user,
                target=file,
                extra={"channel": channel, "flow_id": str(flow.id)},
            ),
        )
