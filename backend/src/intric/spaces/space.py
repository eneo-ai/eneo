from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional, Union
from uuid import UUID

from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from intric.main.models import NOT_PROVIDED, NotProvided
from intric.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from intric.spaces.api.space_models import SpaceMember, SpaceRoleValue
from intric.transcription_models.domain.transcription_model import TranscriptionModel

if TYPE_CHECKING:
    from intric.ai_models.ai_model import AIModel
    from intric.apps import App
    from intric.assistants.assistant import Assistant
    from intric.collections.domain.collection import Collection
    from intric.completion_models.domain import CompletionModel
    from intric.embedding_models.domain.embedding_model import EmbeddingModel
    from intric.group_chat.domain.entities.group_chat import GroupChat
    from intric.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from intric.services.service import Service
    from intric.websites.domain.website import Website

UNAUTHORIZED_EXCEPTION_MESSAGE = "Unauthorized. User has no permissions to access."
SECURITY_CLASSIFICATION_EXCEPTION_MESSAGE = (
    "Security classification is not compatible with the space."
)


class SpacePermissionsActions(Enum):
    READ = "read"
    EDIT = "edit"
    DELETE = "delete"


class Space:
    def __init__(
        self,
        id: UUID | None,
        tenant_id: UUID | None,
        tenant_space_id: UUID | None,
        user_id: UUID | None,
        name: str,
        description: str | None,
        embedding_models: list["EmbeddingModel"],
        completion_models: list["CompletionModel"],
        transcription_models: list[TranscriptionModel],
        default_assistant: "Assistant",
        assistants: list["Assistant"],
        apps: list["App"],
        services: list["Service"],
        websites: list["Website"],
        collections: list["Collection"],
        integration_knowledge_list: list["IntegrationKnowledge"],
        members: dict[UUID, SpaceMember],
        created_at: datetime = None,
        updated_at: datetime = None,
        group_chats: Optional[list["GroupChat"]] = [],
        security_classification: Optional[SecurityClassification] = None,
    ):
        self.id = id
        self.tenant_id = tenant_id
        self.tenant_space_id = tenant_space_id
        self.user_id = user_id
        self.name = name
        self.description = description
        self._embedding_models = embedding_models
        self._completion_models = completion_models
        self._transcription_models = transcription_models
        self.default_assistant = default_assistant
        self.assistants = assistants
        self.group_chats = group_chats
        self.apps = apps
        self.services = services
        self.websites = websites
        self.collections = collections
        self.integration_knowledge_list = integration_knowledge_list
        self.members = members
        self.created_at = created_at
        self.updated_at = updated_at
        self.security_classification = security_classification

    def _get_member_ids(self):
        return self.members.keys()

    def is_personal(self):
        return self.user_id is not None

    def is_organization(self):
        return (self.user_id is None) and (self.tenant_space_id is None)
    
    def is_embedding_model_in_space(self, embedding_model_id: UUID | None) -> bool:
        return embedding_model_id in [model.id for model in self.embedding_models]

    def is_completion_model_in_space(self, completion_model_id: UUID | None) -> bool:
        if completion_model_id is None:
            return False
        return any(m.id == completion_model_id for m in self.completion_models)

    def is_transcription_model_in_space(self, transcription_model_id: UUID | None) -> bool:
        return transcription_model_id in [model.id for model in self.transcription_models]

    def is_completion_model_available(self, completion_model_id: UUID) -> bool:
        return (
            self.is_completion_model_in_space(completion_model_id)
            and self.get_completion_model(completion_model_id).can_access
        )

    def is_embedding_model_available(self, embedding_model_id: UUID) -> bool:
        return (
            self.is_embedding_model_in_space(embedding_model_id)
            and self.get_embedding_model(embedding_model_id).can_access
        )

    def is_transcription_model_available(self, transcription_model_id: UUID) -> bool:
        return (
            self.is_transcription_model_in_space(transcription_model_id)
            and self.get_transcription_model(transcription_model_id).can_access
        )

    def is_group_in_space(self, group_id: UUID) -> bool:
        return group_id in [group.id for group in self.collections]

    def is_website_in_space(self, website_id: UUID) -> bool:
        return website_id in [website.id for website in self.websites]

    def is_integration_knowledge_in_space(self, integration_knowledge_id: UUID) -> bool:
        return integration_knowledge_id in [i.id for i in self.integration_knowledge_list]

    def get_member(self, member_id: UUID) -> SpaceMember:
        return self.members[member_id]

    def get_latest_embedding_model(self) -> "EmbeddingModel":
        if not self.embedding_models:
            return

        sorted_embedding_models = sorted(
            [
                embedding_model
                for embedding_model in self.embedding_models
                if embedding_model.can_access
            ],
            key=lambda model: model.created_at,
            reverse=True,
        )

        if not sorted_embedding_models:
            raise NotFoundException("No embedding models found in the space")

        return sorted_embedding_models[0]  # type: ignore

    def get_latest_completion_model(self) -> "CompletionModel":
        if not self.completion_models:
            return

        sorted_completion_models = sorted(
            [
                completion_model
                for completion_model in self.completion_models
                if completion_model.can_access
            ],
            key=lambda model: model.created_at,
            reverse=True,
        )

        if not sorted_completion_models:
            raise NotFoundException("No completion models found in the space")

        return sorted_completion_models[0]  # type: ignore

    def get_latest_transcription_model(self) -> TranscriptionModel:
        if not self.transcription_models:
            return

        sorted_transcription_models = sorted(
            [
                transcription_model
                for transcription_model in self.transcription_models
                if transcription_model.can_access
            ],
            key=lambda model: model.created_at,
            reverse=True,
        )

        if not sorted_transcription_models:
            raise NotFoundException("No transcription models found in the space")

        return sorted_transcription_models[0]  # type: ignore

    def get_default_completion_model(self) -> Optional["CompletionModel"]:
        if not self.completion_models:
            return None

        model = filter(lambda m: m.is_org_default and m.can_access, self.completion_models)
        default_model = next(model, None)

        if default_model is None:
            model = filter(
                lambda m: m.name == "gpt-4o" and m.can_access,
                self.completion_models,
            )

            default_model = next(model, None)

            if default_model is None:
                default_model = self.get_latest_completion_model()

        return default_model

    def get_default_embedding_model(self) -> Optional["EmbeddingModel"]:
        return self.get_latest_embedding_model()

    def get_default_transcription_model(self) -> Optional[TranscriptionModel]:
        """Get the default transcription model from the space.
        Returns the default model if it exists, otherwise returns the latest model."""
        if not self.transcription_models:
            return None

        # First try to get the org default model
        model = filter(lambda m: m.is_org_default and m.can_access, self.transcription_models)
        default_model = next(model, None)

        if default_model is not None:
            return default_model

        # Get the most recently added model as a fallback
        return self.get_latest_transcription_model()

    @property
    def embedding_models(self):
        return self._embedding_models

    @embedding_models.setter
    def embedding_models(self, embedding_models: list["EmbeddingModel"]):
        for model in embedding_models:
            if not model.can_access:
                raise UnauthorizedException(UNAUTHORIZED_EXCEPTION_MESSAGE)
            self.validate_model_security_compatibility(model)

        self._embedding_models = embedding_models

    @property
    def completion_models(self) -> list["CompletionModel"]:
        return self._completion_models

    @completion_models.setter
    def completion_models(self, completion_models: list["CompletionModel"]):
        for model in completion_models:
            if not model.can_access:
                raise UnauthorizedException(UNAUTHORIZED_EXCEPTION_MESSAGE)
            self.validate_model_security_compatibility(model)
        self._completion_models = completion_models

    @property
    def transcription_models(self) -> list[TranscriptionModel]:
        return self._transcription_models

    @transcription_models.setter
    def transcription_models(self, transcription_models: list[TranscriptionModel]):
        for model in transcription_models:
            if not model.can_access:
                raise UnauthorizedException(UNAUTHORIZED_EXCEPTION_MESSAGE)
            self.validate_model_security_compatibility(model)

        self._transcription_models = transcription_models

    def update(
        self,
        name: str = None,
        description: str = None,
        embedding_models: list["EmbeddingModel"] = None,
        completion_models: list["CompletionModel"] = None,
        transcription_models: list[TranscriptionModel] = None,
        security_classification: Union[SecurityClassification, NotProvided, None] = NOT_PROVIDED,
    ):
        if name is not None:
            if self.is_personal():
                raise BadRequestException("Can not change name of personal space")

            self.name = name

        if description is not None:
            if self.is_personal():
                raise BadRequestException("Can not change description of personal space")

            self.description = description
        # Only if security_classification_enabled on tenant (checked in service layer)
        if security_classification is not NOT_PROVIDED:
            if self.is_personal():
                raise BadRequestException(
                    "Can not change security classification of personal space"
                )
            self.security_classification = security_classification
            if self.security_classification is not None:
                self.completion_models = [
                    model
                    for model in self.completion_models
                    if not self.security_classification.is_greater_than(
                        model.security_classification
                    )
                ]
                self.embedding_models = [
                    model
                    for model in self.embedding_models
                    if not self.security_classification.is_greater_than(
                        model.security_classification
                    )
                ]
                self.transcription_models = [
                    model
                    for model in self.transcription_models
                    if not self.security_classification.is_greater_than(
                        model.security_classification
                    )
                ]

        if completion_models is not None:
            if self.is_personal():
                raise BadRequestException("Can not add completion models to personal space")

            self.completion_models = completion_models

        if embedding_models is not None:
            if self.is_personal():
                raise BadRequestException("Can not add embedding models to personal space")

            self.embedding_models = embedding_models

        if transcription_models is not None:
            if self.is_personal():
                raise BadRequestException("Can not add transcription models to personal space")

            self.transcription_models = transcription_models

    def add_member(self, user: SpaceMember):
        if self.is_personal():
            raise BadRequestException("Can not add members to personal space")

        if user.id in self._get_member_ids():
            raise BadRequestException("User is already a member of the space")

        self.members[user.id] = user

    def remove_member(self, user_id: UUID):
        if user_id not in self._get_member_ids():
            raise BadRequestException("User is not a member of the space")

        del self.members[user_id]

    def change_member_role(self, user_id: UUID, new_role: SpaceRoleValue):
        if user_id not in self._get_member_ids():
            raise BadRequestException("User is not a member of the space")

        self.members[user_id].role = new_role

    def add_website(self, website: "Website"):
        if not self.is_embedding_model_in_space(website.embedding_model.id):
            raise BadRequestException("Embedding model is not in the space")

        if any(w.id == website.id for w in self.websites):
            return

        self.websites.append(website)

    def remove_website(self, website: "Website"):
        for assistant in self.assistants:
            assistant.websites = [w for w in assistant.websites if w.id != website.id]

        self.websites.remove(website)

    def add_group_chat(self, group_chat: "GroupChat"):
        self.group_chats.append(group_chat)

    def remove_group_chat(self, group_chat: "GroupChat"):
        self.group_chats.remove(group_chat)

    def add_assistant(self, assistant: "Assistant"):
        if assistant.id in [a.id for a in self.assistants]:
            raise BadRequestException("Assistant is already in the space")

        cm = getattr(assistant, "completion_model", None)
        if cm is None or getattr(cm, "id", None) is None:
            raise BadRequestException("Assistant has no completion model assigned")

        if not self.is_completion_model_in_space(cm.id):
            self.add_completion_model(cm)

        self.assistants.append(assistant)

    def remove_assistant(self, assistant: "Assistant"):
        for group_chat in self.group_chats:
            if assistant.id in [a.assistant.id for a in group_chat.assistants]:
                group_chat.assistants.remove(assistant)

        self.assistants.remove(assistant)


    def add_collection_owner_move(self, collection: "Collection"):
        """Byter ägare på en collection till detta space (uppdaterar FK i DB). 
        Använd INTE för import/delning."""

        if collection.id in [_c.id for _c in self.collections]:
            raise BadRequestException("Collection is already owned by the space")
        if not self.is_embedding_model_in_space(collection.embedding_model.id):
            raise BadRequestException("Embedding model is not in the space")
        self.collections.append(collection)
        
    def remove_collection(self, collection: "Collection"):
        for assistant in self.assistants:
            assistant.collections = [
                c for c in assistant.collections if c.id != collection.id
            ]

        self.collections = [c for c in self.collections if c.id != collection.id]

    def can_use_knowledge(
        self, knowledge: list[Union["Website", "Collection", "IntegrationKnowledge"]]
    ) -> bool:
        for knowledge_item in knowledge:
            if not self.is_embedding_model_available(knowledge_item.embedding_model.id):
                return False
            if self.security_classification is not None:
                if self.security_classification.is_greater_than(
                    knowledge_item.embedding_model.security_classification
                ):
                    return False

        return True

    def can_ask_assistant(self, assistant: "Assistant") -> bool:
        if not self.is_completion_model_available(assistant.completion_model.id):
            return False
        if not self.can_use_knowledge(
            assistant.collections + assistant.websites + assistant.integration_knowledge_list
        ):
            return False
        if self.security_classification is not None:
            if self.security_classification.is_greater_than(
                assistant.completion_model.security_classification
            ):
                return False

        return True

    def can_run_app(self, app: "App") -> bool:
        if not self.is_completion_model_available(app.completion_model.id):
            return False
        if not self.is_transcription_model_available(app.transcription_model.id):
            return False
        if self.security_classification is not None:
            if self.security_classification.is_greater_than(
                app.completion_model.security_classification
            ):
                return False
            if self.security_classification.is_greater_than(
                app.transcription_model.security_classification
            ):
                return False

        return True

    def can_use_service(self, service: "Service") -> bool:
        if not self.is_completion_model_available(service.completion_model.id):
            return False
        if self.security_classification is not None:
            if self.security_classification.is_greater_than(
                service.completion_model.security_classification
            ):
                return False

        return True

    def _get_entity(self, entity_id: UUID, entity_list: list[Any]):
        for entity in entity_list:
            if entity.id == entity_id:
                return entity

        raise NotFoundException()

    def get_assistant(self, assistant_id: UUID) -> "Assistant":
        # Check if the user wants the default assistant
        if self.default_assistant and self.default_assistant.id == assistant_id:
            return self.default_assistant

        return self._get_entity(assistant_id, self.assistants)

    def get_group_chat(self, group_chat_id: UUID) -> "GroupChat":
        return self._get_entity(group_chat_id, self.group_chats)

    def get_app(self, app_id: UUID) -> "App":
        return self._get_entity(app_id, self.apps)

    def get_service(self, service_id: UUID) -> "Service":
        return self._get_entity(service_id, self.services)

    def get_collection(self, collection_id: UUID) -> "Collection":
        return self._get_entity(collection_id, self.collections)

    def get_integration_knowledge(self, integration_knowledge_id: UUID) -> "IntegrationKnowledge":
        return self._get_entity(integration_knowledge_id, self.integration_knowledge_list)

    def get_transcription_model(self, transcription_model_id: UUID) -> "TranscriptionModel":
        return self._get_entity(transcription_model_id, self.transcription_models)

    def get_completion_model(self, completion_model_id: UUID) -> "CompletionModel":
        return self._get_entity(completion_model_id, self.completion_models)

    def get_embedding_model(self, embedding_model_id: UUID) -> "EmbeddingModel":
        return self._get_entity(embedding_model_id, self.embedding_models)

    def get_website(self, website_id: UUID) -> "Website":
        return self._get_entity(website_id, self.websites)

    def validate_model_security_compatibility(self, model: "AIModel") -> None:
        if not self.security_classification:
            return
        if self.security_classification.is_greater_than(model.security_classification):
            raise BadRequestException(SECURITY_CLASSIFICATION_EXCEPTION_MESSAGE)

    def add_completion_model(self, model: "CompletionModel"):
        if model is None or getattr(model, "id", None) is None:
            raise BadRequestException("Invalid completion model")

        if hasattr(model, "can_access") and not model.can_access:
            raise BadRequestException("Completion model is not accessible")

        if any(m.id == model.id for m in self.completion_models):
            return

        self.completion_models.append(model)