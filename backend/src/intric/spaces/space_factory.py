from typing import TYPE_CHECKING, Iterable, Optional

from intric.apps.apps.app_factory import AppFactory
from intric.collections.domain.collection import Collection
from intric.database.tables.app_table import Apps
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.group_chats_table import GroupChatsTable
from intric.database.tables.service_table import Services
from intric.database.tables.spaces_table import Spaces
from intric.group_chat.domain.factories.group_chat_factory import GroupChatFactory
from intric.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from intric.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from intric.services.service import Service
from intric.spaces.api.space_models import SpaceMember
from intric.spaces.space import Space
from intric.users.user import UserInDBBase
from intric.websites.domain.website import Website

if TYPE_CHECKING:
    from uuid import UUID

    from intric.assistants.assistant_factory import AssistantFactory
    from intric.completion_models.domain.completion_model import CompletionModel
    from intric.database.tables.websites_table import Websites
    from intric.embedding_models.domain.embedding_model import EmbeddingModel
    from intric.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )
    from intric.users.user import UserInDB


class SpaceFactory:
    def __init__(self, assistant_factory: "AssistantFactory", app_factory: AppFactory):
        self.assistant_factory = assistant_factory
        self.app_factory = app_factory

    @staticmethod
    def create_space(
        name: str,
        tenant_id: "UUID",
        tenant_space_id: "UUID" = None,
        description: str = None,
        user_id: "UUID" = None,
    ) -> Space:
        return Space(
            id=None,
            tenant_id=tenant_id,
            tenant_space_id=tenant_space_id,
            user_id=user_id,
            name=name,
            description=description,
            embedding_models=[],
            completion_models=[],
            transcription_models=[],
            default_assistant=None,
            assistants=[],
            group_chats=[],
            apps=[],
            services=[],
            websites=[],
            integration_knowledge_list=[],
            collections=[],
            members={},
        )

    def create_space_from_db(
        self,
        space_in_db: Spaces,
        user: "UserInDB",
        collections_in_db: list[tuple[CollectionsTable, int]] = [],
        websites_in_db: list["Websites"] = [],
        completion_models: list["CompletionModel"] = [],
        embedding_models: list["EmbeddingModel"] = [],
        transcription_models: list["TranscriptionModel"] = [],
        assistants_in_db: list["Assistants"] = [],
        group_chats_in_db: list["GroupChatsTable"] = [],
        apps_in_db: list["Apps"] = [],
        services_in_db: list[Services] = [],
        security_classification: Optional[SecurityClassification] = None,
        integration_knowledge_in_db: Optional[Iterable] = None,
    ) -> Space:
        non_deprecated_completion_models = [
            completion_model
            for completion_model in completion_models
            if not completion_model.is_deprecated
        ]
        non_deprecated_transcription_models = [
            transcription_model
            for transcription_model in transcription_models
            if not transcription_model.is_deprecated
        ]
        non_deprecated_embedding_models = [
            embedding_model
            for embedding_model in embedding_models
            if not embedding_model.is_deprecated
        ]

        # Personal spaces have all models enabled
        if space_in_db.user_id is not None:
            space_completion_models = non_deprecated_completion_models
            space_transcription_models = non_deprecated_transcription_models
            space_embedding_models = non_deprecated_embedding_models
        else:
            space_completion_models = [
                completion_model
                for completion_model in non_deprecated_completion_models
                if completion_model.id
                in [
                    mapping.completion_model_id
                    for mapping in space_in_db.completion_models_mapping
                ]
            ]
            space_transcription_models = [
                transcription_model
                for transcription_model in non_deprecated_transcription_models
                if transcription_model.id
                in [
                    mapping.transcription_model_id
                    for mapping in space_in_db.transcription_models_mapping
                ]
            ]
            space_embedding_models = [
                embedding_model
                for embedding_model in non_deprecated_embedding_models
                if embedding_model.id
                in [
                    mapping.embedding_model_id
                    for mapping in space_in_db.embedding_models_mapping
                ]
            ]

        members = {
            space_user.user_id: SpaceMember(
                **space_user.user.to_dict(), role=space_user.role
            )
            for space_user in space_in_db.members
            if space_user.user.deleted_at is None
        }
        space_collections = [
            Collection.to_domain(
                record=collection,
                embedding_model=next(
                    (
                        embedding_model
                        for embedding_model in embedding_models
                        if embedding_model.id == collection.embedding_model_id
                    ),
                    None,
                ),
                num_info_blobs=info_blob_count,
            )
            for collection, info_blob_count in collections_in_db
        ]
        space_websites = [
            Website.to_domain(
                record=website,
                embedding_model=next(
                    (
                        embedding_model
                        for embedding_model in embedding_models
                        if embedding_model.id == website.embedding_model_id
                    ),
                    None,
                ),
            )
            for website in websites_in_db
        ]

        ik_source = list(integration_knowledge_in_db) if integration_knowledge_in_db is not None \
            else list(getattr(space_in_db, "integration_knowledge_list", []) or [])

        integration_knowledge_list = []
        for i in ik_source:
            integration_knowledge_list.append(
                IntegrationKnowledge(
                    name=i.name,
                    user_integration=getattr(i, "user_integration", None), 
                    embedding_model=next(
                        (em for em in embedding_models if em.id == i.embedding_model_id),
                        None,
                    ),
                    tenant_id=i.tenant_id,
                    space_id=i.space_id,
                    id=i.id,
                    url=getattr(i, "url", None),
                    size=getattr(i, "size", None),
                )
            )

        all_assistants = [
            self.assistant_factory.create_space_assistant_from_db(
                assistant_in_db=assistant,
                completion_models=completion_models,
                collections=space_collections,
                websites=space_websites,
                integration_knowledge_list=integration_knowledge_list,
                user=user,
            )
            for assistant in assistants_in_db
        ]
        default_assistant = next(
            (assistant for assistant in all_assistants if assistant.is_default), None
        )
        space_assistants = [
            assistant
            for assistant in all_assistants
            if (not default_assistant or assistant.id != default_assistant.id)
        ]
        # Set the tools of the default assistant
        if default_assistant is not None:
            default_assistant.tool_assistants = space_assistants

        space_apps = [
            self.app_factory.create_space_app_from_db(
                app_in_db=app,
                completion_models=completion_models,
                transcription_models=transcription_models,
            )
            for app in apps_in_db
        ]
        space_group_chats = [
            GroupChatFactory.create_group_chat_from_db(
                group_chat_db=group_chat,
                assistants=space_assistants,
            )
            for group_chat in group_chats_in_db
        ]

        space_services = [
            Service(
                **service.to_dict(),
                user=UserInDBBase.model_validate(service.user),
                completion_model=next(
                    (
                        model
                        for model in completion_models
                        if model.id == service.completion_model_id
                    ),
                    None,
                ),
                groups=[
                    group
                    for group in space_collections
                    if group.id
                    in [
                        service_group.group_id
                        for service_group in service.service_groups
                    ]
                ],
            )
            for service in services_in_db
        ]

        if security_classification is not None:
            security_classification = SecurityClassification.to_domain(
                security_classification
            )

        return Space(
            created_at=space_in_db.created_at,
            updated_at=space_in_db.updated_at,
            id=space_in_db.id,
            tenant_id=space_in_db.tenant_id,
            tenant_space_id=space_in_db.tenant_space_id,
            user_id=space_in_db.user_id,
            name=space_in_db.name,
            description=space_in_db.description,
            embedding_models=space_embedding_models,
            transcription_models=space_transcription_models,
            completion_models=space_completion_models,
            default_assistant=default_assistant,
            assistants=space_assistants,
            group_chats=space_group_chats,
            apps=space_apps,
            services=space_services,
            integration_knowledge_list=integration_knowledge_list,
            collections=space_collections,
            websites=space_websites,
            members=members,
            security_classification=security_classification,
        )
