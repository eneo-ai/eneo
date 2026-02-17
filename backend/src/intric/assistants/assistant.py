from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Union
from uuid import UUID

from intric.ai_models.completion_models.completion_model import (
    CompletionModelPublic,
    ModelKwargs,
)
from intric.assistants.api.assistant_models import AssistantType, RagContextType
from intric.base.base_entity import Entity
from intric.completion_models.domain.completion_model import CompletionModel
from intric.completion_models.infrastructure.completion_service import CompletionService
from intric.files.file_models import File, FileInfo, FileType
from intric.files.text import TextMimeTypes
from intric.info_blobs.info_blob import InfoBlobChunkInDBWithScore
from intric.main.exceptions import (
    BadRequestException,
    NoModelSelectedException,
    UnauthorizedException,
)
from intric.main.models import NOT_PROVIDED, NotProvided
from intric.prompts.prompt import Prompt
from intric.sessions.session import SessionInDB
from intric.users.user import UserSparse

if TYPE_CHECKING:
    from intric.assistants.references import ReferencesService
    from intric.collections.domain.collection import Collection
    from intric.completion_models.infrastructure.web_search import WebSearchResult
    from intric.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from intric.templates.assistant_template.assistant_template import AssistantTemplate
    from intric.websites.domain.website import Website


UNAUTHORIZED_EXCEPTION_MESSAGE = "Unauthorized. User has no permissions to access."


_KnowledgeItemList = List[Union["Collection", "Website", "IntegrationKnowledge"]]


class Assistant(Entity):
    def __init__(
        self,
        id: UUID | None,
        user: UserSparse | None,
        space_id: UUID,
        completion_model: CompletionModel | None,
        name: str,
        prompt: Prompt | None,
        completion_model_kwargs: ModelKwargs,
        logging_enabled: bool,
        websites: list["Website"],
        collections: list["Collection"],
        attachments: list[FileInfo],
        published: bool,
        integration_knowledge_list: list["IntegrationKnowledge"] = [],
        created_at: datetime = None,
        updated_at: datetime = None,
        source_template: Optional["AssistantTemplate"] = None,
        is_default: bool = False,
        tool_assistants: list["Assistant"] = None,
        description: Optional[str] = None,
        insight_enabled: bool = False,
        data_retention_days: Optional[int] = None,
        metadata_json: Optional[dict] = {},
        icon_id: Optional[UUID] = None,
        rag_context_type: Optional[RagContextType] = None,
        rag_context_value: Optional[int] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)

        self.user = user
        self.space_id = space_id
        self._completion_model = completion_model
        self.name = name
        self.prompt = prompt
        self.completion_model_kwargs = completion_model_kwargs
        self.logging_enabled = logging_enabled
        self._websites = websites
        self._collections = collections
        self._integration_knowledge_list = integration_knowledge_list
        self.created_at = created_at
        self.updated_at = updated_at
        self._attachments = attachments
        self.source_template = source_template
        self.published = published
        self.is_default = is_default
        self.tool_assistants = tool_assistants or []
        self.description = description
        self.insight_enabled = insight_enabled
        self.data_retention_days = data_retention_days
        self.type = AssistantType.DEFAULT_ASSISTANT if is_default else AssistantType.ASSISTANT
        self._metadata_json = metadata_json
        self.icon_id = icon_id
        self.rag_context_type = rag_context_type
        self.rag_context_value = rag_context_value

    def _validate_embedding_model(self, items: _KnowledgeItemList):
        embedding_model_id_set = set([item.embedding_model.id for item in items])
        if len(embedding_model_id_set) != 1 or (
            self.embedding_model_id is not None
            and embedding_model_id_set.pop() != self.embedding_model_id
        ):
            raise BadRequestException(
                """All websites or groups or integration_knowledge_list
                    must have the same embedding model"""
            )

    def _set_collections_and_websites(
        self, collections: list["Collection"] | None, websites: list["Website"] | None
    ):
        if collections is None and websites is None:
            return

        elif collections is not None and websites is not None:
            self._collections.clear()
            self._websites.clear()

            self.collections = collections
            self.websites = websites

        elif collections is not None:
            self.collections = collections

        elif websites is not None:
            self.websites = websites

    @property
    def completion_model(self):
        return self._completion_model

    @completion_model.setter
    def completion_model(self, model: CompletionModelPublic):
        if not model.can_access:
            raise UnauthorizedException(UNAUTHORIZED_EXCEPTION_MESSAGE)

        self._completion_model = model

    @property
    def embedding_model_id(self):
        if not self.websites and not self.collections:
            return None

        if self.websites:
            return self.websites[0].embedding_model.id

        if self.collections:
            return self.collections[0].embedding_model.id

    @property
    def attachments(self):
        return self._attachments

    @attachments.setter
    def attachments(self, attachments: list[FileInfo]):
        for attachment in attachments:
            if not TextMimeTypes.has_value(attachment.mimetype):
                raise BadRequestException("Attachements can only be text files")

        if sum(attachment.size for attachment in attachments) > 26214400:
            raise BadRequestException("Files too large!")

        self._attachments = attachments

    @property
    def websites(self):
        return self._websites

    @websites.setter
    def websites(self, websites: list["Website"]):
        self._websites.clear()

        if websites:
            self._validate_embedding_model(websites)

        self._websites = websites

    @property
    def collections(self):
        return self._collections

    @collections.setter
    def collections(self, collections: list["Collection"]):
        self._collections.clear()

        if collections:
            self._validate_embedding_model(collections)

        self._collections = collections

    @property
    def integration_knowledge_list(self):
        return self._integration_knowledge_list

    @integration_knowledge_list.setter
    def integration_knowledge_list(self, integration_knowledge_list: list["IntegrationKnowledge"]):
        if integration_knowledge_list:
            self._validate_embedding_model(integration_knowledge_list)

        self._integration_knowledge_list = integration_knowledge_list

    @property
    def metadata_json(self):
        return self._metadata_json

    @metadata_json.setter
    def metadata_json(self, metadata_json: dict):
        self._metadata_json = metadata_json

    def has_knowledge(self) -> bool:
        return self.collections or self.websites or self.integration_knowledge_list

    def update(
        self,
        name: str | None = None,
        prompt: Prompt | None = None,
        completion_model: CompletionModel | None = None,
        completion_model_kwargs: ModelKwargs | None = None,
        attachments: list[FileInfo] | None = None,
        logging_enabled: bool | None = None,
        collections: list["Collection"] | None = None,
        websites: list["Website"] | None = None,
        integration_knowledge_list: list["IntegrationKnowledge"] | None = None,
        published: bool | None = None,
        description: Union[str, None, NotProvided] = NOT_PROVIDED,
        insight_enabled: bool | None = None,
        data_retention_days: Union[int, None, NotProvided] = NOT_PROVIDED,
        metadata_json: Union[dict, None, NotProvided] = NOT_PROVIDED,
        icon_id: Union[UUID, None, NotProvided] = NOT_PROVIDED,
        rag_context_type: Union[RagContextType, None, NotProvided] = NOT_PROVIDED,
        rag_context_value: Union[int, None, NotProvided] = NOT_PROVIDED,
    ):
        if name is not None:
            self.name = name

        if prompt is not None:
            self.prompt = prompt

        if completion_model is not None:
            self.completion_model = completion_model

        if completion_model_kwargs is not None:
            self.completion_model_kwargs = completion_model_kwargs

        if attachments is not None:
            self.attachments = attachments

        if logging_enabled is not None:
            self.logging_enabled = logging_enabled

        if published is not None:
            self.published = published

        self._set_collections_and_websites(collections=collections, websites=websites)

        if integration_knowledge_list is not None:
            self.integration_knowledge_list = integration_knowledge_list

        if description is not NOT_PROVIDED:
            self.description = description

        if insight_enabled is not None:
            self.insight_enabled = insight_enabled

        if data_retention_days is not NOT_PROVIDED:
            self.data_retention_days = data_retention_days

        if metadata_json is not NOT_PROVIDED:
            self.metadata_json = metadata_json

        if icon_id is not NOT_PROVIDED:
            self.icon_id = icon_id
        
        if rag_context_type is not NOT_PROVIDED:
            self.rag_context_type = rag_context_type

        if rag_context_value is not NOT_PROVIDED:
            self.rag_context_value = rag_context_value

    def get_prompt_text(self):
        if self.prompt is not None:
            return self.prompt.text

        return ""
    
    def _get_retrieval_params(self, version: int = 1) -> dict:
        """
        Get retrieval parameters for RAG based on context settings.

        Returns a dict with:
        - num_chunks: number of chunks to retrieve
        - autocut_cutoff: if set, use autocut to filter by relevance jumps

        The calculation depends on the rag_context_type:
        - None (default): Use half of model's context length (50%)
        - PERCENTAGE: Use a percentage (1-100) of model's context length
        - FIXED_CHUNKS: Use a fixed number of chunks
        - AUTO_RELEVANCE: Fetch many chunks and use autocut to filter by relevance

        For version 1, always returns 30 chunks with autocut_cutoff=3 (legacy behavior).
        """
        if version != 2:
            return dict(num_chunks=30, autocut_cutoff=3)

        token_limit = self.completion_model.token_limit
        tokens_per_chunk = 200  # Approximate tokens per chunk

        # Use a percentage of the context
        if self.rag_context_type == RagContextType.PERCENTAGE:
            percentage = self.rag_context_value or 50  # Default to 50% if not set
            percentage = max(1, min(100, percentage))  # Clamp to 1-100
            num_chunks = token_limit // tokens_per_chunk * percentage // 100
            return dict(num_chunks=num_chunks, autocut_cutoff=None)

        # Use a fixed number of chunks
        if self.rag_context_type == RagContextType.FIXED_CHUNKS:
            num_chunks = self.rag_context_value or 30  # Default to 30 chunks if not set
            return dict(num_chunks=num_chunks, autocut_cutoff=None)

        # Auto-relevance: fetch generously and let autocut prune by score jumps
        if self.rag_context_type == RagContextType.AUTO_RELEVANCE:
            # Fetch up to half the context worth of chunks; autocut will trim
            num_chunks = token_limit // tokens_per_chunk // 2
            return dict(num_chunks=num_chunks, autocut_cutoff=3)

        # Default behavior (None): use half the context
        num_chunks = token_limit // tokens_per_chunk // 2
        return dict(num_chunks=num_chunks, autocut_cutoff=None)

    async def get_response(
        self,
        question: str,
        completion_service: "CompletionService",
        model_kwargs: ModelKwargs | None = None,
        files: list[File] = [],
        info_blob_chunks: list[InfoBlobChunkInDBWithScore] = [],
        session: SessionInDB | None = None,
        stream: bool = False,
        extended_logging: bool = False,
        prompt: str | None = None,
    ):
        if self.completion_model is None:
            raise NoModelSelectedException()

        return await completion_service.get_response(
            model=self.completion_model,
            text_input=question,
            files=files,
            prompt=prompt or self.get_prompt_text(),
            prompt_files=self.attachments,
            info_blob_chunks=info_blob_chunks,
            session=session,
            stream=stream,
            extended_logging=extended_logging,
            model_kwargs=model_kwargs,
        )

    async def ask(
        self,
        question: str,
        completion_service: "CompletionService",
        references_service: "ReferencesService",
        session: Optional["SessionInDB"] = None,
        files: list["File"] = [],
        stream: bool = False,
        version: int = 1,
        web_search_results: list["WebSearchResult"] = [],
    ):
        if any([file.file_type == FileType.IMAGE for file in files]):
            if not self.completion_model.vision:
                raise BadRequestException(
                    f"Completion model {self.completion_model.name} do not support vision."
                )

        # Calculate retrieval params based on RAG context settings
        retrieval_params = self._get_retrieval_params(version=version)

        datastore_result = await references_service.get_references(
            question=question,
            session=session,
            collections=self.collections,
            websites=self.websites,
            integration_knowledge_list=self.integration_knowledge_list,
            num_chunks=retrieval_params["num_chunks"],
            autocut_cutoff=retrieval_params["autocut_cutoff"],
            version=version,
        )

        response = await completion_service.get_response(
            model=self.completion_model,
            text_input=question,
            files=files,
            prompt=self.get_prompt_text(),
            prompt_files=self.attachments,
            info_blob_chunks=datastore_result.chunks,
            session=session,
            stream=stream,
            extended_logging=self.logging_enabled,
            model_kwargs=self.completion_model_kwargs,
            version=version,
            use_image_generation=self.is_default,
            web_search_results=web_search_results,
        )

        return response, datastore_result
