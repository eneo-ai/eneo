# Copyright (c) 2024 Sundsvalls Kommun
#
# Licensed under the MIT License.


from eneo.main.models import ResourcePermission
from eneo.prompts.api.prompt_models import PromptPublic
from eneo.prompts.prompt import Prompt
from eneo.users.user import UserInDB, UserSparse


class PromptAssembler:
    def __init__(self, user: UserInDB) -> None:
        super().__init__()
        self.user = user

    def get_prompt_permissions(self, prompt: Prompt) -> list[ResourcePermission]:
        permissions = [ResourcePermission.READ]

        if prompt.user_id == self.user.id:
            permissions.extend([ResourcePermission.EDIT, ResourcePermission.DELETE])

        return permissions

    def from_prompt_to_model(self, prompt: Prompt) -> PromptPublic:
        permissions = self.get_prompt_permissions(prompt)

        assert prompt.id is not None, "Prompt must have an id before being assembled"
        assert prompt.user is not None, "Prompt must have a user before being assembled"

        user = prompt.user
        # Help-assistant prompts are owned by the per-tenant system user so they
        # are never orphaned when a real user is deleted. That account is
        # non-interactive and is seeded with a synthetic, non-deliverable address
        # on a reserved TLD (e.g. system+<tenant_id>@eneo.local) that Pydantic's
        # EmailStr refuses to validate. Project it with model_construct so we do
        # not re-validate already-stored, trusted data — otherwise serializing a
        # system-user-owned prompt (e.g. opening a help assistant to edit it)
        # 500s here. This mirrors the model_construct used when the helper is
        # created in OrgSpaceAssistantRoleService; normal owners are unaffected
        # and still go through full validation.
        if getattr(user, "is_system_user", False):
            user = UserSparse.model_construct(
                id=user.id,
                created_at=user.created_at,
                updated_at=user.updated_at,
                email=user.email,
                username=user.username,
            )

        return PromptPublic(
            created_at=prompt.created_at,
            updated_at=prompt.updated_at,
            id=prompt.id,
            permissions=permissions,
            description=prompt.description,
            is_selected=prompt.is_selected,
            user=user,
            text=prompt.text,
        )
