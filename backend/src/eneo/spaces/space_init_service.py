import logging
from typing import TYPE_CHECKING

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant_update import AssistantUpdate
from eneo.governance_policy.domain.policy_resolver import (
    select_effective_completion_model,
)

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.assistants.assistant import Assistant
    from eneo.assistants.assistant_repo import AssistantRepository
    from eneo.assistants.assistant_service import AssistantService
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.governance_policy.application.effective_config_service import (
        EffectiveConfigService,
    )
    from eneo.spaces.space import Space
    from eneo.spaces.space_repo import SpaceRepository
    from eneo.spaces.space_service import SpaceService
    from eneo.users.user import UserInDB

logger = logging.getLogger(__name__)


def _unusable_reason(model: "CompletionModel | None") -> str:
    if model is None:
        return "missing"
    if model.deleted_at is not None:
        return "deleted"
    if model.migrated_to_model_id is not None:
        return "migrated"
    return "disabled"


class SpaceInitService:
    def __init__(
        self,
        user: "UserInDB",
        space_service: "SpaceService",
        assistant_service: "AssistantService",
        space_repo: "SpaceRepository",
        assistant_repo: "AssistantRepository",
        effective_config_service: "EffectiveConfigService | None" = None,
    ):
        super().__init__()
        self.user = user
        self.space_service = space_service
        self.assistant_service = assistant_service
        self.space_repo = space_repo
        self.assistant_repo = assistant_repo
        self.effective_config_service = effective_config_service

    async def _update_space_with_default_assistant(self, space: "Space"):
        assert space.id is not None
        space_id = space.id
        await self.space_repo.lock(space_id)
        space = await self.space_service.get_space(space_id)
        if space.default_assistant is not None or space.default_assistant_load_failed:
            return space
        default_assistant = await self.assistant_service.create_default_assistant(
            "Default", space
        )
        await self.assistant_repo.add(default_assistant)
        return await self.space_service.get_space(space_id)

    async def _ensure_tenant_space(self) -> "Space":
        hub = await self.space_service.get_or_create_tenant_space()
        if hub.default_assistant is None and not hub.default_assistant_load_failed:
            hub = await self._update_space_with_default_assistant(hub)
        return hub

    async def _create_personal_space(self):
        await self._ensure_tenant_space()
        personal_space = await self.space_service.create_personal_space()
        return await self._update_space_with_default_assistant(personal_space)

    async def create_space(self, name: str):
        await self._ensure_tenant_space()
        space = await self.space_service.create_space(name)
        return await self._update_space_with_default_assistant(space)

    async def get_personal_space(self):
        personal_space = await self.space_service.get_personal_space()

        if personal_space is None:
            # Create personal space if it does not exist
            personal_space = await self._create_personal_space()

        if (
            personal_space.default_assistant is None
            and not personal_space.default_assistant_load_failed
        ):
            # Create default assistant only when none exists. If a default row
            # exists but failed to load, recreating would orphan a duplicate.
            personal_space = await self._update_space_with_default_assistant(
                personal_space
            )

        return await self._ensure_usable_completion_model(personal_space)

    async def _ensure_usable_completion_model(self, space: "Space") -> "Space":
        """Keep the personal assistant pointing at a model it can use.

        The assistant is created with whatever default model exists at the
        time, which may be none, and a stored model can later be deleted,
        migrated or disabled. No lifecycle event repairs that, so do it here:
        every chat load passes through this service, which already writes on
        read. A usable stored choice is never touched. When a models policy is
        enforced, the policy's own resolution is stored so the saved id matches
        what the chat actually runs. With no usable model anywhere the
        assistant is left alone, so the "no model available" state stays true.

        Only the assistant row is written. Rewriting the whole space would also
        delete any sibling assistant the loader skipped as invalid.
        """
        assistant = space.default_assistant
        if assistant is None:
            return space

        current = assistant.completion_model
        if current is not None and current.can_access:
            return space

        fallback = await self._fallback_completion_model(space, assistant)
        if fallback is None:
            return space

        # Reset model parameters like the migration tool does: they belong to
        # the model they were tuned for.
        assistant.update(
            completion_model=fallback, completion_model_kwargs=ModelKwargs()
        )
        logger.info(
            "Repaired personal assistant %s for user %s: completion model %s (%s) "
            "replaced with %s",
            assistant.id,
            self.user.id,
            current.id if current is not None else None,
            _unusable_reason(current),
            fallback.id,
        )
        await self.assistant_repo.apply_update(
            assistant.id,
            assistant.space_id,
            AssistantUpdate(
                completion_model_id=fallback.id,
                completion_model_kwargs=ModelKwargs(),
            ),
        )
        return space

    async def _fallback_completion_model(
        self, space: "Space", assistant: "Assistant"
    ) -> "CompletionModel | None":
        if self.effective_config_service is not None:
            effective_config = await self.effective_config_service.resolve_for(
                assistant, space_is_personal=True
            )
            if effective_config.models_enforced:
                return select_effective_completion_model(
                    current_model=None, effective_config=effective_config
                )

        # Personal spaces load every tenant model, usable or not, and
        # get_default_completion_model raises when none is usable.
        if not any(model.can_access for model in space.completion_models):
            return None
        return space.get_default_completion_model()

    async def get_space(self, space_id: "UUID"):
        space = await self.space_service.get_space(space_id)

        if space.default_assistant is None and not space.default_assistant_load_failed:
            space = await self._update_space_with_default_assistant(space)

        return space

    async def get_or_create_tenant_space(self) -> "Space":
        return await self._ensure_tenant_space()
