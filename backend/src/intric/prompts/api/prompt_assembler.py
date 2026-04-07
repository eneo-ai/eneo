# Copyright (c) 2024 Sundsvalls Kommun
#
# Licensed under the MIT License.


from intric.main.models import ResourcePermission
from intric.prompts.api.prompt_models import PromptPublic
from intric.prompts.prompt import Prompt
from intric.users.user import UserInDB


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

        return PromptPublic(
            created_at=prompt.created_at,
            updated_at=prompt.updated_at,
            id=prompt.id,
            permissions=permissions,
            description=prompt.description,
            is_selected=prompt.is_selected,
            user=prompt.user,
            text=prompt.text,
        )
