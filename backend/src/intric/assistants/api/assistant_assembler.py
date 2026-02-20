from typing import TYPE_CHECKING

from intric.assistants.api.assistant_models import (
    AssistantPublic,
    AssistantType,
    DefaultAssistant,
    ModelInfo,
)
from intric.tokens.token_utils import count_assistant_prompt_tokens
from intric.assistants.assistant import Assistant
from intric.collections.presentation.collection_models import CollectionPublic
from intric.completion_models.presentation.completion_model_assembler import (
    CompletionModelAssembler,
)
from intric.files.file_models import (
    AcceptedFileType,
    FilePublic,
    FileRestrictions,
    Limit,
)
from intric.files.text import TextMimeTypes
from intric.integration.presentation.assemblers.integration_knowledge_assembler import (
    IntegrationKnowledgeAssembler,
)
from intric.mcp_servers.presentation.assemblers.mcp_server_assembler import (
    MCPServerAssembler,
)
from intric.prompts.api.prompt_assembler import PromptAssembler
from intric.questions.question import ToolAssistant, UseTools
from intric.users.user import UserInDB
from intric.websites.presentation.website_models import WebsitePublic

if TYPE_CHECKING:
    from intric.main.models import ResourcePermission


class AssistantAssembler:
    def __init__(self, user: UserInDB, prompt_assembler: PromptAssembler):
        self.user = user
        self.prompt_assembler = prompt_assembler

    def _get_completion_model_sparse(self, model):
        """
        Convert any completion model type to a CompletionModelSparse.
        Returns None if no model is provided.
        """
        if model is None:
            return None

        return CompletionModelAssembler.from_completion_model_to_sparse(completion_model=model)

    def _get_prompt(self, assistant: Assistant):
        return (
            self.prompt_assembler.from_prompt_to_model(assistant.prompt)
            if assistant.prompt
            else None
        )

    def _get_attachments(self, assistant: Assistant):
        return [FilePublic(**attachment.model_dump()) for attachment in assistant.attachments]

    def _get_allowed_attachments(self):
        return FileRestrictions(
            accepted_file_types=[
                AcceptedFileType(mimetype=mimetype, size_limit=26214400)
                for mimetype in TextMimeTypes.values()
            ],
            limit=Limit(max_files=3, max_size=26214400),
        )

    def from_assistant_to_model(
        self,
        assistant: Assistant,
        permissions: list["ResourcePermission"] = None,
    ):
        permissions = permissions or []

        prompt = self._get_prompt(assistant)
        completion_model = self._get_completion_model_sparse(model=assistant.completion_model)
        attachments = self._get_attachments(assistant)
        allowed_attachments = self._get_allowed_attachments()
        tools = UseTools(
            assistants=[
                ToolAssistant(id=tool_assistant.id, handle=tool_assistant.name)
                for tool_assistant in assistant.tool_assistants
            ]
        )

        groups = [CollectionPublic.from_domain(collection=group) for group in assistant.collections]

        integration_knowledge_list = IntegrationKnowledgeAssembler.to_knowledge_model_list(
            items=assistant.integration_knowledge_list
        )

        # Calculate model info
        model_info = None
        if assistant.completion_model:
            prompt_tokens = 0
            if assistant.prompt:
                prompt_text = getattr(assistant.prompt, "prompt", None) or getattr(
                    assistant.prompt, "text", None
                )
                if prompt_text:
                    try:
                        prompt_tokens = count_assistant_prompt_tokens(
                            prompt_text, assistant.completion_model.name
                        )
                    except Exception:
                        # If token counting fails, don't break the response
                        pass

            model_info = ModelInfo(
                name=assistant.completion_model.name,
                token_limit=assistant.completion_model.token_limit,
                prompt_tokens=prompt_tokens,
            )

        return AssistantPublic(
            created_at=assistant.created_at,
            updated_at=assistant.updated_at,
            id=assistant.id,
            space_id=assistant.space_id,
            name=assistant.name,
            prompt=prompt,
            attachments=attachments,
            allowed_attachments=allowed_attachments,
            user=assistant.user,
            groups=groups,
            websites=[WebsitePublic.from_domain(website) for website in assistant.websites],
            integration_knowledge_list=integration_knowledge_list,
            mcp_servers=[
                MCPServerAssembler.to_dict_with_tools(server)
                for server in assistant.mcp_servers
            ],
            mcp_tools=[],  # Initialize as empty - frontend will track changes from current state
            completion_model=completion_model,
            completion_model_kwargs=assistant.completion_model_kwargs,
            logging_enabled=assistant.logging_enabled,
            published=assistant.published,
            tools=tools,
            permissions=permissions,
            description=assistant.description,
            insight_enabled=assistant.insight_enabled,
            type=assistant.type,
            data_retention_days=assistant.data_retention_days,
            metadata_json=assistant.metadata_json,
            model_info=model_info,
            icon_id=assistant.icon_id,
            rag_context_type=assistant.rag_context_type,
            rag_context_value=assistant.rag_context_value,
        )

    def from_assistant_to_default_assistant_model(
        self,
        assistant: Assistant,
        permissions: list["ResourcePermission"],
    ):
        assistant_public = self.from_assistant_to_model(
            assistant=assistant, permissions=permissions
        )

        # We need to check if the assistant is a default assistant
        assistant_data = assistant_public.model_dump()
        if assistant.is_default:
            assistant_data["type"] = AssistantType.DEFAULT_ASSISTANT
        return DefaultAssistant(
            **assistant_data,
        )
