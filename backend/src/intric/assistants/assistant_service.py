import re
from collections.abc import AsyncGenerator, Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Optional, TypeVar, Union, cast
from uuid import UUID

from intric.ai_models.completion_models.completion_model import (
    Completion,
    ModelKwargs,
    ResponseType,
    TokenUsage,
)
from intric.assistants.api.assistant_models import AssistantResponse
from intric.assistants.assistant import Assistant
from intric.assistants.assistant_factory import AssistantFactory
from intric.assistants.assistant_repo import AssistantRepository
from intric.authentication.api_key_scope_revoker import ApiKeyScopeRevoker
from intric.authentication.auth_models import ApiKeyScopeType, ApiKeyStateReasonCode
from intric.authentication.auth_service import AuthService
from intric.completion_models.infrastructure.context_builder import count_tokens
from intric.completion_models.infrastructure.web_search import WebSearch
from intric.files.file_service import FileService
from intric.governance_policy.domain.policy_resolver import (
    select_effective_completion_model,
)
from intric.help_assistants.application.ask_guard import assert_not_helper_assistant
from intric.help_assistants.infrastructure.help_assistant_assignment_history_repo import (  # noqa: E501
    HelpAssistantAssignmentHistoryRepo,
)
from intric.help_assistants.infrastructure.org_space_assistant_role_repo import (
    OrgSpaceAssistantRoleRepo,
)
from intric.icons.icon_repo import IconRepository
from intric.logging.logging import LoggingDetails
from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from intric.main.logging import get_logger
from intric.main.models import (
    NOT_PROVIDED,
    NotProvided,
    ResourcePermission,
    is_provided,
)
from intric.prompts.api.prompt_models import PromptCreate
from intric.prompts.prompt import Prompt
from intric.prompts.prompt_service import PromptService
from intric.questions.question import ToolAssistant, ToolCallInfo, UseTools
from intric.roles.permissions import (
    Permission,
    validate_permission,
    validate_permissions,
)
from intric.services.service import DatastoreResult
from intric.services.service_repo import ServiceRepository
from intric.spaces.api.space_models import WizardType
from intric.spaces.space_service import SpaceService
from intric.templates.assistant_template.assistant_template_service import (
    AssistantTemplateService,
)
from intric.users.user import UserInDB
from intric.workflows.step_repo import StepRepository

logger = get_logger(__name__)

if TYPE_CHECKING:
    from intric.actors import ActorManager
    from intric.ai_models.completion_models.completion_model import (
        CompletionModel as AICompletionModel,
    )
    from intric.ai_models.completion_models.completion_model import (
        CompletionModelPublic,
        CompletionModelResponse,
    )
    from intric.assistants.references import ReferencesService
    from intric.completion_models.application import CompletionModelCRUDService
    from intric.completion_models.domain.completion_model import CompletionModel
    from intric.completion_models.infrastructure.completion_service import (
        CompletionService,
    )
    from intric.completion_models.infrastructure.web_search import (
        WebSearchResult,
    )
    from intric.files.file_models import File
    from intric.governance_policy.application.effective_config_service import (
        EffectiveConfigService,
    )
    from intric.governance_policy.domain.policy_resolver import EffectiveConfig
    from intric.integration.domain.repositories.integration_knowledge_repo import (
        IntegrationKnowledgeRepository,
    )
    from intric.mcp_servers.domain.entities.mcp_server import MCPServer
    from intric.sessions.session import SessionInDB
    from intric.sessions.session_service import SessionService
    from intric.spaces.api.space_models import TemplateCreate
    from intric.spaces.space import Space
    from intric.spaces.space_repo import SpaceRepository

logger = get_logger(__name__)

AT_TAG_PATTERN = r"<intric-at-tag: @[^>]+>"
REFERENCE_PATTERN = r'<inref id="([0-9a-f]{8})"/>'  # noqa


def clean_intric_tag(input_string: str) -> str:
    return re.sub(AT_TAG_PATTERN, "", input_string)


TReference = TypeVar("TReference")


def get_references(
    response_string: str,
    info_blobs: Sequence[TReference],
    version: int = 1,
    get_id_func: Callable[[TReference], object] | None = None,
) -> list[TReference]:
    if version == 1:
        return list(info_blobs)

    # Preserve order, remove duplicates
    info_blob_ids = list(dict.fromkeys(re.findall(REFERENCE_PATTERN, response_string)))

    if get_id_func is None:

        def _default_get_id_func(blob: object) -> object:
            return getattr(blob, "id", getattr(blob, "info_blob_id", None))

        get_id_func = _default_get_id_func

    def _get_blob(blob_id: str):
        return next(
            (blob for blob in info_blobs if str(get_id_func(blob))[:8] == blob_id), None
        )

    blobs = [_get_blob(blob_id) for blob_id in info_blob_ids]

    return [blob for blob in blobs if blob is not None]


class AssistantService:
    def __init__(
        self,
        repo: AssistantRepository,
        space_repo: "SpaceRepository",
        user: UserInDB,
        auth_service: AuthService,
        service_repo: ServiceRepository,
        step_repo: StepRepository,
        completion_model_crud_service: "CompletionModelCRUDService",
        space_service: SpaceService,
        factory: AssistantFactory,
        prompt_service: PromptService,
        file_service: FileService,
        assistant_template_service: AssistantTemplateService,
        session_service: "SessionService",
        actor_manager: "ActorManager",
        integration_knowledge_repo: "IntegrationKnowledgeRepository",
        completion_service: "CompletionService",
        references_service: "ReferencesService",
        icon_repo: IconRepository,
        org_space_assistant_role_repo: OrgSpaceAssistantRoleRepo,
        help_assistant_assignment_history_repo: HelpAssistantAssignmentHistoryRepo,
        api_key_scope_revoker: ApiKeyScopeRevoker | None = None,
        effective_config_service: "EffectiveConfigService | None" = None,
    ):
        super().__init__()
        self.repo = repo
        self.space_repo = space_repo
        self.factory = factory
        self.user = user
        self.auth_service = auth_service
        self.service_repo = service_repo
        self.step_repo = step_repo
        self.completion_model_crud_service = completion_model_crud_service
        self.space_service = space_service
        self.prompt_service = prompt_service
        self.file_service = file_service
        self.assistant_template_service = assistant_template_service
        self.session_service = session_service
        self.actor_manager = actor_manager
        self.integration_knowledge_repo = integration_knowledge_repo
        self.completion_service = completion_service
        self.references_service = references_service
        self.icon_repo = icon_repo
        self.org_space_assistant_role_repo = org_space_assistant_role_repo
        self.help_assistant_assignment_history_repo = (
            help_assistant_assignment_history_repo
        )
        self.api_key_scope_revoker = api_key_scope_revoker
        self.effective_config_service = effective_config_service

    @property
    async def web_search(self):
        return WebSearch()

    def validate_space_assistant(
        self,
        space: "Space",
        assistant: Assistant,
        completion_model_changing: bool = True,
        knowledge_changing: bool = True,
    ):
        # validate completion model only if it was actually updated
        if completion_model_changing and assistant.completion_model is not None:
            if not space.is_completion_model_in_space(assistant.completion_model.id):
                raise BadRequestException("Completion model is not in space.")

        # validate groups and websites only if knowledge is changing
        if knowledge_changing:
            for group in assistant.collections:
                if not space.is_group_in_space(group.id):
                    raise BadRequestException("Group is not in space.")

            for website in assistant.websites:
                if not space.is_website_in_space(website.id):
                    raise BadRequestException("Website is not in space.")

        for integration_knowledge in assistant.integration_knowledge_list:
            if not space.is_integration_knowledge_in_space(
                integration_knowledge_id=integration_knowledge.id
            ):
                raise BadRequestException("Invalid integration knowledge")

    async def _resolve_effective_config(
        self, *, space: "Space", assistant: Assistant
    ) -> "EffectiveConfig | None":
        if (
            self.effective_config_service is None
            or not assistant.is_default
            or not space.is_personal()
        ):
            return None
        return await self.effective_config_service.resolve_for(
            assistant, space_is_personal=space.is_personal()
        )

    async def _ensure_governance_policy_allows_update(
        self,
        *,
        space: "Space",
        assistant: Assistant,
        completion_model_id: UUID | None,
        mcp_server_ids: list[UUID] | None,
        prompt_changing: bool = False,
        effective_config: "EffectiveConfig | None | NotProvided" = NOT_PROVIDED,
    ) -> None:
        # Nothing to validate → skip resolving the policy (and its DB round-trip).
        if (
            completion_model_id is None
            and mcp_server_ids is None
            and not prompt_changing
        ):
            return

        # _resolve_effective_config owns the is_default / personal-space / no-service
        # short-circuits and returns None when the policy does not apply. Callers
        # that already resolved it pass it in to avoid a second round-trip.
        if isinstance(effective_config, NotProvided):
            effective_config = await self._resolve_effective_config(
                space=space, assistant=assistant
            )
        if effective_config is None:
            return

        if prompt_changing and effective_config.prompt_enforced:
            raise BadRequestException(
                "Prompt is locked by personal assistant governance policy",
            )

        if completion_model_id is not None and effective_config.models_enforced:
            current_model_id = (
                assistant.completion_model.id
                if assistant.completion_model is not None
                else None
            )
            if completion_model_id != current_model_id:
                allowed_ids = {m.id for m in effective_config.available_models}
                if completion_model_id not in allowed_ids:
                    raise BadRequestException(
                        "Model not allowed by personal assistant governance policy",
                    )

        if mcp_server_ids is not None and effective_config.mcp_enforced:
            allowed_ids = {s.id for s in effective_config.available_mcp_servers}
            # Grandfather servers already attached: only newly-added servers
            # must satisfy the policy, mirroring the completion-model rule
            # above. This lets an admin tighten the whitelist without blocking
            # re-saves of assistants that still reference a now-disallowed
            # server.
            current_ids = {s.id for s in assistant.mcp_servers}
            disallowed = (set(mcp_server_ids) - current_ids) - allowed_ids
            if disallowed:
                raise BadRequestException(
                    "MCP servers not allowed by personal assistant governance policy",
                )

    async def _ensure_governance_policy_allows_mcp_server(
        self, *, space: "Space", assistant: Assistant, mcp_server_id: UUID
    ) -> None:
        await self._ensure_governance_policy_allows_update(
            space=space,
            assistant=assistant,
            completion_model_id=None,
            mcp_server_ids=[mcp_server_id],
        )

    async def create_assistant(
        self,
        name: str,
        space_id: UUID,
        template_data: Optional["TemplateCreate"] = None,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        space = await self.space_service.get_space(space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_create_assistants():
            raise UnauthorizedException(
                "User does not have permission to create assistants in this space"
            )

        completion_model = await self.get_completion_model(space=space)
        assert space.id is not None

        if not template_data:
            assistant = self.factory.create_assistant(
                name=name,
                user=self.user,
                space_id=space.id,
                completion_model=completion_model,
            )

            space.add_assistant(assistant)
            refreshed_space = await self.space_repo.update(space)
            assistant = refreshed_space.get_assistant(assistant.id)

        else:
            assistant = await self._create_from_template(
                space=space,
                template_data=template_data,
                completion_model=completion_model,
                name=name,
            )

        # TODO: Review how we get the permissions to the presentation layer
        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )

        return assistant, permissions  # type: ignore[return-value]

    async def _create_from_template(
        self,
        space: "Space",
        template_data: "TemplateCreate",
        completion_model: Optional["CompletionModel"],
        name: str | None = None,
    ):
        template = await self.assistant_template_service.get_assistant_template(
            assistant_template_id=template_data.id
        )

        if (
            template.completion_model
            and template.completion_model.id
            and space.is_completion_model_available(template.completion_model.id)
        ):
            completion_model = space.get_completion_model(template.completion_model.id)

        # Validate incoming data
        template.validate_assistant_wizard_data(template_data=template_data)
        assert space.id is not None

        attachments = await self.file_service.get_files_by_ids(
            file_ids=template_data.get_ids_by_type(wizard_type=WizardType.attachments)
        )
        collections = [
            space.get_collection(collection_id=group_id)
            for group_id in template_data.get_ids_by_type(wizard_type=WizardType.groups)
        ]

        prompt = None
        if template.prompt_text:
            prompt = await self.prompt_service.create_prompt(text=template.prompt_text)

        template_kwargs: dict[str, object] = cast(
            dict[str, object], getattr(template, "completion_model_kwargs", {})
        )

        assistant = self.factory.create_assistant(
            name=name or template.name,
            user=self.user,
            space_id=space.id,
            prompt=prompt,
            completion_model=completion_model,
            completion_model_kwargs=ModelKwargs.model_validate(template_kwargs),
            attachments=attachments,
            collections=collections,
            template=template,
            description=template.description,
        )

        space.add_assistant(assistant)
        refreshed_space = await self.space_repo.update(space)
        assistant = refreshed_space.get_assistant(assistant.id)

        return assistant

    async def get_completion_model(self, space: "Space") -> Optional["CompletionModel"]:
        """Get a completion model for the space. Returns None if no model is available."""
        model = space.get_default_completion_model()
        if model:
            return model  # type: ignore[return-value]

        if space.completion_models:
            try:
                model = space.get_latest_completion_model()
                if model:
                    return model  # type: ignore[return-value]
            except Exception:
                pass

        # Try to get tenant default model
        return await self.completion_model_crud_service.get_default_completion_model()  # type: ignore[return-value]

    async def create_default_assistant(self, name: str, space: "Space"):
        cm = space.get_default_completion_model()
        assert space.id is not None

        if cm and not space.is_completion_model_in_space(cm.id):
            space.add_completion_model(cm)
            await self.space_repo.update(space)

        return self.factory.create_assistant(
            name=name,
            user=self.user,
            space_id=space.id,
            completion_model=cm,
            is_default=True,
        )

    async def update_assistant(
        self,
        assistant_id: UUID,
        name: str | None = None,
        prompt: PromptCreate | None = None,
        completion_model_id: UUID | None = None,
        completion_model_kwargs: ModelKwargs | None = None,
        logging_enabled: bool | None = None,
        groups: list[UUID] | None = None,
        websites: list[UUID] | None = None,
        integration_knowledge_ids: list[UUID] | None = None,
        mcp_server_ids: list[UUID] | None = None,
        mcp_tools: list[tuple[UUID, bool]] | None = None,
        attachment_ids: list[UUID] | None = None,
        description: Union[str, None, NotProvided] = NOT_PROVIDED,
        insight_enabled: Optional[bool] = None,
        data_retention_days: Union[int, None, NotProvided] = NOT_PROVIDED,
        metadata_json: Union[dict[str, object], None, NotProvided] = NOT_PROVIDED,
        icon_id: Union[UUID, None, NotProvided] = NOT_PROVIDED,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        if logging_enabled:
            validate_permission(self.user, Permission.ADMIN)

        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        # Check if user has permission to toggle insights
        if insight_enabled is not None:
            if not actor.can_toggle_insight():
                raise UnauthorizedException("Only admins can toggle insights")

        assistant = space.get_assistant(assistant_id=assistant_id)

        # Access to the personal default assistant requires PERSONAL_CHAT.
        # That permission permits model selection only; broader configuration
        # changes additionally require ASSISTANTS below.
        is_personal_default = (
            space.is_personal()
            and space.default_assistant is not None
            and assistant.id == space.default_assistant.id
        )

        can_edit_default = (
            actor.can_edit_default_assistant() if is_personal_default else False
        )
        can_edit_assistants = actor.can_edit_assistants()
        if not (can_edit_default if is_personal_default else can_edit_assistants):
            raise UnauthorizedException(
                "You do not have permission to edit assistants in this space.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "update",
                    "auth_layer": "domain_policy",
                },
            )

        extended_update_requested = any(
            value is not None
            for value in (
                name,
                prompt,
                completion_model_kwargs,
                logging_enabled,
                groups,
                websites,
                integration_knowledge_ids,
                mcp_server_ids,
                mcp_tools,
                attachment_ids,
                insight_enabled,
            )
        ) or any(
            is_provided(value)
            for value in (
                description,
                data_retention_days,
                metadata_json,
                icon_id,
            )
        )
        if (
            is_personal_default
            and extended_update_requested
            and not can_edit_assistants
        ):
            raise UnauthorizedException(
                "The personal_chat permission only allows changing the "
                "personal assistant's completion model.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "update",
                    "auth_layer": "domain_policy",
                },
            )

        update_effective_config: "EffectiveConfig | None | NotProvided" = NOT_PROVIDED
        if prompt is not None:
            update_effective_config = await self._resolve_effective_config(
                space=space, assistant=assistant
            )
            await self._ensure_governance_policy_allows_update(
                space=space,
                assistant=assistant,
                completion_model_id=None,
                mcp_server_ids=None,
                prompt_changing=True,
                effective_config=update_effective_config,
            )

        prompt_obj: Prompt | None = None
        if prompt is not None:
            # When the update carries a `prompt` field, persist it — empty
            # text included. An empty string is a deliberate "clear the
            # prompt" action by the user (they emptied the textarea on
            # purpose), not a missing field; the outer ``prompt is not
            # None`` check above already distinguishes "this update does
            # not touch the prompt" from "set the prompt to X". Treating
            # ``""`` as falsy here silently kept the previous prompt and
            # reverted the user's clear-and-save.
            #
            # Attribute the prompt to the assistant's owner, not the
            # caller. Keeps service-key edits FK-safe (synthetic id has
            # no `users` row) and makes admin edits to others'
            # assistants attribute correctly.
            prompt_owner_id = (
                assistant.user.id if assistant.user is not None else self.user.id
            )
            prompt_obj = await self.prompt_service.create_prompt(
                prompt.text,
                prompt.description,
                owner_user_id=prompt_owner_id,
            )

        completion_model = None
        if completion_model_id is not None:
            if not space.is_completion_model_available(completion_model_id):
                raise BadRequestException(
                    "The completion model is not enabled in the space."
                )
            completion_model = space.get_completion_model(completion_model_id)

        attachments = None
        if attachment_ids is not None:
            attachments = await self.file_service.get_files_by_ids(attachment_ids)

        group_entities = None
        if groups is not None:
            group_entities = [
                space.get_collection(collection_id=group_id) for group_id in groups
            ]

        website_entities = None
        if websites is not None:
            website_entities = [
                space.get_website(website_id=website_id) for website_id in websites
            ]

        integration_knowledge_list = None
        if integration_knowledge_ids is not None:
            integration_knowledge_list = [
                space.get_integration_knowledge(
                    integration_knowledge_id=integration_knowledge_id
                )
                for integration_knowledge_id in integration_knowledge_ids
            ]

        # Validate MCP server assignments against tenant + space boundaries.
        mcp_effective_config: "EffectiveConfig | None | NotProvided" = (
            update_effective_config
        )
        if mcp_server_ids is not None:
            import sqlalchemy as sa

            from intric.database.tables.mcp_server_table import (
                MCPServers as MCPServersTable,
            )
            from intric.database.tables.mcp_server_table import (
                SpacesMCPServers as SpacesMCPServersTable,
            )

            mcp_servers_query = (
                sa.select(MCPServersTable.id)
                .where(MCPServersTable.tenant_id == self.user.tenant_id)
                .where(MCPServersTable.is_enabled == True)  # noqa: E712
                .where(MCPServersTable.id.in_(mcp_server_ids))
            )
            mcp_servers_result = await self.repo.session.execute(mcp_servers_query)
            enabled_server_ids = {row[0] for row in mcp_servers_result.fetchall()}

            missing_tenant_enabled_ids = [
                str(server_id)
                for server_id in mcp_server_ids
                if server_id not in enabled_server_ids
            ]
            if missing_tenant_enabled_ids:
                raise BadRequestException(
                    "MCP server(s) are not enabled for this tenant: "
                    + ", ".join(missing_tenant_enabled_ids)
                )

            # For a personal default assistant under an active MCP policy, the
            # governance whitelist (enforced just below) is the source of truth.
            # Personal spaces are seeded with tenant MCP servers only at creation
            # time and are not back-filled when a server is enabled later, so the
            # space-assignment check would wrongly reject a policy-allowed server.
            if isinstance(mcp_effective_config, NotProvided):
                mcp_effective_config = await self._resolve_effective_config(
                    space=space, assistant=assistant
                )
            mcp_governed = (
                mcp_effective_config is not None and mcp_effective_config.mcp_enforced
            )
            if not mcp_governed:
                space_servers_query = sa.select(
                    SpacesMCPServersTable.mcp_server_id
                ).where(
                    SpacesMCPServersTable.space_id == space.id,
                    SpacesMCPServersTable.mcp_server_id.in_(mcp_server_ids),
                )
                space_servers_result = await self.repo.session.execute(
                    space_servers_query
                )
                space_server_ids = {row[0] for row in space_servers_result.fetchall()}
                missing_space_ids = [
                    str(server_id)
                    for server_id in mcp_server_ids
                    if server_id not in space_server_ids
                ]
                if missing_space_ids:
                    raise BadRequestException(
                        "MCP server(s) are not assigned to this assistant's space: "
                        + ", ".join(missing_space_ids)
                    )

        await self._ensure_governance_policy_allows_update(
            space=space,
            assistant=assistant,
            completion_model_id=completion_model_id,
            mcp_server_ids=mcp_server_ids,
            prompt_changing=False,
            effective_config=mcp_effective_config,
        )

        # Store MCP server IDs and tool settings for repository to handle.
        setattr(assistant, "_mcp_server_ids", mcp_server_ids)
        setattr(assistant, "_mcp_tool_settings", mcp_tools)

        assistant.update(
            name=name,
            prompt=prompt_obj,
            completion_model=completion_model,
            completion_model_kwargs=completion_model_kwargs,
            attachments=attachments,
            logging_enabled=logging_enabled,
            collections=group_entities,
            websites=website_entities,
            integration_knowledge_list=integration_knowledge_list,
            description=description,
            insight_enabled=insight_enabled,
            data_retention_days=data_retention_days,
            metadata_json=metadata_json,
            icon_id=icon_id,
        )

        # Validate mutual exclusivity: knowledge and MCP servers cannot both be active.
        # Only check when either side is being updated to avoid false positives on
        # unrelated updates (e.g. renaming an assistant).
        knowledge_changing = (
            groups is not None
            or websites is not None
            or integration_knowledge_ids is not None
        )
        mcp_changing = mcp_server_ids is not None
        if knowledge_changing or mcp_changing:
            will_have_mcp = (
                mcp_server_ids is not None and len(mcp_server_ids) > 0
            ) or (mcp_server_ids is None and assistant.has_mcp())
            if assistant.has_knowledge() and will_have_mcp:
                raise BadRequestException(
                    "Knowledge and MCP servers cannot both be active on an assistant. "
                    "Remove one before enabling the other."
                )

        # Only validate space references when the relevant fields are actually changing
        self.validate_space_assistant(
            space=space,
            assistant=assistant,
            completion_model_changing=completion_model is not None,
            knowledge_changing=knowledge_changing,
        )

        refreshed_space = await self.space_repo.update(space)
        assistant = refreshed_space.get_assistant(assistant_id=assistant_id)

        # TODO: Review how we get the permissions to the presentation layer
        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )

        return assistant, permissions

    def _authorize_read_assistant(self, space: "Space", assistant: Assistant) -> None:
        """Enforce read authorization for an assistant in a space.

        The personal chat is the personal space's default assistant — it is
        gated by PERSONAL_CHAT (via can_read_default_assistant), not ASSISTANTS,
        so a baseline role can use the chat without managing assistants. Every
        read path (get_assistant, the effective-config serialization, and the
        preflight model resolution) must apply this same carve-out, or the exact
        users this feature targets get a spurious 403.
        """
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        is_personal_default = (
            space.is_personal()
            and space.default_assistant is not None
            and assistant.id == space.default_assistant.id
        )
        can_read = (
            actor.can_read_default_assistant()
            if is_personal_default
            else actor.can_read_assistants()
        )
        if not can_read:
            raise UnauthorizedException(
                "You do not have permission to read assistants in this space.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "read",
                    "auth_layer": "domain_policy",
                },
            )

    async def get_assistant(
        self, assistant_id: UUID
    ) -> tuple[Assistant, list[ResourcePermission]]:
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        self._authorize_read_assistant(space=space, assistant=assistant)

        # TODO: Review how we get the permissions to the presentation layer
        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )

        return assistant, permissions  # type: ignore[return-value]

    async def get_assistant_with_effective_config(
        self, assistant_id: UUID
    ) -> tuple[Assistant, list[ResourcePermission], "EffectiveConfig | None"]:
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        self._authorize_read_assistant(space=space, assistant=assistant)

        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )
        effective_config = await self._resolve_effective_config(
            space=space, assistant=assistant
        )

        return assistant, permissions, effective_config

    async def get_effective_completion_model(
        self, assistant_id: UUID
    ) -> "CompletionModel | None":
        """The model that will actually answer for this assistant, honoring a
        personal-assistant models policy.

        Mirrors the resolution `ask()` applies so read-time preflight and
        ask-time enforcement never disagree about which model a request uses.
        """
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        # Preflight is reachable with an arbitrary assistant_id; enforce the same
        # read authorization get_assistant() applies so it can't probe assistants
        # the caller cannot access.
        self._authorize_read_assistant(space=space, assistant=assistant)
        effective_config = await self._resolve_effective_config(
            space=space, assistant=assistant
        )
        return select_effective_completion_model(
            current_model=assistant.completion_model,
            effective_config=effective_config,
        )

    async def is_help_assistant(self, assistant_id: UUID) -> bool:
        """Whether ``assistant_id`` currently fills a Help Assistant role.

        True iff an active row in ``org_space_assistant_roles`` points at it.
        The single-assistant GET endpoint surfaces this so the edit UI can
        explain why logging is permanently disabled on helpers (PRD §6, §9).
        Mirrors the "active" half of the ``assert_not_helper_assistant`` guard.
        """
        return await self.org_space_assistant_role_repo.exists_active_for_assistant(
            assistant_id
        )

    async def get_help_assistant(self, assistant_id: UUID) -> Assistant:
        """Load a Help Assistant by id, bypassing the space-actor read gate.

        Help Assistants live in the org-space, whose only members are the
        tenant admins added by ``SpaceService.ensure_org_admin_members`` —
        regular users are never org-space members and therefore cannot pass
        the ``actor.can_read_assistants()`` check in :meth:`get_assistant`.
        But the Prompt Guide is, by design (PRD §5/§6/§10), usable by *any*
        authenticated user who has ``EDIT`` rights on the *target* assistant:
        their authorization is governed by those target-edit rights plus the
        role's ``is_enabled`` / ``is_visible_to_users`` flags — all enforced
        by the caller — **not** by org-space membership.

        This loads the assistant exactly as :meth:`get_assistant` does, minus
        the org-space read gate. To keep the bypass narrow — only the assistant
        *designated by a help-assistant role* is readable this way, never an
        arbitrary org-space assistant — it first asserts the id currently
        fills, or formerly filled, a help-assistant role. Anything else raises
        :class:`NotFoundException`, so this can neither be used as a generic
        permission-skipping read nor to probe org-space assistants.

        Callers are :class:`HelperRunService` (``run`` / ``continue_turn``) and
        the availability endpoint, always with an id resolved server-side from
        an active ``OrgSpaceAssistantRole`` or an existing ``HelperRun`` — never
        a client-supplied assistant id. ``continue_turn`` may legitimately load
        a *former* helper (the role was reassigned mid-conversation), which is
        why the assignment-history branch counts.
        """
        is_active_helper = (
            await self.org_space_assistant_role_repo.exists_active_for_assistant(
                assistant_id
            )
        )
        is_former_helper = (
            await self.help_assistant_assignment_history_repo.exists_for_assistant(
                assistant_id
            )
        )
        if not (is_active_helper or is_former_helper):
            raise NotFoundException(
                "Assistant is not a help assistant; refusing privileged read."
            )

        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        return space.get_assistant(assistant_id=assistant_id)

    async def get_assistants(
        self,
        name: str | None = None,
        for_tenant: bool = False,
        space_id_filter: UUID | None = None,
        assistant_id_filter: UUID | None = None,
    ) -> list[Assistant]:
        if for_tenant:
            return await self.get_tenant_assistants(name)

        return await self.repo.get_for_user(
            self.user.id,
            search_query=name,
            space_id=space_id_filter,
            assistant_id=assistant_id_filter,
        )

    @validate_permissions(Permission.ADMIN)
    async def get_tenant_assistants(
        self,
        name: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[Assistant]:
        assistants = await self.repo.get_for_tenant(
            tenant_id=self.user.tenant_id,
            search_query=name,
            start_date=start_date,
            end_date=end_date,
        )
        return assistants

    async def delete_assistant(self, assistant_id: UUID):
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assert space.id is not None
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_delete_assistants():
            raise UnauthorizedException(
                "You do not have permission to delete assistants in this space.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "delete",
                    "auth_layer": "domain_policy",
                },
            )

        assistant = space.get_assistant(assistant_id=assistant_id)
        icon_id = assistant.icon_id

        if self.api_key_scope_revoker is not None:
            try:
                await self.api_key_scope_revoker.revoke_scope(
                    scope_type=ApiKeyScopeType.ASSISTANT,
                    scope_id=assistant_id,
                    reason_code=ApiKeyStateReasonCode.SCOPE_REMOVED,
                    reason_text="Assistant deleted",
                )
            except Exception:
                logger.exception(
                    "Failed to revoke API keys for deleted assistant",
                    extra={"assistant_id": str(assistant_id)},
                )

        space.remove_assistant(assistant)
        await self.space_repo.update(space)

        if icon_id:
            await self.icon_repo.delete(icon_id)

    @validate_permissions(Permission.ADMIN)
    async def generate_api_key(self, assistant_id: UUID):
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assert space.id is not None
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_edit_assistants():
            raise UnauthorizedException(
                "You do not have permission to manage assistant API keys.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "manage_api_keys",
                    "auth_layer": "domain_policy",
                },
            )

        return await self.auth_service.create_assistant_api_key(
            "ina", assistant_id=assistant_id
        )

    async def get_prompts_by_assistant(self, assistant_id: UUID) -> list[Prompt]:
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_prompts_of_assistants():
            raise UnauthorizedException(
                "You do not have permission to read prompts for this assistant.",
                code="forbidden_action",
                context={
                    "resource_type": "prompt",
                    "action": "read",
                    "auth_layer": "domain_policy",
                },
            )

        return await self.prompt_service.get_prompts_by_assistant(assistant_id)

    async def _handle_response(
        self,
        response: "CompletionModelResponse",
        datastore_result: "DatastoreResult",
        question: str,
        files: Sequence["File"],
        completion_model: "CompletionModel | CompletionModelPublic | None",
        session: "SessionInDB",
        stream: bool,
        assistant_id: UUID,
        question_id: UUID,
        version: int = 1,
        web_search_results: Sequence["WebSearchResult"] | None = None,
        assistant_selector_tokens: int = 0,
    ) -> str | AsyncGenerator[Completion, None]:
        # Capture tenant_id outside the generator so the abort-path background save
        # doesn't depend on self.user being safely accessible during teardown.
        tenant_id = self.user.tenant_id
        if stream:

            async def response_stream() -> AsyncGenerator[Completion, None]:
                reasoning_token_count = 0
                response_string = ""
                reasoning_string = ""
                generated_files: list[File] = []
                tool_calls: list[ToolCallInfo] = []
                stream_usage: TokenUsage | None = None
                completed = False

                try:
                    completion = response.completion
                    if isinstance(completion, str):
                        raise TypeError("Expected streaming completion response")

                    async for chunk in completion:
                        reasoning_token_count = chunk.reasoning_token_count
                        if chunk.usage:
                            stream_usage = chunk.usage

                        if chunk.response_type == ResponseType.TEXT:
                            response_string = f"{response_string}{chunk.text}"
                            chunk.reference_chunks = get_references(
                                response_string=response_string,
                                info_blobs=datastore_result.info_blobs,
                                version=version,
                            )
                            yield chunk

                        if chunk.response_type == ResponseType.REASONING:
                            # Reasoning/thinking text — pass through to SSE and
                            # accumulate separately so it can be persisted on the
                            # question without ever landing in the answer.
                            reasoning_string = (
                                f"{reasoning_string}{chunk.reasoning_content or ''}"
                            )
                            yield chunk

                        if chunk.response_type == ResponseType.FILES:
                            image_file = await self.file_service.save_image_from_bytes(
                                chunk.image_data
                            )

                            generated_files.append(image_file)
                            chunk.generated_file = image_file
                            yield chunk

                        if chunk.response_type == ResponseType.INTRIC_EVENT:
                            yield chunk

                        if chunk.response_type == ResponseType.TOOL_CALL:
                            if chunk.tool_calls_metadata:
                                for tc in chunk.tool_calls_metadata:
                                    # Check if this tool_call already exists (from TOOL_APPROVAL_REQUIRED)
                                    existing = next(
                                        (
                                            t
                                            for t in tool_calls
                                            if t.tool_call_id
                                            and t.tool_call_id == tc.tool_call_id
                                        ),
                                        None,
                                    )
                                    if existing:
                                        # Update existing entry with approval status
                                        existing.approved = tc.approved
                                        existing.result_status = tc.result_status
                                        # Pending entries are emitted before the argument
                                        # JSON is complete; fill arguments in once a later
                                        # chunk carries them.
                                        if tc.arguments is not None:
                                            existing.arguments = cast(
                                                dict[str, object] | None,
                                                tc.arguments,
                                            )
                                        # The TOOL_CALL chunk after execution carries the
                                        # tool output; keep it so later turns can replay.
                                        if tc.result is not None:
                                            existing.result = tc.result
                                    else:
                                        # Add new tool call
                                        tool_calls.append(
                                            ToolCallInfo(
                                                server_name=tc.server_name,
                                                tool_name=tc.tool_name,
                                                arguments=cast(
                                                    dict[str, object] | None,
                                                    tc.arguments,
                                                ),
                                                tool_call_id=tc.tool_call_id,
                                                approved=tc.approved,
                                                result_status=tc.result_status,
                                                result=tc.result,
                                                mcp_tool_name=tc.mcp_tool_name,
                                            )
                                        )
                            yield chunk

                        if chunk.response_type == ResponseType.TOOL_APPROVAL_REQUIRED:
                            # Collect tool calls for approval flow (approval status will be updated later)
                            if chunk.tool_calls_metadata:
                                for tc in chunk.tool_calls_metadata:
                                    # A "pending" TOOL_CALL chunk may already have
                                    # registered this call — merge instead of
                                    # duplicating it.
                                    existing = next(
                                        (
                                            t
                                            for t in tool_calls
                                            if t.tool_call_id
                                            and t.tool_call_id == tc.tool_call_id
                                        ),
                                        None,
                                    )
                                    if existing:
                                        existing.approved = None
                                        existing.result_status = tc.result_status
                                        if tc.arguments is not None:
                                            existing.arguments = cast(
                                                dict[str, object] | None,
                                                tc.arguments,
                                            )
                                    else:
                                        tool_calls.append(
                                            ToolCallInfo(
                                                server_name=tc.server_name,
                                                tool_name=tc.tool_name,
                                                arguments=cast(
                                                    dict[str, object] | None,
                                                    tc.arguments,
                                                ),
                                                tool_call_id=tc.tool_call_id,
                                                approved=None,
                                                result_status=tc.result_status,
                                                mcp_tool_name=tc.mcp_tool_name,
                                            )
                                        )
                            yield chunk

                        if chunk.response_type == ResponseType.TOOL_APPROVAL_TIMEOUT:
                            if chunk.tool_calls_metadata:
                                for tc in chunk.tool_calls_metadata:
                                    existing = next(
                                        (
                                            t
                                            for t in tool_calls
                                            if t.tool_call_id
                                            and t.tool_call_id == tc.tool_call_id
                                        ),
                                        None,
                                    )
                                    if existing:
                                        existing.approved = False
                                        existing.result_status = (
                                            tc.result_status or "timeout_denied"
                                        )
                                    else:
                                        tool_calls.append(
                                            ToolCallInfo(
                                                server_name=tc.server_name,
                                                tool_name=tc.tool_name,
                                                arguments=cast(
                                                    dict[str, object] | None,
                                                    tc.arguments,
                                                ),
                                                tool_call_id=tc.tool_call_id,
                                                approved=False,
                                                result_status=tc.result_status
                                                or "timeout_denied",
                                                mcp_tool_name=tc.mcp_tool_name,
                                            )
                                        )
                            yield chunk

                    # Get the references for the whole response
                    reference_chunks = get_references(
                        response_string=response_string,
                        info_blobs=datastore_result.no_duplicate_chunks,
                        version=version,
                        get_id_func=lambda chunk: chunk.info_blob_id,
                    )
                    # Prefer actual provider token counts, fall back to litellm estimates
                    if stream_usage and stream_usage.prompt_tokens is not None:
                        num_tokens_question = (
                            stream_usage.prompt_tokens + assistant_selector_tokens
                        )
                        input_source = "provider"
                    else:
                        num_tokens_question = (
                            response.total_token_count + assistant_selector_tokens
                        )
                        input_source = "litellm"

                    if stream_usage and stream_usage.completion_tokens is not None:
                        num_tokens_answer = stream_usage.completion_tokens
                        output_source = "provider"
                    else:
                        assert completion_model is not None
                        num_tokens_answer = (
                            count_tokens(response_string, completion_model.name)
                            + reasoning_token_count
                        )
                        output_source = "litellm"

                    logger.info(
                        f"[TokenUsage] assistant={assistant_id} streaming — "
                        f"input={num_tokens_question} ({input_source}), "
                        f"output={num_tokens_answer} ({output_source})"
                    )

                    await self.session_service.complete_question_with_answer(
                        question_id=question_id,
                        answer=response_string,
                        num_tokens_question=num_tokens_question,
                        num_tokens_answer=num_tokens_answer,
                        completion_model=cast("AICompletionModel", completion_model),
                        info_blob_chunks=reference_chunks,
                        generated_files=generated_files,
                        logging_details=response.extended_logging
                        or LoggingDetails(model_kwargs={}),
                        web_search_results=list(web_search_results or []),
                        tool_calls=tool_calls if tool_calls else None,
                        reasoning=reasoning_string or None,
                    )
                    completed = True

                    # Send token usage event to frontend
                    yield Completion(
                        text="",
                        response_type=ResponseType.TOKEN_USAGE,
                        usage=TokenUsage(
                            prompt_tokens=num_tokens_question,
                            completion_tokens=num_tokens_answer,
                        ),
                    )
                finally:
                    # Stream did not reach normal completion: client abort, LLM
                    # error, network drop, etc. The placeholder row already captures
                    # the user's question, so nothing streamed means there is
                    # nothing further to persist — skip the redundant UPDATE.
                    # Anything else (partial answer or reasoning streamed before
                    # abort) must be saved via a fresh DB session because the
                    # request-scoped AsyncSession may already be torn down and
                    # `await` across GeneratorExit is fragile.
                    if not completed and (response_string or reasoning_string):
                        from intric.sessions.session_service import (
                            persist_partial_question_answer,
                            safe_count_tokens,
                            schedule_background_save,
                        )

                        model_name = (
                            completion_model.name
                            if completion_model is not None
                            else None
                        )
                        partial_tokens_answer = (
                            safe_count_tokens(response_string, model_name)
                            + reasoning_token_count
                        )
                        schedule_background_save(
                            persist_partial_question_answer(
                                tenant_id=tenant_id,
                                question_id=question_id,
                                answer=response_string,
                                num_tokens_answer=partial_tokens_answer,
                                reasoning=reasoning_string or None,
                            )
                        )
                        logger.info(
                            "Scheduled partial chat answer save on stream abort: "
                            f"assistant={assistant_id} question_id={question_id} "
                            f"answer_chars={len(response_string)}"
                        )

            return response_stream()
        else:
            reasoning_token_count = 0
            final_answer = ""
            final_reasoning: str | None = None
            generated_files: list[File] = []

            if response.completion is not None:
                answer = response.completion
                if isinstance(answer, str):
                    final_answer = answer
                else:
                    reasoning_token_count = getattr(answer, "reasoning_token_count", 0)
                    final_answer = getattr(answer, "text", "")
                    final_reasoning = getattr(answer, "reasoning_content", None)

            reference_chunks = get_references(
                response_string=final_answer,
                info_blobs=datastore_result.no_duplicate_chunks,
                version=version,
                get_id_func=lambda chunk: chunk.info_blob_id,
            )
            # Prefer actual provider token counts, fall back to litellm estimates
            if response.usage and response.usage.prompt_tokens is not None:
                num_tokens_question = (
                    response.usage.prompt_tokens + assistant_selector_tokens
                )
                input_source = "provider"
            else:
                num_tokens_question = (
                    response.total_token_count + assistant_selector_tokens
                )
                input_source = "litellm"

            if response.usage and response.usage.completion_tokens is not None:
                num_tokens_answer = response.usage.completion_tokens
                output_source = "provider"
            else:
                assert completion_model is not None
                num_tokens_answer = (
                    count_tokens(final_answer, completion_model.name)
                    + reasoning_token_count
                )
                output_source = "litellm"

            logger.info(
                f"[TokenUsage] assistant={assistant_id} non-streaming — "
                f"input={num_tokens_question} ({input_source}), "
                f"output={num_tokens_answer} ({output_source})"
            )

            await self.session_service.complete_question_with_answer(
                question_id=question_id,
                answer=final_answer,
                num_tokens_question=num_tokens_question,
                num_tokens_answer=num_tokens_answer,
                generated_files=generated_files,
                completion_model=cast("AICompletionModel", completion_model),
                info_blob_chunks=reference_chunks,
                logging_details=response.extended_logging
                or LoggingDetails(model_kwargs={}),
                web_search_results=list(web_search_results or []),
                reasoning=final_reasoning,
            )

            return final_answer

    async def _check_assistant_models(self, assistant: "Assistant", space: "Space"):
        if assistant.completion_model is None:
            raise BadRequestException("Assistant has no completion model configured.")

        if not assistant.completion_model.can_access:
            raise UnauthorizedException(
                "Completion model is inaccessible, please contact your administrator"
            )
        elif not space.is_completion_model_in_space(assistant.completion_model.id):
            raise BadRequestException(
                f"Completion Model {assistant.completion_model.nickname} is not in space."
            )

        for item in assistant.collections + assistant.websites:
            if not space.is_embedding_model_in_space(item.embedding_model.id):
                raise BadRequestException(
                    f"Embedding Model {item.embedding_model.name} is not in space."
                )

    async def ask(
        self,
        question: str,
        assistant_id: "UUID",
        group_chat_id: Optional["UUID"] = None,
        session_id: "UUID | None" = None,
        file_ids: list["UUID"] | None = None,
        stream: bool = False,
        tool_assistant_id: Optional["UUID"] = None,
        version: int = 1,
        use_web_search: bool = False,
        assistant_selector_tokens: int = 0,
        require_tool_approval: bool = False,
        disabled_mcp_server_ids: list["UUID"] | None = None,
    ):
        # PRD §6 "Critical tests #2": defense-in-depth — never run a Help
        # Assistant via the normal ask path. Both ``POST /assistants/{id}/sessions/``
        # and ``POST /assistants/{id}/sessions/{session_id}/`` flow through
        # here, so guarding this method covers both router entry points and
        # short-circuits before any session row is created.
        await assert_not_helper_assistant(
            assistant_id=assistant_id,
            role_repo=self.org_space_assistant_role_repo,
            history_repo=self.help_assistant_assignment_history_repo,
        )
        if tool_assistant_id is not None:
            await assert_not_helper_assistant(
                assistant_id=tool_assistant_id,
                role_repo=self.org_space_assistant_role_repo,
                history_repo=self.help_assistant_assignment_history_repo,
            )

        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        active_assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        # The personal chat is the personal space's default assistant — gated by
        # PERSONAL_CHAT (via can_read_default_assistant), not ASSISTANTS, so a
        # baseline role can chat without managing assistants.
        is_personal_default = (
            space.is_personal()
            and space.default_assistant is not None
            and active_assistant.id == space.default_assistant.id
        )
        can_use = (
            actor.can_read_default_assistant()
            if is_personal_default
            else actor.can_read_assistant(assistant=active_assistant)
        )
        if not can_use:
            raise UnauthorizedException(
                "You do not have permission to use this assistant.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "ask",
                    "auth_layer": "domain_policy",
                },
            )

        space.can_ask_assistant(assistant=active_assistant)

        if tool_assistant_id is not None:
            tool_assistant = space.get_assistant(assistant_id=tool_assistant_id)
            if tool_assistant_id not in [
                assistant.id for assistant in active_assistant.tool_assistants
            ]:
                raise BadRequestException()

            assistant_to_ask = tool_assistant
        else:
            assistant_to_ask = active_assistant

        cleaned_question = clean_intric_tag(question)
        files = await self.file_service.get_files_by_ids(file_ids=file_ids or [])

        # Personal assistant governance runtime enforcement.
        # Resolve before creating a session/question placeholder so invalid
        # policy states fail without leaving empty conversation history behind.
        completion_model_override: "CompletionModel | None" = None
        mcp_servers_override: "list[MCPServer] | None" = None
        prompt_override: str | None = None
        effective_config = await self._resolve_effective_config(
            space=space, assistant=assistant_to_ask
        )
        if effective_config is not None:
            if effective_config.models_enforced:
                # Same resolution preflight uses, so the projected and actual
                # models can't diverge. None here means the whitelist is empty.
                resolved_model = select_effective_completion_model(
                    current_model=assistant_to_ask.completion_model,
                    effective_config=effective_config,
                )
                if resolved_model is None:
                    raise BadRequestException(
                        "Personal assistant governance policy has no allowed models — "
                        "contact admin",
                    )
                # Only override when the policy steered away from the assistant's
                # own (stale) model; otherwise leave it untouched.
                if resolved_model is not assistant_to_ask.completion_model:
                    completion_model_override = resolved_model  # type: ignore[assignment]

            if effective_config.mcp_enforced:
                # GRANT semantics: the policy provides its allowed MCP servers to
                # the personal assistant directly. The user does not attach them
                # on the assistant (the entity's own mcp_servers stay empty), so
                # we hand the policy set straight to the completion call rather
                # than intersecting with assistant_to_ask.mcp_servers.
                mcp_servers_override = list(effective_config.available_mcp_servers)

            if (
                effective_config.prompt_enforced
                and effective_config.enforced_prompt_text
            ):
                prompt_override = effective_config.enforced_prompt_text

        # Per-request MCP opt-out from the composer toolbar: narrow whatever set
        # is effective (policy-granted servers above, or the assistant's own) by
        # the servers the user switched off for this message. Narrowing only — it
        # can never enable a server that isn't already active.
        disabled_ids = set(disabled_mcp_server_ids or [])
        if disabled_ids:
            base_mcp_servers = (
                mcp_servers_override
                if mcp_servers_override is not None
                else list(assistant_to_ask.mcp_servers)
            )
            mcp_servers_override = [
                server for server in base_mcp_servers if server.id not in disabled_ids
            ]

        effective_completion_model = (
            completion_model_override or assistant_to_ask.completion_model
        )
        if effective_completion_model is None:
            raise BadRequestException(
                "No completion model configured for this conversation.",
            )

        if session_id is not None:
            if group_chat_id is not None:
                session = await self.session_service.get_session_by_uuid(
                    id=session_id, group_chat_id=group_chat_id
                )
            else:
                session = await self.session_service.get_session_by_uuid(
                    id=session_id, assistant_id=assistant_id
                )
        else:
            # Set the name as the question or the filenames
            name = question
            if not name and files:
                name = " ".join(file.name for file in files)
            if group_chat_id is not None:
                session = await self.session_service.create_session(
                    name=name, group_chat_id=group_chat_id
                )
            else:
                session = await self.session_service.create_session(
                    name=name, assistant_id=active_assistant.id
                )

        assert session is not None
        for _question in session.questions:
            _question.question = clean_intric_tag(_question.question)

        # Persist a placeholder Question row BEFORE the LLM stream begins. This commits
        # with the router's setup transaction (conversations_router.py line 300/328), so
        # the user's message is durable even if the stream is aborted mid-flight.
        question_id = await self.session_service.create_question_placeholder(
            question=question,
            session=session,
            files=files,
            assistant_id=assistant_to_ask.id,
            completion_model=cast("AICompletionModel", effective_completion_model),
        )

        if use_web_search and version == 2:
            web_search = await self.web_search
            web_search_results = await web_search.search(search_query=question)
        else:
            web_search_results = []

        response, datastore_result = await assistant_to_ask.ask(
            question=cleaned_question,
            completion_service=self.completion_service,
            references_service=self.references_service,
            session=session,
            files=files,
            stream=stream,
            version=version,
            web_search_results=web_search_results,
            require_tool_approval=require_tool_approval,
            completion_model_override=completion_model_override,
            mcp_servers_override=mcp_servers_override,
            prompt_override=prompt_override,
        )

        # TODO: Separate the response based on stream true or false

        answer = await self._handle_response(
            response=response,
            datastore_result=datastore_result,
            question=question,
            files=files,
            completion_model=effective_completion_model,
            session=session,
            stream=stream,
            assistant_id=assistant_to_ask.id,
            question_id=question_id,
            version=version,
            web_search_results=web_search_results,
            assistant_selector_tokens=assistant_selector_tokens,
        )

        if not stream:
            assert isinstance(answer, str)
            info_blob_references = datastore_result.info_blobs
        else:
            info_blob_references = datastore_result.info_blobs

        final_response = AssistantResponse(
            question=question,
            files=files,
            session=session,
            answer=answer,
            info_blobs=info_blob_references,
            completion_model=effective_completion_model,
            tools=UseTools(
                assistants=[
                    ToolAssistant(id=assistant_to_ask.id, handle=assistant_to_ask.name)
                ]
            ),
            description=assistant_to_ask.description,
            web_search_results=web_search_results,
            question_id=question_id,
        )

        return final_response

    async def publish_assistant(
        self, assistant_id: "UUID", publish: bool
    ) -> tuple[Assistant, list[ResourcePermission]]:
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assert space.id is not None
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_publish_assistants():
            raise UnauthorizedException(
                "Publishing assistants is not allowed for your current space role.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "publish",
                    "auth_layer": "domain_policy",
                },
            )

        assistant.update(published=publish)

        await self.space_repo.update(space)

        # TODO: Review how we get the permissions to the presentation layer
        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )

        return assistant, permissions

    async def get_assistant_mcp_servers(self, assistant_id: UUID):
        """Get all MCP servers associated with an assistant."""
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_assistants():
            raise UnauthorizedException(
                "You do not have permission to read assistants in this space.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "read",
                    "auth_layer": "domain_policy",
                },
            )

        return assistant.mcp_servers

    async def add_mcp_to_assistant(
        self,
        assistant_id: UUID,
        mcp_server_id: UUID,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        """Add an MCP server to an assistant."""
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assert space.id is not None
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_edit_assistants():
            raise UnauthorizedException(
                "You do not have permission to edit assistants in this space.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "edit_mcp",
                    "auth_layer": "domain_policy",
                },
            )

        # Get existing associations from the database
        import sqlalchemy as sa

        from intric.database.tables.assistant_table import AssistantMCPServers
        from intric.database.tables.mcp_server_table import (
            MCPServers as MCPServersTable,
        )
        from intric.database.tables.mcp_server_table import (
            SpacesMCPServers as SpacesMCPServersTable,
        )

        # Validate tenant ownership + enablement
        mcp_server_query = sa.select(MCPServersTable).where(
            MCPServersTable.id == mcp_server_id,
            MCPServersTable.tenant_id == self.user.tenant_id,
            MCPServersTable.is_enabled == True,  # noqa: E712
        )
        mcp_server_db = await self.repo.session.scalar(mcp_server_query)
        if mcp_server_db is None:
            raise BadRequestException("MCP server is not enabled for this tenant")

        effective_config = await self._resolve_effective_config(
            space=space, assistant=assistant
        )
        mcp_governed = effective_config is not None and effective_config.mcp_enforced
        if not mcp_governed:
            space_mapping_query = sa.select(SpacesMCPServersTable).where(
                SpacesMCPServersTable.space_id == space.id,
                SpacesMCPServersTable.mcp_server_id == mcp_server_id,
            )
            space_mapping = await self.repo.session.scalar(space_mapping_query)
            if space_mapping is None:
                raise BadRequestException(
                    "MCP server is not assigned to this assistant's space"
                )

        await self._ensure_governance_policy_allows_update(
            space=space,
            assistant=assistant,
            completion_model_id=None,
            mcp_server_ids=[mcp_server_id],
            effective_config=effective_config,
        )

        stmt = sa.select(AssistantMCPServers).where(
            AssistantMCPServers.assistant_id == assistant_id
        )
        result = await self.repo.session.execute(stmt)
        existing_server_ids: list[UUID] = [
            row.mcp_server_id for row in result.scalars()
        ]

        # Check if already exists
        if mcp_server_id in existing_server_ids:
            raise BadRequestException("MCP server already associated with assistant")

        # Add new association
        existing_server_ids.append(mcp_server_id)
        # Update via repository
        from intric.database.tables.assistant_table import Assistants

        stmt = sa.select(Assistants).where(Assistants.id == assistant_id)
        assistant_in_db = await self.repo.session.scalar(stmt)
        assert assistant_in_db is not None

        await self.repo.set_mcp_servers(assistant_in_db, existing_server_ids)

        # Refresh and return
        refreshed_space = await self.space_repo.get_space_by_assistant(
            assistant_id=assistant_id
        )
        assistant = refreshed_space.get_assistant(assistant_id=assistant_id)
        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )

        return assistant, permissions

    async def remove_mcp_from_assistant(
        self,
        assistant_id: UUID,
        mcp_server_id: UUID,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        """Remove an MCP server from an assistant."""
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assert space.id is not None
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_edit_assistants():
            raise UnauthorizedException(
                "You do not have permission to edit assistants in this space.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "edit_mcp",
                    "auth_layer": "domain_policy",
                },
            )

        # Get existing associations from the database
        import sqlalchemy as sa

        from intric.database.tables.assistant_table import (
            AssistantMCPServers,
            Assistants,
        )

        stmt = sa.select(AssistantMCPServers).where(
            AssistantMCPServers.assistant_id == assistant_id
        )
        result = await self.repo.session.execute(stmt)
        existing_server_ids: list[UUID] = [
            row.mcp_server_id for row in result.scalars()
        ]

        # Remove the association
        existing_server_ids = [
            server_id for server_id in existing_server_ids if server_id != mcp_server_id
        ]
        # Update via repository
        stmt = sa.select(Assistants).where(Assistants.id == assistant_id)
        assistant_in_db = await self.repo.session.scalar(stmt)
        assert assistant_in_db is not None

        await self.repo.set_mcp_servers(assistant_in_db, existing_server_ids)

        # Refresh and return
        refreshed_space = await self.space_repo.get_space_by_assistant(
            assistant_id=assistant_id
        )
        assistant = refreshed_space.get_assistant(assistant_id=assistant_id)
        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )

        return assistant, permissions

    async def update_assistant_mcp_config(
        self,
        assistant_id: UUID,
        mcp_server_id: UUID,
        enabled: bool | None = None,
        config: dict[str, object] | None = None,
        priority: int | None = None,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        """Update the configuration of an MCP server association."""
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assert space.id is not None
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_edit_assistants():
            raise UnauthorizedException(
                "You do not have permission to edit assistants in this space.",
                code="forbidden_action",
                context={
                    "resource_type": "assistant",
                    "action": "edit_mcp",
                    "auth_layer": "domain_policy",
                },
            )

        # Get existing associations from the database
        import sqlalchemy as sa

        from intric.database.tables.assistant_table import (
            AssistantMCPServers,
            Assistants,
        )

        stmt = sa.select(AssistantMCPServers).where(
            AssistantMCPServers.assistant_id == assistant_id
        )
        result = await self.repo.session.execute(stmt)
        existing_server_ids: list[UUID] = [
            row.mcp_server_id for row in result.scalars()
        ]

        # Check if the association exists
        if mcp_server_id not in existing_server_ids:
            raise BadRequestException("MCP server not associated with assistant")

        # Note: enabled/config/priority fields are not currently stored in the database schema
        # The association table only stores assistant_id and mcp_server_id
        # Update via repository
        stmt = sa.select(Assistants).where(Assistants.id == assistant_id)
        assistant_in_db = await self.repo.session.scalar(stmt)
        assert assistant_in_db is not None

        await self.repo.set_mcp_servers(assistant_in_db, existing_server_ids)

        # Refresh and return
        refreshed_space = await self.space_repo.get_space_by_assistant(
            assistant_id=assistant_id
        )
        assistant = refreshed_space.get_assistant(assistant_id=assistant_id)
        permissions: list[ResourcePermission] = actor.get_assistant_permissions(
            assistant=assistant
        )

        return assistant, permissions
