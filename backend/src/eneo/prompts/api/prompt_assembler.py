# Copyright (c) 2024 Sundsvalls Kommun
#
# Licensed under the MIT License.


from eneo.main.models import ResourcePermission
from eneo.prompts.api.prompt_models import PromptPublic
from eneo.prompts.prompt import Prompt
from eneo.users.user import UserInDB


class PromptAssembler:
    def __init__(self, user: UserInDB):
        self.user = user

    def get_prompt_permissions(self, prompt: Prompt):
        permissions = [ResourcePermission.READ]

        if prompt.user_id == self.user.id:
            permissions.extend([ResourcePermission.EDIT, ResourcePermission.DELETE])

        return permissions

    def from_prompt_to_model(self, prompt: Prompt):
        permissions = self.get_prompt_permissions(prompt)

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
