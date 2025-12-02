import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Union
from uuid import UUID

from intric.ai_models.completion_models.completion_model import (
    ModelKwargs,
    ResponseType,
)
from intric.assistants.api.assistant_models import AssistantResponse
from intric.assistants.assistant import Assistant
from intric.assistants.assistant_factory import AssistantFactory
from intric.assistants.assistant_repo import AssistantRepository
from intric.authentication.auth_service import AuthService
from intric.completion_models.infrastructure.context_builder import count_tokens
from intric.completion_models.infrastructure.web_search import WebSearch
from intric.files.file_service import FileService
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.main.models import NOT_PROVIDED, NotProvided
from intric.prompts.api.prompt_models import PromptCreate
from intric.prompts.prompt import Prompt
from intric.prompts.prompt_service import PromptService
from intric.questions.question import ToolAssistant, UseTools
from intric.roles.permissions import (
    Permission,
    validate_permission,
    validate_permissions,
)
from intric.services.service_repo import ServiceRepository
from intric.spaces.api.space_models import WizardType
from intric.spaces.space_service import SpaceService
from intric.templates.assistant_template.assistant_template_service import (
    AssistantTemplateService,
)
from intric.users.user import UserInDB
from intric.workflows.step_repo import StepRepository

if TYPE_CHECKING:
    from intric.actors import ActorManager
    from intric.ai_models.completion_models.completion_model import (
        CompletionModel,
        CompletionModelResponse,
    )
    from intric.assistants.references import ReferencesService
    from intric.completion_models.application import CompletionModelCRUDService
    from intric.completion_models.infrastructure.completion_service import (
        CompletionService,
    )
    from intric.completion_models.infrastructure.web_search import (
        WebSearchResult,
    )
    from intric.files.file_models import File
    from intric.info_blobs.info_blob import InfoBlobChunkInDBWithScore
    from intric.integration.domain.repositories.integration_knowledge_repo import (
        IntegrationKnowledgeRepository,
    )
    from intric.services.service import DatastoreResult
    from intric.sessions.session import SessionInDB
    from intric.sessions.session_service import SessionService
    from intric.spaces.api.space_models import TemplateCreate
    from intric.spaces.space import Space
    from intric.spaces.space_repo import SpaceRepository

AT_TAG_PATTERN = r"<intric-at-tag: @[^>]+>"
REFERENCE_PATTERN = r'<inref id="([0-9a-f]{8})"/>'  # noqa


def clean_intric_tag(input_string: str):
    return re.sub(AT_TAG_PATTERN, "", input_string)


def get_references(
    response_string: str,
    info_blobs: list["InfoBlobChunkInDBWithScore"],
    version: int = 1,
    get_id_func=lambda blob: blob.id,
):
    if version == 1:
        return info_blobs

    # Preserve order, remove duplicates
    info_blob_ids = list(dict.fromkeys(re.findall(REFERENCE_PATTERN, response_string)))

    def _get_blob(blob_id):
        return next((blob for blob in info_blobs if str(get_id_func(blob))[:8] == blob_id), None)

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
    ):
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

    @property
    async def web_search(self):
        return WebSearch()

    def validate_space_assistant(self, space: "Space", assistant: Assistant):
        # validate completion model
        if assistant.completion_model is not None:
            if not space.is_completion_model_in_space(assistant.completion_model.id):
                raise BadRequestException("Completion model is not in space.")

        # validate groups
        for group in assistant.collections:
            if not space.is_group_in_space(group.id):
                raise BadRequestException("Group is not in space.")

        # validate websites
        for website in assistant.websites:
            if not space.is_website_in_space(website.id):
                raise BadRequestException("Website is not in space.")

        for integration_knowledge in assistant.integration_knowledge_list:
            if not space.is_integration_knowledge_in_space(
                integration_knowledge_id=integration_knowledge.id
            ):
                raise BadRequestException("Invalid integration knowledge")

    async def create_assistant(
        self,
        name: str,
        space_id: UUID,
        template_data: Optional["TemplateCreate"] = None,
    ) -> Assistant:
        space = await self.space_service.get_space(space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_create_assistants():
            raise UnauthorizedException(
                "User does not have permission to create assistants in this space"
            )

        completion_model = await self.get_completion_model(space=space)

        if not template_data:
            assistant = self.factory.create_assistant(
                name=name,
                user=self.user,
                space_id=space_id,
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
        permissions = actor.get_assistant_permissions(assistant=assistant)

        return assistant, permissions

    async def _create_from_template(
        self,
        space: "Space",
        template_data: "TemplateCreate",
        completion_model: "CompletionModel",
        name: str | None = None,
    ):
        template = await self.assistant_template_service.get_assistant_template(
            assistant_template_id=template_data.id
        )

        # Validate incoming data
        template.validate_assistant_wizard_data(template_data=template_data)

        attachments = await self.file_service.get_file_infos(
            file_ids=template_data.get_ids_by_type(wizard_type=WizardType.attachments)
        )
        collections = [
            space.get_collection(collection_id=group_id)
            for group_id in template_data.get_ids_by_type(wizard_type=WizardType.groups)
        ]

        prompt = None
        if template.prompt_text:
            prompt = await self.prompt_service.create_prompt(text=template.prompt_text)

        assistant = self.factory.create_assistant(
            name=name or template.name,
            user=self.user,
            space_id=space.id,
            prompt=prompt,
            completion_model=completion_model,
            attachments=attachments,
            collections=collections,
            template=template,
        )

        space.add_assistant(assistant)
        refreshed_space = await self.space_repo.update(space)
        assistant = refreshed_space.get_assistant(assistant.id)

        return assistant

    async def get_completion_model(self, space: "Space") -> "CompletionModel":
        completion_model = space.get_default_completion_model() or (
            space.get_latest_completion_model()
            if not space.is_personal()
            else await self.completion_model_crud_service.get_default_completion_model()
        )

        if completion_model is None:
            raise BadRequestException(
                "Can not create an assistant in a space without enabled completion models"
            )

        return completion_model

    async def create_default_assistant(self, name: str, space: "Space"):
        completion_model = space.get_default_completion_model()
        return self.factory.create_assistant(
            name=name,
            user=self.user,
            space_id=space.id,
            completion_model=completion_model,
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
        mcp_tools: list | None = None,  # List of (tool_id, is_enabled) tuples
        attachment_ids: list[UUID] | None = None,
        description: Union[str, NotProvided] = NOT_PROVIDED,
        insight_enabled: Optional[bool] = None,
        data_retention_days: Union[int, None, NotProvided] = NOT_PROVIDED,
        metadata_json: Union[dict, None, NotProvided] = NOT_PROVIDED,
    ):
        if logging_enabled:
            validate_permission(self.user, Permission.ADMIN)

        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        # Check if user has permission to toggle insights
        if insight_enabled is not None:
            if not actor.can_toggle_insight():
                raise UnauthorizedException("Only admins can toggle insights")

        assistant = space.get_assistant(assistant_id=assistant_id)

        if not actor.can_edit_assistants():
            raise UnauthorizedException()

        if prompt is not None:
            # Create the prompt if the prompt contains text
            # Update the description if the prompt contains description
            if prompt.text is not None:
                prompt = await self.prompt_service.create_prompt(prompt.text, prompt.description)

        completion_model = None
        if completion_model_id is not None:
            completion_model = space.get_completion_model(completion_model_id)

        attachments = None
        if attachment_ids is not None:
            attachments = await self.file_service.get_file_infos(attachment_ids)

        if groups is not None:
            groups = [space.get_collection(collection_id=group_id) for group_id in groups]

        if websites is not None:
            websites = [space.get_website(website_id=website_id) for website_id in websites]

        integration_knowledge_list = None
        if integration_knowledge_ids is not None:
            integration_knowledge_list = [
                space.get_integration_knowledge(integration_knowledge_id=integration_knowledge_id)
                for integration_knowledge_id in integration_knowledge_ids
            ]

        # Store MCP server IDs and tool settings for repository to handle
        assistant._mcp_server_ids = mcp_server_ids
        assistant._mcp_tool_settings = mcp_tools

        assistant.update(
            name=name,
            prompt=prompt,
            completion_model=completion_model,
            completion_model_kwargs=completion_model_kwargs,
            attachments=attachments,
            logging_enabled=logging_enabled,
            collections=groups,
            websites=websites,
            integration_knowledge_list=integration_knowledge_list,
            description=description,
            insight_enabled=insight_enabled,
            data_retention_days=data_retention_days,
            metadata_json=metadata_json,
        )

        self.validate_space_assistant(space=space, assistant=assistant)

        refreshed_space = await self.space_repo.update(space)
        assistant = refreshed_space.get_assistant(assistant_id=assistant_id)

        # TODO: Review how we get the permissions to the presentation layer
        permissions = actor.get_assistant_permissions(assistant=assistant)

        return assistant, permissions

    async def get_assistant(self, assistant_id: UUID) -> Assistant:
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_assistants():
            raise UnauthorizedException()

        # TODO: Review how we get the permissions to the presentation layer
        permissions = actor.get_assistant_permissions(assistant=assistant)

        return assistant, permissions

    async def get_assistants(self, name: str = None, for_tenant: bool = False) -> list[Assistant]:
        if for_tenant:
            return await self.get_tenant_assistants(name)

        return await self.repo.get_for_user(self.user.id, search_query=name)

    @validate_permissions(Permission.ADMIN)
    async def get_tenant_assistants(
        self,
        name: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
    ):
        assistants = await self.repo.get_for_tenant(
            tenant_id=self.user.tenant_id,
            search_query=name,
            start_date=start_date,
            end_date=end_date,
        )
        return assistants

    async def delete_assistant(self, assistant_id: UUID):
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_delete_assistants():
            raise UnauthorizedException()

        assistant = space.get_assistant(assistant_id=assistant_id)
        space.remove_assistant(assistant)
        await self.space_repo.update(space)

    @validate_permissions(Permission.ADMIN)
    async def generate_api_key(self, assistant_id: UUID):
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_edit_assistants():
            raise UnauthorizedException()

        return await self.auth_service.create_assistant_api_key("ina", assistant_id=assistant_id)

    async def get_prompts_by_assistant(self, assistant_id: UUID) -> list[Prompt]:
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_prompts_of_assistants():
            raise UnauthorizedException()

        return await self.prompt_service.get_prompts_by_assistant(assistant_id)

    async def _handle_response(
        self,
        response: "CompletionModelResponse",
        datastore_result: "DatastoreResult",
        question: str,
        files: list["File"],
        completion_model: "CompletionModel",
        session: "SessionInDB",
        stream: bool,
        assistant_id: UUID,
        version: int = 1,
        web_search_results: list["WebSearchResult"] = [],
        assistant_selector_tokens: int = 0,
    ):
        if stream:

            async def response_stream():
                reasoning_token_count = 0
                response_string = ""
                generated_files = []

                async for chunk in response.completion:
                    reasoning_token_count = chunk.reasoning_token_count

                    if chunk.response_type == ResponseType.TEXT:
                        response_string = f"{response_string}{chunk.text}"
                        chunk.reference_chunks = get_references(
                            response_string=response_string,
                            info_blobs=datastore_result.info_blobs,
                            version=version,
                        )
                        yield chunk

                    if chunk.response_type == ResponseType.FILES:
                        image_file = await self.file_service.save_image_from_bytes(chunk.image_data)

                        generated_files.append(image_file)
                        chunk.generated_file = image_file
                        yield chunk

                    if chunk.response_type == ResponseType.INTRIC_EVENT:
                        yield chunk

                    if chunk.response_type == ResponseType.TOOL_CALL:
                        yield chunk

                # Get the references for the whole response
                reference_chunks = get_references(
                    response_string=response_string,
                    info_blobs=datastore_result.no_duplicate_chunks,
                    version=version,
                    get_id_func=lambda chunk: chunk.info_blob_id,
                )
                total_response_tokens = count_tokens(response_string) + reasoning_token_count
                await self.session_service.add_question_to_session(
                    question=question,
                    answer=response_string,
                    num_tokens_question=response.total_token_count + assistant_selector_tokens,
                    num_tokens_answer=total_response_tokens,
                    session=session,
                    completion_model=completion_model,
                    info_blob_chunks=reference_chunks,
                    files=files,
                    generated_files=generated_files,
                    logging_details=response.extended_logging,
                    assistant_id=assistant_id,
                    web_search_results=web_search_results,
                )

            return response_stream()
        else:
            reasoning_token_count = 0
            final_answer = ""
            generated_files = []

            if response.completion is not None:
                answer = response.completion
                reasoning_token_count = answer.reasoning_token_count
                final_answer = answer.text

            reference_chunks = get_references(
                response_string=final_answer,
                info_blobs=datastore_result.no_duplicate_chunks,
                version=version,
                get_id_func=lambda chunk: chunk.info_blob_id,
            )
            total_response_tokens = count_tokens(final_answer) + reasoning_token_count
            await self.session_service.add_question_to_session(
                question=question,
                answer=final_answer,
                num_tokens_question=response.total_token_count + assistant_selector_tokens,
                num_tokens_answer=total_response_tokens,
                files=files,
                generated_files=generated_files,
                completion_model=completion_model,
                info_blob_chunks=reference_chunks,
                session=session,
                logging_details=response.extended_logging,
                assistant_id=assistant_id,
            )

            return final_answer

    async def _check_assistant_models(self, assistant: "Assistant", space: "Space"):
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
        session_id: "UUID" = None,
        file_ids: list["UUID"] = [],
        stream: bool = False,
        tool_assistant_id: Optional["UUID"] = None,
        version: int = 1,
        use_web_search: bool = False,
        assistant_selector_tokens: int = 0,
    ):
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        active_assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_assistant(assistant=active_assistant):
            raise UnauthorizedException()

        if not space.can_ask_assistant(assistant=active_assistant):
            raise UnauthorizedException(
                "This assistant can not be used at this time. "
                "Please review your assistant settings and try again."
            )

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
        files = await self.file_service.get_files_by_ids(file_ids=file_ids)

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

        for _question in session.questions:
            _question.question = clean_intric_tag(_question.question)

        if use_web_search and version == 2:
            web_search_results = await self.web_search.search(search_query=question)
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
        )

        # TODO: Separate the response based on stream true or false

        answer = await self._handle_response(
            response=response,
            datastore_result=datastore_result,
            question=question,
            files=files,
            completion_model=assistant_to_ask.completion_model,
            session=session,
            stream=stream,
            assistant_id=assistant_to_ask.id,
            version=version,
            web_search_results=web_search_results,
            assistant_selector_tokens=assistant_selector_tokens,
        )

        if not stream:
            info_blob_references = get_references(
                response_string=answer,
                info_blobs=datastore_result.info_blobs,
                version=version,
            )
        else:
            info_blob_references = datastore_result.info_blobs

        final_response = AssistantResponse(
            question=question,
            files=files,
            session=session,
            answer=answer,
            info_blobs=info_blob_references,
            completion_model=assistant_to_ask.completion_model,
            tools=(
                UseTools(
                    assistants=[ToolAssistant(id=assistant_to_ask.id, handle=assistant_to_ask.name)]
                )
                if assistant_to_ask.id is not None
                else UseTools(assistants=[])
            ),
            description=assistant_to_ask.description,
            web_search_results=web_search_results,
        )

        return final_response

    async def publish_assistant(self, assistant_id: "UUID", publish: bool):
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_publish_assistants():
            raise UnauthorizedException()

        assistant.update(published=publish)

        await self.space_repo.update(space)

        # TODO: Review how we get the permissions to the presentation layer
        permissions = actor.get_assistant_permissions(assistant=assistant)

        return assistant, permissions

    async def get_assistant_mcp_servers(self, assistant_id: UUID):
        """Get all MCP servers associated with an assistant."""
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_assistants():
            raise UnauthorizedException()

        return assistant.mcp_servers

    async def add_mcp_to_assistant(
        self,
        assistant_id: UUID,
        mcp_server_id: UUID,
        enabled: bool = True,
        config: dict | None = None,
        priority: int = 0,
    ):
        """Add an MCP server to an assistant."""
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_edit_assistants():
            raise UnauthorizedException()

        # TODO: Validate that the MCP server is enabled for the tenant

        # Get existing associations from the database
        from intric.database.tables.assistant_table import AssistantMCPServers
        import sqlalchemy as sa

        stmt = sa.select(AssistantMCPServers).where(
            AssistantMCPServers.assistant_id == assistant_id
        )
        result = await self.repo.session.execute(stmt)
        existing_associations = [
            {
                "mcp_server_id": row.mcp_server_id,
                "enabled": row.enabled,
                "config": row.config,
                "priority": row.priority,
            }
            for row in result.scalars()
        ]

        # Check if already exists
        if any(a["mcp_server_id"] == mcp_server_id for a in existing_associations):
            raise BadRequestException("MCP server already associated with assistant")

        # Add new association
        existing_associations.append({
            "mcp_server_id": mcp_server_id,
            "enabled": enabled,
            "config": config,
            "priority": priority,
        })

        # Update via repository
        from intric.database.tables.assistant_table import Assistants
        stmt = sa.select(Assistants).where(Assistants.id == assistant_id)
        assistant_in_db = await self.repo.session.scalar(stmt)

        await self.repo._set_mcp_servers(assistant_in_db, existing_associations)

        # Refresh and return
        refreshed_space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = refreshed_space.get_assistant(assistant_id=assistant_id)
        permissions = actor.get_assistant_permissions(assistant=assistant)

        return assistant, permissions

    async def remove_mcp_from_assistant(
        self,
        assistant_id: UUID,
        mcp_server_id: UUID,
    ):
        """Remove an MCP server from an assistant."""
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_edit_assistants():
            raise UnauthorizedException()

        # Get existing associations from the database
        from intric.database.tables.assistant_table import AssistantMCPServers, Assistants
        import sqlalchemy as sa

        stmt = sa.select(AssistantMCPServers).where(
            AssistantMCPServers.assistant_id == assistant_id
        )
        result = await self.repo.session.execute(stmt)
        existing_associations = [
            {
                "mcp_server_id": row.mcp_server_id,
                "enabled": row.enabled,
                "config": row.config,
                "priority": row.priority,
            }
            for row in result.scalars()
        ]

        # Remove the association
        existing_associations = [
            a for a in existing_associations if a["mcp_server_id"] != mcp_server_id
        ]

        # Update via repository
        stmt = sa.select(Assistants).where(Assistants.id == assistant_id)
        assistant_in_db = await self.repo.session.scalar(stmt)

        await self.repo._set_mcp_servers(assistant_in_db, existing_associations)

        # Refresh and return
        refreshed_space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = refreshed_space.get_assistant(assistant_id=assistant_id)
        permissions = actor.get_assistant_permissions(assistant=assistant)

        return assistant, permissions

    async def update_assistant_mcp_config(
        self,
        assistant_id: UUID,
        mcp_server_id: UUID,
        enabled: bool | None = None,
        config: dict | None = None,
        priority: int | None = None,
    ):
        """Update the configuration of an MCP server association."""
        space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = space.get_assistant(assistant_id=assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_edit_assistants():
            raise UnauthorizedException()

        # Get existing associations from the database
        from intric.database.tables.assistant_table import AssistantMCPServers, Assistants
        import sqlalchemy as sa

        stmt = sa.select(AssistantMCPServers).where(
            AssistantMCPServers.assistant_id == assistant_id
        )
        result = await self.repo.session.execute(stmt)
        existing_associations = [
            {
                "mcp_server_id": row.mcp_server_id,
                "enabled": row.enabled,
                "config": row.config,
                "priority": row.priority,
            }
            for row in result.scalars()
        ]

        # Find and update the association
        found = False
        for assoc in existing_associations:
            if assoc["mcp_server_id"] == mcp_server_id:
                found = True
                if enabled is not None:
                    assoc["enabled"] = enabled
                if config is not None:
                    assoc["config"] = config
                if priority is not None:
                    assoc["priority"] = priority
                break

        if not found:
            raise BadRequestException("MCP server not associated with assistant")

        # Update via repository
        stmt = sa.select(Assistants).where(Assistants.id == assistant_id)
        assistant_in_db = await self.repo.session.scalar(stmt)

        await self.repo._set_mcp_servers(assistant_in_db, existing_associations)

        # Refresh and return
        refreshed_space = await self.space_repo.get_space_by_assistant(assistant_id=assistant_id)
        assistant = refreshed_space.get_assistant(assistant_id=assistant_id)
        permissions = actor.get_assistant_permissions(assistant=assistant)

        return assistant, permissions
