"""The hidden per-space assistant the flows chat talks to.

One assistant per space with ``purpose="flows"``: a fixed, versioned prompt,
the space's default completion model, no knowledge and no MCP servers. It is
never listed and is reached only through the flows feature; the loopback
flows server attaches because of its purpose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from eneo.assistants.assistant_update import AssistantUpdate
from eneo.flows.authoring_prompt import AUTHORING_PROMPT, AUTHORING_PROMPT_VERSION
from eneo.flows.flow_models import FlowAuthoringAssistantPublic
from eneo.main.exceptions import BadRequestException, UnauthorizedException
from eneo.mcp_servers.domain.capabilities import CapabilityPurpose
from eneo.prompts.prompt_service import PromptService

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.actors.actor_manager import ActorManager
    from eneo.assistants.assistant import Assistant
    from eneo.assistants.assistant_factory import AssistantFactory
    from eneo.assistants.assistant_repo import AssistantRepository
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.spaces.space import Space
    from eneo.spaces.space_repo import SpaceRepository
    from eneo.users.user import UserInDB

FLOWS_PURPOSE = "flows"
FLOWS_ASSISTANT_NAME = "Flows"
PROMPT_VERSION_KEY = "flows_prompt_version"
# The capabilities document and function steps resolve their providers
# through: a step runs as a call of this assistant, so it holds every one
# (which of them a run may use is the space's and the user's decision).
REQUIRED_CAPABILITIES: list[CapabilityPurpose] = [
    "web_search",
    "image_generation",
    "file_analysis",
    "file_creation",
    "charts",
    "compute",
]


class FlowAuthoringAssistantService:
    def __init__(
        self,
        user: UserInDB,
        assistant_repo: AssistantRepository,
        assistant_factory: AssistantFactory,
        space_repo: SpaceRepository,
        actor_manager: ActorManager,
        prompt_service: PromptService,
    ):
        self.user = user
        self.assistant_repo = assistant_repo
        self.assistant_factory = assistant_factory
        self.space_repo = space_repo
        self.actor_manager = actor_manager
        self.prompt_service = prompt_service

    @staticmethod
    def _find(space: Space) -> Optional[Assistant]:
        return next(
            (
                assistant
                for assistant in space.purpose_assistants
                if assistant.purpose == FLOWS_PURPOSE
            ),
            None,
        )

    async def _prompt(self):
        """A persisted prompt row; the repo links prompts by id."""
        return await self.prompt_service.create_prompt(
            AUTHORING_PROMPT, None, owner_user_id=self.user.id
        )

    async def get_or_create(self, space_id: UUID) -> FlowAuthoringAssistantPublic:
        space = await self.space_repo.one(space_id)
        assert space.id is not None
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        if not actor.can_create_flows():
            raise UnauthorizedException(
                "You do not have permission to build flows in this space."
            )
        default_model = space.get_default_completion_model()
        if default_model is None:
            raise BadRequestException(
                "The space has no completion model; enable one before building flows."
            )

        assistant = self._find(space)
        if assistant is None:
            assistant = self.assistant_factory.create_assistant(
                name=FLOWS_ASSISTANT_NAME,
                user=self.user,
                space_id=space.id,
                prompt=await self._prompt(),
                completion_model=default_model,
                metadata_json={PROMPT_VERSION_KEY: AUTHORING_PROMPT_VERSION},
                purpose=FLOWS_PURPOSE,
            )
            assistant.enabled_capabilities = list(REQUIRED_CAPABILITIES)
            assistant_id = await self.assistant_repo.add(assistant)
            return FlowAuthoringAssistantPublic(
                assistant_id=assistant_id, space_id=space.id
            )

        assert assistant.id is not None
        update = await self._repair(assistant, space, default_model)
        if update is not None:
            await self.assistant_repo.apply_update(assistant.id, space.id, update)
        return FlowAuthoringAssistantPublic(
            assistant_id=assistant.id, space_id=space.id
        )

    async def _repair(
        self, assistant: Assistant, space: Space, default_model: CompletionModel
    ) -> Optional[AssistantUpdate]:
        """Point the assistant back at a usable model, the current prompt and
        the capabilities its document steps resolve through."""
        model = assistant.completion_model
        model_id = (
            default_model.id
            if model is None or not space.is_completion_model_in_space(model.id)
            else None
        )
        recorded = (assistant.metadata_json or {}).get(PROMPT_VERSION_KEY)
        prompt_stale = recorded != AUTHORING_PROMPT_VERSION
        missing: list[CapabilityPurpose] = [
            purpose
            for purpose in REQUIRED_CAPABILITIES
            if purpose not in assistant.enabled_capabilities
        ]
        capabilities: list[CapabilityPurpose] | None = (
            [*assistant.enabled_capabilities, *missing] if missing else None
        )
        if model_id is None and not prompt_stale and capabilities is None:
            return None
        if not prompt_stale:
            return AssistantUpdate(
                completion_model_id=model_id, enabled_capabilities=capabilities
            )
        metadata: dict[str, object] = {
            **(assistant.metadata_json or {}),
            PROMPT_VERSION_KEY: AUTHORING_PROMPT_VERSION,
        }
        return AssistantUpdate(
            prompt=await self._prompt(),
            metadata_json=metadata,
            completion_model_id=model_id,
            enabled_capabilities=capabilities,
        )
