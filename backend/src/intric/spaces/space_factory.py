from collections.abc import Callable, Iterable, Sequence
from typing import TYPE_CHECKING, Optional, TypeVar, cast
from uuid import UUID

from pydantic import ValidationError

from intric.apps.apps.app_factory import AppFactory
from intric.collections.domain.collection import Collection
from intric.database.tables.app_table import Apps
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.group_chats_table import GroupChatsTable
from intric.database.tables.service_table import Services
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.users_table import Users
from intric.group_chat.domain.factories.group_chat_factory import GroupChatFactory
from intric.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from intric.main.logging import get_logger
from intric.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from intric.services.service import Service
from intric.spaces.api.space_models import SpaceGroupMember, SpaceMember, SpaceRoleValue
from intric.spaces.space import Space
from intric.user_groups.user_group import UserGroupState
from intric.users.user import UserInDBBase, UserSparse
from intric.websites.domain.website import Website

logger = get_logger(__name__)

RowT = TypeVar("RowT")
T = TypeVar("T")


def _build_or_skip(
    rows: Iterable[RowT],
    *,
    item_kind: str,
    build_fn: Callable[[RowT], T],
) -> list[T]:
    """Build domain objects per DB row, skipping any that fail Pydantic validation.

    A single legacy or corrupt row (e.g. a JSONB column the domain model now
    rejects) must not crash the entire space load. We log the offending row's
    identifying fields so it can be triaged downstream, then continue with the
    rest. Non-validation errors propagate — they signal a real bug, not data drift.

    Log keys are stable across item kinds (`space_item_kind`, `space_item_id`,
    `space_item_tenant_id`, `space_item_user_id`, `space_item_space_id`,
    `validation_error_count`) so dashboards and alerts can match on a single
    schema rather than per-domain field names. Pydantic error payloads are
    redacted (no `input`, no `url`) to avoid leaking row data into logs.
    """
    built: list[T] = []
    for row in rows:
        try:
            built.append(build_fn(row))
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_url=False)
            logger.exception(
                "Skipping invalid %s row while loading space",
                item_kind,
                extra={
                    "space_item_kind": item_kind,
                    "space_item_id": getattr(row, "id", None),
                    "space_item_tenant_id": getattr(row, "tenant_id", None),
                    "space_item_user_id": getattr(row, "user_id", None),
                    "space_item_space_id": getattr(row, "space_id", None),
                    "validation_error_count": len(errors),
                    "validation_errors": errors,
                },
            )
    return built


if TYPE_CHECKING:
    from intric.assistants.assistant_factory import AssistantFactory
    from intric.completion_models.domain.completion_model import CompletionModel
    from intric.database.tables.integration_table import (
        IntegrationKnowledge as IntegrationKnowledgeDBModel,
    )
    from intric.database.tables.security_classifications_table import (
        SecurityClassification as SecurityClassificationDBModel,
    )
    from intric.database.tables.websites_table import Websites
    from intric.embedding_models.domain.embedding_model import EmbeddingModel
    from intric.groups_legacy.api.group_models import GroupInDBBase
    from intric.integration.domain.entities.sharepoint_subscription import (
        SharePointSubscription as DomainSharePointSubscription,
    )
    from intric.integration.domain.entities.user_integration import UserIntegration
    from intric.mcp_servers.domain.entities.mcp_server import MCPServer
    from intric.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )
    from intric.users.user import UserInDB


class SpaceFactory:
    def __init__(self, assistant_factory: "AssistantFactory", app_factory: AppFactory):
        super().__init__()
        self.assistant_factory = assistant_factory
        self.app_factory = app_factory

    @staticmethod
    def create_space(
        name: str,
        tenant_id: "UUID",
        tenant_space_id: Optional["UUID"] = None,
        description: Optional[str] = None,
        user_id: Optional["UUID"] = None,
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
            mcp_servers=[],
            default_assistant=None,
            assistants=[],
            group_chats=[],
            apps=[],
            services=[],
            websites=[],
            integration_knowledge_list=[],
            collections=[],
            members={},
            group_members={},
        )

    def create_space_from_db(
        self,
        space_in_db: Spaces,
        user: "UserInDB",
        collections_in_db: Sequence[tuple[CollectionsTable, int]] | None = None,
        websites_in_db: Sequence["Websites"] | None = None,
        completion_models: Sequence["CompletionModel"] | None = None,
        embedding_models: Sequence["EmbeddingModel"] | None = None,
        transcription_models: Sequence["TranscriptionModel"] | None = None,
        mcp_servers: Sequence["MCPServer"] | None = None,
        assistants_in_db: Sequence["Assistants"] | None = None,
        group_chats_in_db: Sequence["GroupChatsTable"] | None = None,
        apps_in_db: Sequence["Apps"] | None = None,
        services_in_db: Sequence[Services] | None = None,
        security_classification: Optional["SecurityClassificationDBModel"] = None,
        integration_knowledge_in_db: Iterable["IntegrationKnowledgeDBModel"]
        | None = None,
    ) -> Space:
        collections_in_db = list(collections_in_db or [])
        websites_in_db = list(websites_in_db or [])
        completion_models = list(completion_models or [])
        embedding_models = list(embedding_models or [])
        transcription_models = list(transcription_models or [])
        mcp_servers = list(mcp_servers or [])
        assistants_in_db = list(assistants_in_db or [])
        group_chats_in_db = list(group_chats_in_db or [])
        apps_in_db = list(apps_in_db or [])
        services_in_db = list(services_in_db or [])
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
            space_mcp_servers = mcp_servers
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
            space_mcp_servers = [
                mcp_server
                for mcp_server in mcp_servers
                if mcp_server.id
                in [
                    mapping.mcp_server_id for mapping in space_in_db.mcp_servers_mapping
                ]
            ]

        members = {
            space_user.user_id: SpaceMember(
                **UserSparse.model_validate(space_user.user).model_dump(),
                role=cast(SpaceRoleValue, space_user.role),
            )
            for space_user in space_in_db.members
            if space_user.user.deleted_at is None
        }

        group_members: dict[UUID, SpaceGroupMember] = {}
        for space_group in getattr(space_in_db, "group_members", []) or []:
            user_group = space_group.user_group
            if user_group and user_group.state != UserGroupState.DELETED:
                users = cast(list[Users], user_group.users or [])
                group_members[user_group.id] = SpaceGroupMember(
                    id=user_group.id,
                    name=user_group.name,
                    role=cast(SpaceRoleValue, space_group.role),
                    user_count=len(users),
                )

        space_collections: list[Collection] = []
        for collection, info_blob_count in collections_in_db:
            embedding_model = next(
                (
                    embedding_model
                    for embedding_model in embedding_models
                    if embedding_model.id == collection.embedding_model_id
                ),
                None,
            )
            assert embedding_model is not None
            space_collections.append(
                Collection.to_domain(
                    record=collection,
                    embedding_model=embedding_model,
                    num_info_blobs=info_blob_count,
                )
            )
        space_websites: list[Website] = []
        for website in websites_in_db:
            embedding_model = next(
                (
                    embedding_model
                    for embedding_model in embedding_models
                    if embedding_model.id == website.embedding_model_id
                ),
                None,
            )
            assert embedding_model is not None
            space_websites.append(
                Website.to_domain(
                    record=website,
                    embedding_model=embedding_model,
                    http_auth=getattr(website, "_decrypted_http_auth", None),
                )
            )

        ik_source: list["IntegrationKnowledgeDBModel"] = (
            list(integration_knowledge_in_db)
            if integration_knowledge_in_db is not None
            else list(getattr(space_in_db, "integration_knowledge_list", []) or [])
        )

        integration_knowledge_list: list[IntegrationKnowledge] = []
        for i in ik_source:
            # Check if sharepoint_subscription was eager loaded via selectinload
            # We need to use sqlalchemy.inspect to check if the attribute was loaded
            # without triggering a lazy load (which causes greenlet errors in async context)
            from sqlalchemy import inspect

            sharepoint_subscription = None
            try:
                insp = inspect(i)
                if insp is not None and "sharepoint_subscription" not in insp.unloaded:
                    sharepoint_subscription = i.sharepoint_subscription
            except Exception:
                # If inspection fails (e.g., not a SQLAlchemy model), fall back to None
                pass

            integration_knowledge_list.append(
                IntegrationKnowledge(
                    name=cast(str, i.name),
                    original_name=getattr(i, "original_name", None),
                    user_integration=cast(
                        "UserIntegration",
                        getattr(i, "user_integration", None),
                    ),
                    embedding_model=cast(
                        "EmbeddingModel",
                        next(
                            (
                                em
                                for em in embedding_models
                                if em.id == i.embedding_model_id
                            ),
                            None,
                        ),
                    ),
                    tenant_id=i.tenant_id,
                    space_id=i.space_id,
                    id=i.id,
                    url=i.url,
                    size=i.size,
                    site_id=getattr(i, "site_id", None),
                    last_synced_at=i.last_synced_at,
                    last_sync_summary=i.last_sync_summary,
                    sharepoint_subscription_id=getattr(
                        i, "sharepoint_subscription_id", None
                    ),
                    sharepoint_subscription=cast(
                        "Optional[DomainSharePointSubscription]",
                        sharepoint_subscription,
                    ),
                    delta_token=getattr(i, "delta_token", None),
                    folder_id=getattr(i, "folder_id", None),
                    folder_path=getattr(i, "folder_path", None),
                    selected_item_type=getattr(i, "selected_item_type", None),
                    resource_type=getattr(i, "resource_type", None),
                    drive_id=getattr(i, "drive_id", None),
                    wrapper_id=getattr(i, "wrapper_id", None),
                    wrapper_name=getattr(i, "wrapper_name", None),
                )
            )

        all_assistants = _build_or_skip(
            assistants_in_db,
            item_kind="assistant",
            build_fn=lambda assistant: self.assistant_factory.create_space_assistant_from_db(
                assistant_in_db=assistant,
                completion_models=completion_models,
                collections=space_collections,
                websites=space_websites,
                integration_knowledge_list=integration_knowledge_list,
                user=user,
            ),
        )
        default_assistant = next(
            (assistant for assistant in all_assistants if assistant.is_default), None
        )
        # A default row may exist in the DB yet have been dropped by the
        # validation belt above. Distinguish that from "no default exists" so
        # SpaceInitService doesn't auto-create a duplicate default on read.
        default_assistant_load_failed = default_assistant is None and any(
            getattr(assistant, "is_default", False) for assistant in assistants_in_db
        )
        space_assistants = [
            assistant
            for assistant in all_assistants
            if (not default_assistant or assistant.id != default_assistant.id)
        ]
        # Set the tools of the default assistant
        if default_assistant is not None:
            default_assistant.tool_assistants = space_assistants

        space_apps = _build_or_skip(
            apps_in_db,
            item_kind="app",
            build_fn=lambda app: self.app_factory.create_space_app_from_db(
                app_in_db=app,
                completion_models=completion_models,
                transcription_models=transcription_models,
            ),
        )
        space_group_chats = _build_or_skip(
            group_chats_in_db,
            item_kind="group_chat",
            build_fn=lambda group_chat: GroupChatFactory.create_group_chat_from_db(
                group_chat_db=group_chat,
                assistants=space_assistants,
            ),
        )

        def _build_service(service: "Services") -> Service:
            return Service(
                **service.to_dict(),  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType] -- sqlalchemy_mixins.SerializeMixin lacks type stubs
                user=UserInDBBase.model_validate(service.user),
                completion_model=next(
                    (
                        model
                        for model in completion_models
                        if model.id == service.completion_model_id
                    ),
                    None,
                ),
                # NOTE: These are Collection domain objects cast to GroupInDBBase
                # to satisfy Service.groups typing. Downstream code (e.g.
                # service_runner.py) must cast back to Collection before
                # accessing Collection-specific attributes like .embedding_model.
                groups=cast(
                    "list[GroupInDBBase]",
                    [
                        group
                        for group in space_collections
                        if group.id
                        in [
                            service_group.group_id
                            for service_group in service.service_groups
                        ]
                    ],
                ),
            )

        space_services = _build_or_skip(
            services_in_db,
            item_kind="service",
            build_fn=_build_service,
        )

        space_security_classification: SecurityClassification | None = (
            SecurityClassification.to_domain(security_classification)
            if security_classification is not None
            else None
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
            mcp_servers=space_mcp_servers,
            default_assistant=default_assistant,
            default_assistant_load_failed=default_assistant_load_failed,
            assistants=space_assistants,
            group_chats=space_group_chats,
            apps=space_apps,
            services=space_services,
            integration_knowledge_list=integration_knowledge_list,
            collections=space_collections,
            websites=space_websites,
            members=members,
            group_members=group_members,
            security_classification=space_security_classification,
            data_retention_days=space_in_db.data_retention_days,
            icon_id=space_in_db.icon_id,
        )
