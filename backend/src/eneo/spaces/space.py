from collections.abc import Iterable, Sequence
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Optional, Protocol, TypeVar, Union
from uuid import UUID

from eneo.main.datetime_utils import datetime_or_utc_min
from eneo.main.exceptions import (
    BadRequestException,
    KnowledgeModelUnavailableException,
    ModelNotAvailableException,
    NoModelSelectedException,
    NotFoundException,
    SecurityClassificationMismatchException,
    UnauthorizedException,
)
from eneo.main.models import NOT_PROVIDED, NotProvided, is_provided
from eneo.mcp_servers.domain.capabilities import (
    CapabilityAvailability,
    CapabilityPurpose,
)
from eneo.mcp_servers.domain.entities.mcp_server import is_capability_purpose
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces.api.space_models import SpaceGroupMember, SpaceMember, SpaceRoleValue
from eneo.transcription_models.domain.transcription_model import TranscriptionModel

if TYPE_CHECKING:
    from eneo.ai_models.ai_model import AIModel
    from eneo.apps import App
    from eneo.assistants.assistant import Assistant
    from eneo.collections.domain.collection import Collection
    from eneo.completion_models.domain import CompletionModel
    from eneo.embedding_models.domain.embedding_model import EmbeddingModel
    from eneo.group_chat.domain.entities.group_chat import GroupChat
    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.services.service import Service
    from eneo.transcription_services.models import TranscriptionServiceConnection
    from eneo.websites.domain.website import Website


class ClassifiedLink(Protocol):
    """A resource a space links to and grants use of under its classification:
    a model, or a transcription-service connection."""

    @property
    def id(self) -> UUID: ...

    @property
    def can_access(self) -> bool: ...

    @property
    def security_classification(self) -> Optional[SecurityClassification]: ...


_M = TypeVar("_M", bound=ClassifiedLink)
LinkKind = Literal["completion", "embedding", "transcription", "transcription_service"]
LINK_KINDS: tuple[LinkKind, ...] = (
    "completion",
    "embedding",
    "transcription",
    "transcription_service",
)


def _security_level(
    classification: Optional[SecurityClassification],
) -> int | None:
    """The level model eligibility depends on; None when unclassified."""
    return classification.security_level if classification is not None else None


UNAUTHORIZED_EXCEPTION_MESSAGE = "Unauthorized. User has no permissions to access."
SECURITY_CLASSIFICATION_EXCEPTION_MESSAGE = (
    "Security classification is not compatible with the space."
)
NO_COMPLETION_MODEL_EXCEPTION_MESSAGE = (
    "Cannot perform operation: Space '{space_name}' has no completion models configured. "
    "Please configure at least one completion model in the space settings."
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
        mcp_servers: list["MCPServer"],
        default_assistant: Optional["Assistant"],
        assistants: Optional[list["Assistant"]],
        apps: Optional[list["App"]],
        services: Optional[list["Service"]],
        websites: Optional[list["Website"]],
        collections: Optional[list["Collection"]],
        integration_knowledge_list: Optional[list["IntegrationKnowledge"]],
        members: dict[UUID, SpaceMember] | None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        group_chats: list["GroupChat"] | None = None,
        security_classification: Optional[SecurityClassification] = None,
        data_retention_days: Optional[int] = None,
        icon_id: Optional[UUID] = None,
        enabled_capabilities: list[CapabilityPurpose] | None = None,
        group_members: dict[UUID, SpaceGroupMember] | None = None,
        default_assistant_load_failed: bool = False,
        unloaded_hidden_assistant_ids: frozenset[UUID] = frozenset(),
        transcription_services: Optional[list["TranscriptionServiceConnection"]] = None,
    ):
        super().__init__()
        self.id = id
        self.tenant_id = tenant_id
        self.tenant_space_id = tenant_space_id
        self.user_id = user_id
        self.name = name
        self.description = description
        self._embedding_models = embedding_models
        self._completion_models = completion_models
        self._transcription_models = transcription_models
        self._transcription_services = list(transcription_services or [])
        self._mcp_servers = mcp_servers
        self.default_assistant = default_assistant
        # True when a default-assistant row existed in the DB but failed to
        # build (e.g. skipped by the space-load validation belt). Lets callers
        # distinguish "no default exists" from "default exists but unloadable"
        # so they don't auto-create a duplicate default. See SpaceInitService.
        self.default_assistant_load_failed = default_assistant_load_failed
        self.assistants = assistants or []
        # Assistants this request removed on purpose. A whole-space write
        # deletes only these, never one it merely did not load.
        self.removed_assistant_ids: set[UUID] = set()
        # Hidden assistants of the space this load did not build. API-key
        # access facts still count them, as a load of every hidden one did.
        self.unloaded_hidden_assistant_ids = unloaded_hidden_assistant_ids
        self.group_chats = group_chats or []
        self.apps = apps or []
        self.services = services or []
        self.websites = websites or []
        self.collections = collections or []
        self.integration_knowledge_list = integration_knowledge_list or []
        self.members = members or {}
        self.created_at = created_at
        self.updated_at = updated_at
        self.security_classification = security_classification
        # A stored model list can outlive a reclassification of the space or of
        # a model. The space's classification is the one owner of which models
        # it may use, so a hydrated list is held to it here, once, instead of
        # every chooser asking again. A linked model below the classification
        # is not usable here, but it stays linked: an unrelated save must not
        # remove it, and an admin decides whether to raise the model's
        # classification, change the space's, or remove it.
        self._completion_models_below_classification: list["CompletionModel"] = []
        self._embedding_models_below_classification: list["EmbeddingModel"] = []
        self._transcription_models_below_classification: list[TranscriptionModel] = []
        self._transcription_services_below_classification: list[
            "TranscriptionServiceConnection"
        ] = []
        self._split_models_by_classification()
        # The links as loaded. A save writes only the difference (see
        # link_changes), so a stored link this space never loaded, such as
        # one to a deprecated model, is left exactly as it is.
        self._loaded_link_ids: dict[LinkKind, frozenset[UUID]] = {
            kind: frozenset(link.id for link in self._linked(kind))
            for kind in LINK_KINDS
        }
        self.data_retention_days = data_retention_days
        self.enabled_capabilities: list[CapabilityPurpose] = list(
            enabled_capabilities or []
        )
        self.available_capabilities: list[CapabilityAvailability] = []
        self.icon_id = icon_id
        self.group_members = group_members if group_members is not None else {}

    def _get_member_ids(self):
        return self.members.keys()

    def is_personal(self):
        return self.user_id is not None

    def is_organization(self):
        return (self.user_id is None) and (self.tenant_space_id is None)

    def is_shared(self) -> bool:
        """Collaborative Delat-tab space (not personal, not the org hub)."""
        return (not self.is_personal()) and (not self.is_organization())

    def is_embedding_model_in_space(self, embedding_model_id: UUID | None) -> bool:
        return embedding_model_id in [model.id for model in self.embedding_models]

    def is_completion_model_in_space(self, completion_model_id: UUID | None) -> bool:
        if completion_model_id is None:
            return False
        return any(m.id == completion_model_id for m in self.completion_models)

    def is_transcription_model_in_space(
        self, transcription_model_id: UUID | None
    ) -> bool:
        return transcription_model_id in [
            model.id for model in self.transcription_models
        ]

    def is_transcription_service_available(self, connection_id: UUID) -> bool:
        """Whether new work in this space may use the connection: granted,
        allowed by the classification, and enabled by the organisation."""
        return any(
            connection.id == connection_id and connection.can_access
            for connection in self._transcription_services
        )

    def is_mcp_server_in_space(self, mcp_server_id: UUID | None) -> bool:
        return mcp_server_id in [server.id for server in self.mcp_servers]

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
        return integration_knowledge_id in [
            i.id for i in self.integration_knowledge_list
        ]

    def get_member(self, member_id: UUID) -> SpaceMember:
        return self.members[member_id]

    def get_latest_embedding_model(self) -> "EmbeddingModel | None":
        if not self.embedding_models:
            return

        sorted_embedding_models = sorted(
            [
                embedding_model
                for embedding_model in self.embedding_models
                if embedding_model.can_access
            ],
            key=lambda model: datetime_or_utc_min(model.created_at),
            reverse=True,
        )

        if not sorted_embedding_models:
            raise BadRequestException(
                f"Cannot perform operation: Space '{self.name}' has no embedding models configured. "
                "Please configure at least one embedding model in the space settings."
            )

        return sorted_embedding_models[0]  # type: ignore

    def get_latest_completion_model(self) -> "CompletionModel | None":
        if not self.completion_models:
            return

        sorted_completion_models = sorted(
            [
                completion_model
                for completion_model in self.completion_models
                if completion_model.can_access
            ],
            key=lambda model: datetime_or_utc_min(model.created_at),
            reverse=True,
        )

        if not sorted_completion_models:
            raise BadRequestException(
                NO_COMPLETION_MODEL_EXCEPTION_MESSAGE.format(space_name=self.name)
            )

        return sorted_completion_models[0]  # type: ignore

    def get_latest_transcription_model(self) -> Optional[TranscriptionModel]:
        if not self.transcription_models:
            return None

        sorted_transcription_models = sorted(
            [
                transcription_model
                for transcription_model in self.transcription_models
                if transcription_model.can_access
            ],
            key=lambda model: datetime_or_utc_min(model.created_at),
            reverse=True,
        )

        if not sorted_transcription_models:
            return None

        return sorted_transcription_models[0]  # type: ignore

    def select_default_completion_model(
        self, candidates: Iterable["CompletionModel"]
    ) -> Optional["CompletionModel"]:
        """This space's default among an already-vetted candidate set.

        The policy — the organisation default, else the newest — lives here so
        that callers narrowing the candidates for their own reasons (a planner
        that also needs an active provider, say) pick the same way this space
        would, instead of restating it and drifting.
        """
        eligible = list(candidates)
        organisation_default = next(
            (model for model in eligible if model.is_org_default), None
        )
        if organisation_default is not None:
            return organisation_default
        return max(
            eligible,
            key=lambda model: datetime_or_utc_min(model.created_at),
            default=None,
        )

    def get_default_completion_model(self) -> Optional["CompletionModel"]:
        if not self.completion_models:
            return None

        default_model = self.select_default_completion_model(
            model for model in self.completion_models if model.can_access
        )
        if default_model is None:
            raise BadRequestException(
                NO_COMPLETION_MODEL_EXCEPTION_MESSAGE.format(space_name=self.name)
            )

        return default_model

    def get_default_embedding_model(self) -> Optional["EmbeddingModel"]:
        return self.get_latest_embedding_model()

    def get_default_transcription_model(self) -> Optional[TranscriptionModel]:
        """Get the default transcription model from the space.
        Returns the default model if it exists, otherwise returns the latest model."""
        if not self.transcription_models:
            return None

        # First try to get the org default model
        model = filter(
            lambda m: m.is_org_default and m.can_access, self.transcription_models
        )
        default_model = next(model, None)

        if default_model is not None:
            return default_model

        # Get the most recently added model as a fallback
        return self.get_latest_transcription_model()

    @property
    def embedding_models(self):
        """The embedding models usable in this space."""
        return self._embedding_models

    @embedding_models.setter
    def embedding_models(self, embedding_models: list["EmbeddingModel"]):
        self._embedding_models, self._embedding_models_below_classification = (
            self._assign_models(embedding_models, self.linked_embedding_models)
        )

    @property
    def completion_models(self) -> list["CompletionModel"]:
        """The completion models usable in this space."""
        return self._completion_models

    @completion_models.setter
    def completion_models(self, completion_models: list["CompletionModel"]):
        self._completion_models, self._completion_models_below_classification = (
            self._assign_models(completion_models, self.linked_completion_models)
        )

    @property
    def transcription_models(self) -> list[TranscriptionModel]:
        """The transcription models usable in this space."""
        return self._transcription_models

    @transcription_models.setter
    def transcription_models(self, transcription_models: list[TranscriptionModel]):
        (
            self._transcription_models,
            self._transcription_models_below_classification,
        ) = self._assign_models(transcription_models, self.linked_transcription_models)

    @property
    def transcription_services(self) -> list["TranscriptionServiceConnection"]:
        """The transcription services granted to this space and usable here."""
        return self._transcription_services

    @transcription_services.setter
    def transcription_services(
        self, transcription_services: list["TranscriptionServiceConnection"]
    ):
        (
            self._transcription_services,
            self._transcription_services_below_classification,
        ) = self._assign_models(
            transcription_services, self.linked_transcription_services
        )

    @property
    def transcription_services_below_classification(
        self,
    ) -> list["TranscriptionServiceConnection"]:
        return list(self._transcription_services_below_classification)

    @property
    def linked_transcription_services(
        self,
    ) -> list["TranscriptionServiceConnection"]:
        return [
            *self._transcription_services,
            *self._transcription_services_below_classification,
        ]

    @property
    def completion_models_below_classification(self) -> list["CompletionModel"]:
        """Linked completion models below this space's classification.

        They stay linked but are not usable here; see __init__."""
        return list(self._completion_models_below_classification)

    @property
    def embedding_models_below_classification(self) -> list["EmbeddingModel"]:
        return list(self._embedding_models_below_classification)

    @property
    def transcription_models_below_classification(self) -> list[TranscriptionModel]:
        return list(self._transcription_models_below_classification)

    @property
    def linked_completion_models(self) -> list["CompletionModel"]:
        """Every completion model linked to this space, usable or not.

        A write of the space's links persists this list, so a model below the
        classification is removed only when a request leaves it out."""
        return [
            *self._completion_models,
            *self._completion_models_below_classification,
        ]

    @property
    def linked_embedding_models(self) -> list["EmbeddingModel"]:
        return [*self._embedding_models, *self._embedding_models_below_classification]

    @property
    def linked_transcription_models(self) -> list[TranscriptionModel]:
        return [
            *self._transcription_models,
            *self._transcription_models_below_classification,
        ]

    def _linked(self, kind: LinkKind) -> Sequence[ClassifiedLink]:
        return {
            "completion": self.linked_completion_models,
            "embedding": self.linked_embedding_models,
            "transcription": self.linked_transcription_models,
            "transcription_service": self.linked_transcription_services,
        }[kind]

    def link_changes(self, kind: LinkKind) -> tuple[set[UUID], set[UUID]]:
        """The links of one kind this space added and removed.

        Only an explicit model-list edit, adding a model, or a change of the
        space's classification level changes links. A write persists exactly
        these changes and never touches a stored link it did not load."""
        loaded = self._loaded_link_ids[kind]
        current = {link.id for link in self._linked(kind)}
        return current - loaded, set(loaded - current)

    def _split_models_by_classification(self) -> None:
        """Sort every linked model and service into usable and below-classification."""
        self._completion_models, self._completion_models_below_classification = (
            self._split_by_classification(self.linked_completion_models)
        )
        self._embedding_models, self._embedding_models_below_classification = (
            self._split_by_classification(self.linked_embedding_models)
        )
        (
            self._transcription_models,
            self._transcription_models_below_classification,
        ) = self._split_by_classification(self.linked_transcription_models)
        (
            self._transcription_services,
            self._transcription_services_below_classification,
        ) = self._split_by_classification(self.linked_transcription_services)

    def _split_by_classification(
        self, models: Sequence[_M]
    ) -> tuple[list[_M], list[_M]]:
        usable = [m for m in models if self.allows_security_classification(m)]
        below = [m for m in models if not self.allows_security_classification(m)]
        return usable, below

    def _assign_models(
        self, models: Sequence[_M], linked: Sequence[_M]
    ) -> tuple[list[_M], list[_M]]:
        """Validate an explicit model list and split it into usable and below.

        The list replaces the space's links, so a model it leaves out is
        unlinked. A model that is already linked may stay whatever its state:
        keeping a link grants no use, so neither the tenant disabling it nor
        its classification falling below the space's removes it here. A new
        link must be accessible and meet the classification, as before.
        """
        linked_ids = {model.id for model in linked}
        usable: list[_M] = []
        below: list[_M] = []
        for model in models:
            allowed = self.allows_security_classification(model)
            if model.id not in linked_ids:
                if not model.can_access:
                    raise UnauthorizedException(UNAUTHORIZED_EXCEPTION_MESSAGE)
                if not allowed:
                    raise BadRequestException(SECURITY_CLASSIFICATION_EXCEPTION_MESSAGE)
            (usable if allowed else below).append(model)
        return usable, below

    @property
    def mcp_servers(self) -> list["MCPServer"]:
        return self._mcp_servers

    @mcp_servers.setter
    def mcp_servers(self, mcp_servers: list["MCPServer"]):
        for server in mcp_servers:
            self.validate_mcp_server_security_compatibility(server)
        self._mcp_servers = mcp_servers

    def update(
        self,
        name: str | None = None,
        description: str | None = None,
        embedding_models: list["EmbeddingModel"] | None = None,
        completion_models: list["CompletionModel"] | None = None,
        transcription_models: list[TranscriptionModel] | None = None,
        transcription_services: list["TranscriptionServiceConnection"] | None = None,
        mcp_servers: list["MCPServer"] | None = None,
        security_classification: Union[
            SecurityClassification, NotProvided, None
        ] = NOT_PROVIDED,
        data_retention_days: Union[int, None, NotProvided] = NOT_PROVIDED,
        icon_id: Union[UUID, None, NotProvided] = NOT_PROVIDED,
    ):
        if name is not None:
            if self.is_personal():
                raise BadRequestException("Can not change name of personal space")

            self.name = name

        if description is not None:
            if self.is_personal():
                raise BadRequestException(
                    "Can not change description of personal space"
                )

            self.description = description
        # Only if security_classification_enabled on tenant (checked in service layer)
        if is_provided(security_classification):
            if self.is_personal():
                raise BadRequestException(
                    "Can not change security classification of personal space"
                )
            # Only a change of level may remove links: eligibility depends on
            # the level alone, so a PATCH that resends the classification, or
            # names another one at the same level, leaves every link as it is.
            changes_classification = _security_level(
                self.security_classification
            ) != _security_level(security_classification)
            self.security_classification = security_classification
            # A linked model the new classification allows is usable again.
            self._split_models_by_classification()
            if changes_classification and self.security_classification is not None:
                # Changing the space's classification is the admin's explicit,
                # previewed decision; as on develop, it removes the models the
                # new classification does not allow.
                self._completion_models_below_classification = []
                self._embedding_models_below_classification = []
                self._transcription_models_below_classification = []
                self._transcription_services_below_classification = []
                # Capability markers stay: the provider resolved at ask time
                # is what gets checked, not the marker's own classification.
                self._mcp_servers = [
                    server
                    for server in self._mcp_servers
                    if is_capability_purpose(server.purpose)
                    or not self.security_classification.is_greater_than(
                        server.security_classification
                    )
                ]

        if completion_models is not None:
            if self.is_personal():
                raise BadRequestException(
                    "Can not add completion models to personal space"
                )

            self.completion_models = completion_models

        if embedding_models is not None:
            if self.is_personal():
                raise BadRequestException(
                    "Can not add embedding models to personal space"
                )

            self.embedding_models = embedding_models

        if transcription_models is not None:
            if self.is_personal():
                raise BadRequestException(
                    "Can not add transcription models to personal space"
                )

            self.transcription_models = transcription_models

        if transcription_services is not None:
            if self.is_personal():
                raise BadRequestException(
                    "Can not add transcription services to personal space"
                )

            self.transcription_services = transcription_services

        if mcp_servers is not None:
            if self.is_personal():
                raise BadRequestException("Can not add MCP servers to personal space")

            self.mcp_servers = mcp_servers

        if is_provided(data_retention_days):
            self.data_retention_days = data_retention_days

        if is_provided(icon_id):
            self.icon_id = icon_id

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

    def _get_group_member_ids(self):
        return self.group_members.keys()

    def add_group_member(self, group: SpaceGroupMember):
        """Add a user group as a member of this space.

        Groups cannot be added to personal spaces.
        """
        if self.is_personal():
            raise BadRequestException("Cannot add group members to personal spaces")

        if group.id in self._get_group_member_ids():
            raise BadRequestException("Group is already a member of the space")

        self.group_members[group.id] = group

    def remove_group_member(self, group_id: UUID):
        """Remove a user group from this space."""
        if group_id not in self._get_group_member_ids():
            raise BadRequestException("Group is not a member of the space")

        del self.group_members[group_id]

    def change_group_member_role(self, group_id: UUID, new_role: SpaceRoleValue):
        """Change the role of a user group in this space."""
        if group_id not in self._get_group_member_ids():
            raise BadRequestException("Group is not a member of the space")

        self.group_members[group_id].role = new_role

    def get_group_member(self, group_id: UUID) -> SpaceGroupMember:
        """Get a group member by ID."""
        return self.group_members[group_id]

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
        assert self.group_chats is not None
        self.group_chats.append(group_chat)

    def remove_group_chat(self, group_chat: "GroupChat"):
        assert self.group_chats is not None
        self.group_chats.remove(group_chat)

    def add_assistant(self, assistant: "Assistant"):
        if assistant.id in [a.id for a in self.assistants]:
            raise BadRequestException("Assistant is already in the space")

        cm = getattr(assistant, "completion_model", None)
        # Only add completion model to space if the assistant has one
        if cm is not None and getattr(cm, "id", None) is not None:
            if not self.is_completion_model_in_space(cm.id):
                self.add_completion_model(cm)

        self.assistants.append(assistant)

    def remove_assistant(self, assistant: "Assistant"):
        for group_chat in self.group_chats or []:
            group_chat.assistants = [
                a for a in group_chat.assistants if a.assistant.id != assistant.id
            ]

        self.assistants.remove(assistant)
        self.removed_assistant_ids.add(assistant.id)

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

    def can_ask_assistant(
        self,
        assistant: "Assistant",
        completion_model: "CompletionModel | None" = None,
    ):
        # `completion_model` is the policy-resolved model for a personal default
        # assistant, which may have no stored model of its own.
        completion_model = completion_model or assistant.completion_model
        if completion_model is None:
            raise NoModelSelectedException(
                "No AI model is configured for this assistant. "
                "Please select a model in the assistant settings."
            )
        if not self.is_completion_model_available(completion_model.id):
            raise ModelNotAvailableException(
                "The selected AI model is not available in this space. "
                "Please choose a different model or contact your administrator."
            )
        if not self.can_use_knowledge(
            assistant.collections
            + assistant.websites
            + assistant.integration_knowledge_list
        ):
            raise KnowledgeModelUnavailableException(
                "This assistant uses knowledge sources with unavailable embedding models. "
                "Please review the assistant's knowledge settings."
            )
        if self.security_classification is not None:
            if self.security_classification.is_greater_than(
                completion_model.security_classification
            ):
                raise SecurityClassificationMismatchException(
                    "The assistant's model does not meet this space's "
                    "security classification requirements."
                )

    def can_run_app(self, app: "App") -> bool:
        completion_model = app.completion_model
        if completion_model is None:
            return False
        if not self.is_completion_model_available(completion_model.id):
            return False
        transcription_model = app.transcription_model
        if transcription_model is None:
            return False
        if not self.is_transcription_model_available(transcription_model.id):
            return False
        if self.security_classification is not None:
            # App.completion_model is typed as CompletionModel | CompletionModelSparse | None;
            # domain CompletionModel always has security_classification at this call site.
            if self.security_classification.is_greater_than(
                completion_model.security_classification  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType,reportUnknownArgumentType] -- CompletionModelSparse lacks security_classification but domain model always has it at this call site
            ):
                return False
            if (
                transcription_model.security_classification is not None
                and self.security_classification.is_greater_than(
                    transcription_model.security_classification
                )
            ):
                return False

        return True

    def can_use_service(self, service: "Service") -> bool:
        if service.completion_model is None:
            return False
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

    def get_integration_knowledge(
        self, integration_knowledge_id: UUID
    ) -> "IntegrationKnowledge":
        return self._get_entity(
            integration_knowledge_id, self.integration_knowledge_list
        )

    def get_transcription_model(
        self, transcription_model_id: UUID
    ) -> "TranscriptionModel":
        return self._get_entity(transcription_model_id, self.transcription_models)

    def get_completion_model(self, completion_model_id: UUID) -> "CompletionModel":
        return self._get_entity(completion_model_id, self.completion_models)

    def get_embedding_model(self, embedding_model_id: UUID) -> "EmbeddingModel":
        return self._get_entity(embedding_model_id, self.embedding_models)

    def get_mcp_server(self, mcp_server_id: UUID) -> "MCPServer":
        return self._get_entity(mcp_server_id, self.mcp_servers)

    def get_website(self, website_id: UUID) -> "Website":
        return self._get_entity(website_id, self.websites)

    def allows_security_classification(self, link: ClassifiedLink) -> bool:
        """Whether this space's classification permits the model or service.

        The predicate form exists for callers that must *choose* a model rather
        than accept one: the stored model list is only validated when it is
        assigned, so a caller picking from it on the user's behalf has to ask
        again rather than assume.
        """
        if not self.security_classification:
            return True
        return not self.security_classification.is_greater_than(
            link.security_classification
        )

    def validate_model_security_compatibility(self, model: "AIModel") -> None:
        if not self.allows_security_classification(model):
            raise BadRequestException(SECURITY_CLASSIFICATION_EXCEPTION_MESSAGE)

    def validate_mcp_server_security_compatibility(
        self, mcp_server: "MCPServer"
    ) -> None:
        if not self.security_classification:
            return
        # A capability marker is not the provider that will be called; the
        # service validates the active providers and the ask path enforces
        # the classification on the resolved provider.
        if is_capability_purpose(mcp_server.purpose):
            return
        if self.security_classification.is_greater_than(
            mcp_server.security_classification
        ):
            raise BadRequestException(SECURITY_CLASSIFICATION_EXCEPTION_MESSAGE)

    def add_completion_model(self, model: "CompletionModel"):
        if getattr(model, "id", None) is None:
            raise BadRequestException("Invalid completion model")

        if hasattr(model, "can_access") and not model.can_access:
            raise BadRequestException("Completion model is not accessible")

        self.validate_model_security_compatibility(model)

        if any(m.id == model.id for m in self.completion_models):
            return

        self.completion_models.append(model)
