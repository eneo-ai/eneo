import logging
from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional, Union, cast
from uuid import UUID

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.api.assistant_models import AssistantType
from eneo.base.base_entity import Entity
from eneo.completion_models.domain.completion_model import CompletionModel
from eneo.completion_models.infrastructure.completion_service import (
    CompletionContextPreview,
    CompletionService,
)
from eneo.files.file_models import File, FileType
from eneo.files.mime_support import (
    MimeSupport,
    canonicalize_mime,
    classify_mime,
    supported_text_mimes,
)
from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore
from eneo.main.config import get_settings
from eneo.main.exceptions import (
    BadRequestException,
    NoModelSelectedException,
    UnauthorizedException,
)
from eneo.main.models import NOT_PROVIDED, NotProvided, is_provided
from eneo.prompts.prompt import Prompt
from eneo.services.service import DatastoreResult
from eneo.sessions.session import SessionInDB
from eneo.users.user import UserSparse

if TYPE_CHECKING:
    from eneo.ai_models.completion_models.completion_model import (
        CompletionModel as AICompletionModel,
    )
    from eneo.ai_models.completion_models.completion_model import (
        CompletionModelResponse,
    )
    from eneo.assistants.references import ReferencesService
    from eneo.collections.domain.collection import Collection
    from eneo.completion_models.domain.provider_call_observer import (
        ProviderCallObserver,
        ProviderCallReason,
    )
    from eneo.completion_models.domain.skill_activation import SkillActivationRuntime
    from eneo.completion_models.infrastructure.web_search import WebSearchResult
    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.templates.assistant_template.assistant_template import AssistantTemplate
    from eneo.websites.domain.website import Website


UNAUTHORIZED_EXCEPTION_MESSAGE = "Unauthorized. User has no permissions to access."
logger = logging.getLogger(__name__)


_KnowledgeItemList = Sequence[Union["Collection", "Website", "IntegrationKnowledge"]]


class AssistantOrigin(str, Enum):
    USER = "user"
    FLOW_MANAGED = "flow_managed"


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
        attachments: list[File],
        published: bool,
        integration_knowledge_list: list["IntegrationKnowledge"] | None = None,
        mcp_servers: list["MCPServer"] | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        source_template: Optional["AssistantTemplate"] = None,
        is_default: bool = False,
        tool_assistants: list["Assistant"] | None = None,
        description: Optional[str] = None,
        insight_enabled: bool = False,
        data_retention_days: Optional[int] = None,
        metadata_json: dict[str, object] | None = None,
        icon_id: Optional[UUID] = None,
        hidden: bool = False,
        origin: AssistantOrigin = AssistantOrigin.USER,
        managing_flow_id: UUID | None = None,
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
        self._integration_knowledge_list = integration_knowledge_list or []
        self.mcp_servers = mcp_servers or []
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
        self.type = (
            AssistantType.DEFAULT_ASSISTANT if is_default else AssistantType.ASSISTANT
        )
        self._metadata_json = metadata_json
        self.icon_id = icon_id
        self.hidden = hidden
        self.origin = origin
        self.managing_flow_id = managing_flow_id

        # Temporary attributes for update flow - not persisted directly
        self._mcp_server_ids: list[UUID] | None = None
        self._mcp_tool_settings: list[tuple[UUID, bool]] | None = None

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
    def completion_model(self) -> CompletionModel | None:
        return self._completion_model

    @completion_model.setter
    def completion_model(self, model: CompletionModel | None) -> None:
        if model is not None and not model.can_access:
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

    @staticmethod
    def validate_attachments(attachments: list[File]) -> None:
        settings = get_settings()
        max_files = settings.attachment_max_files
        if len(attachments) > max_files:
            raise BadRequestException(f"Too many attachments (max {max_files}).")

        supported_text = frozenset(supported_text_mimes())
        for attachment in attachments:
            mimetype = attachment.mimetype or ""
            state, reason = classify_mime(mimetype)
            if state is MimeSupport.LEGACY_REJECTED:
                raise BadRequestException(
                    reason or "Attachments can only be text files"
                )
            if canonicalize_mime(mimetype) not in supported_text:
                raise BadRequestException("Attachments can only be text files")

        max_size = settings.attachment_max_size_bytes
        if sum(attachment.size for attachment in attachments) > max_size:
            raise BadRequestException(
                f"Attachments exceed the maximum total size of "
                f"{max_size // (1024 * 1024)} MB."
            )

    @attachments.setter
    def attachments(self, attachments: list[File]):
        self.validate_attachments(attachments)
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
    def integration_knowledge_list(
        self, integration_knowledge_list: list["IntegrationKnowledge"]
    ):
        if integration_knowledge_list:
            self._validate_embedding_model(integration_knowledge_list)

        self._integration_knowledge_list = integration_knowledge_list

    @property
    def metadata_json(self) -> dict[str, object] | None:
        return self._metadata_json

    @metadata_json.setter
    def metadata_json(self, metadata_json: dict[str, object] | None):
        self._metadata_json = metadata_json

    def has_knowledge(self) -> bool:
        return bool(
            self.collections or self.websites or self.integration_knowledge_list
        )

    def has_mcp(self) -> bool:
        return bool(self.mcp_servers)

    def _mcp_servers_for_completion(
        self,
        mcp_servers: Sequence["MCPServer"] | None = None,
    ) -> list["MCPServer"]:
        effective_mcp_servers = list(
            self.mcp_servers if mcp_servers is None else mcp_servers
        )
        if self.has_knowledge():
            if effective_mcp_servers:
                logger.warning(
                    "assistant_mcp_suppressed_due_to_knowledge",
                    extra={
                        "assistant_id": str(self.id),
                        "mcp_server_count": len(effective_mcp_servers),
                    },
                )
            return []
        return effective_mcp_servers

    def update(
        self,
        name: str | None = None,
        prompt: Prompt | None = None,
        completion_model: CompletionModel | None | NotProvided = NOT_PROVIDED,
        completion_model_kwargs: ModelKwargs | None = None,
        attachments: list[File] | None = None,
        logging_enabled: bool | None = None,
        collections: list["Collection"] | None = None,
        websites: list["Website"] | None = None,
        integration_knowledge_list: list["IntegrationKnowledge"] | None = None,
        mcp_servers: list["MCPServer"] | None = None,
        published: bool | None = None,
        description: Union[str, None, NotProvided] = NOT_PROVIDED,
        insight_enabled: bool | None = None,
        data_retention_days: Union[int, None, NotProvided] = NOT_PROVIDED,
        metadata_json: Union[dict[str, object], None, NotProvided] = NOT_PROVIDED,
        icon_id: Union[UUID, None, NotProvided] = NOT_PROVIDED,
    ):
        if name is not None:
            self.name = name

        if prompt is not None:
            self.prompt = prompt

        if is_provided(completion_model):
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

        if mcp_servers is not None:
            self.mcp_servers = mcp_servers

        if is_provided(description):
            self.description = description

        if insight_enabled is not None:
            self.insight_enabled = insight_enabled

        if is_provided(data_retention_days):
            self.data_retention_days = data_retention_days

        if is_provided(metadata_json):
            self.metadata_json = metadata_json  # type: ignore[assignment]

        if is_provided(icon_id):
            self.icon_id = icon_id

    def get_prompt_text(self):
        if self.prompt is not None:
            return self.prompt.text

        return ""

    async def preview_response_context(
        self,
        question: str,
        completion_service: "CompletionService",
        files: list[File] | None = None,
        prompt_override: str | None = None,
        version: int = 1,
    ) -> CompletionContextPreview:
        if self.completion_model is None:
            raise NoModelSelectedException()
        completion_model = cast("AICompletionModel", self.completion_model)
        return await completion_service.preview_context(
            model=completion_model,
            text_input=question,
            files=files or [],
            prompt=(
                prompt_override
                if prompt_override is not None
                else self.get_prompt_text()
            ),
            prompt_files=self.attachments,
            version=version,
        )

    async def get_response(
        self,
        question: str,
        completion_service: "CompletionService",
        model_kwargs: ModelKwargs | None = None,
        files: list[File] | None = None,
        info_blob_chunks: list[InfoBlobChunkInDBWithScore] | None = None,
        session: SessionInDB | None = None,
        stream: bool = False,
        extended_logging: bool = False,
        prompt_override: str | None = None,
        prompt: str | None = None,
        version: int = 1,
        reject_context_over_limit: bool = False,
        provider_call_observer: "ProviderCallObserver | None" = None,
        provider_call_reason: "ProviderCallReason" = "initial",
    ) -> "CompletionModelResponse":
        if self.completion_model is None:
            raise NoModelSelectedException()

        completion_model = cast("AICompletionModel", self.completion_model)
        effective_prompt = (
            prompt_override
            if prompt_override is not None
            else prompt or self.get_prompt_text()
        )
        return await completion_service.get_response(
            model=completion_model,
            text_input=question,
            files=files or [],
            prompt=effective_prompt,
            prompt_files=self.attachments,
            info_blob_chunks=info_blob_chunks or [],
            session=session,
            stream=stream,
            extended_logging=extended_logging,
            model_kwargs=model_kwargs,
            version=version,
            mcp_servers=self._mcp_servers_for_completion(),
            reject_context_over_limit=reject_context_over_limit,
            provider_call_observer=provider_call_observer,
            provider_call_reason=provider_call_reason,
        )

    async def ask(
        self,
        question: str,
        completion_service: "CompletionService",
        references_service: "ReferencesService",
        session: Optional["SessionInDB"] = None,
        files: list["File"] | None = None,
        stream: bool = False,
        version: int = 1,
        web_search_results: Sequence["WebSearchResult"] | None = None,
        require_tool_approval: bool = False,
        completion_model_override: Optional[CompletionModel] = None,
        mcp_servers_override: Optional[list["MCPServer"]] = None,
        prompt_override: str | None = None,
        completion_prompt_files: list["File"] | None = None,
        skill_runtime: "SkillActivationRuntime | None" = None,
    ) -> tuple["CompletionModelResponse", DatastoreResult]:
        # Overrides come from the orchestrating service (personal assistant
        # governance). When set, they take precedence over the values stored on
        # the entity. When None, fall back to the entity's own values.
        effective_model = (
            completion_model_override
            if completion_model_override is not None
            else self.completion_model
        )
        if effective_model is None:
            raise NoModelSelectedException()

        completion_model = cast("AICompletionModel", effective_model)
        completion_message_files = files or []
        prompt_files_for_completion = (
            completion_prompt_files
            if completion_prompt_files is not None
            else self.attachments
        )

        if any(
            file.file_type == FileType.IMAGE
            for file in completion_message_files + prompt_files_for_completion
        ):
            if not effective_model.vision:
                raise BadRequestException(
                    f"Completion model {effective_model.name} do not support vision."
                )

        # Fill half the context
        num_chunks = (
            effective_model.max_input_tokens // 200 // 2 if version == 2 else 30
        )

        if self.has_knowledge():
            datastore_result = await references_service.get_references(
                question=question,
                session=session,
                collections=self.collections,
                websites=self.websites,
                integration_knowledge_list=self.integration_knowledge_list,
                num_chunks=num_chunks,
                version=version,
            )
        else:
            datastore_result = DatastoreResult(
                chunks=[], no_duplicate_chunks=[], info_blobs=[]
            )

        effective_mcp_servers = (
            mcp_servers_override
            if mcp_servers_override is not None
            else self.mcp_servers
        )

        response = await completion_service.get_response(
            model=completion_model,
            text_input=question,
            files=completion_message_files,
            prompt=prompt_override
            if prompt_override is not None
            else self.get_prompt_text(),
            prompt_files=prompt_files_for_completion,
            info_blob_chunks=datastore_result.chunks,
            session=session,
            stream=stream,
            extended_logging=self.logging_enabled,
            model_kwargs=self.completion_model_kwargs,
            version=version,
            use_image_generation=self.is_default,
            web_search_results=list(web_search_results or []),
            mcp_servers=self._mcp_servers_for_completion(effective_mcp_servers),
            require_tool_approval=require_tool_approval,
            skill_runtime=skill_runtime,
        )

        return response, datastore_result
