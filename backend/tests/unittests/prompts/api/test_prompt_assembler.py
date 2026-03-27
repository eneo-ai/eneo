from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.main.models import ResourcePermission
from eneo.prompts.api.prompt_assembler import PromptAssembler
from eneo.prompts.prompt import Prompt
from tests.fixtures import TEST_USER


@pytest.fixture
def prompt_assembler():
    return PromptAssembler(MagicMock())


@pytest.fixture
def prompt():
    return MagicMock(
        id=uuid4(),
        text="text",
        description="description",
        is_selected=True,
        user=TEST_USER,
        user_id=TEST_USER.id,
        tenant_id=TEST_USER.tenant_id,
    )


def test_prompt_owner_permission(prompt: Prompt, prompt_assembler: PromptAssembler):
    prompt_assembler.user = TEST_USER

    prompt = prompt_assembler.from_prompt_to_model(prompt)
    assert prompt.permissions == [
        ResourcePermission.READ,
        ResourcePermission.EDIT,
        ResourcePermission.DELETE,
    ]


async def test_prompt_not_owner_permission(
    prompt: Prompt, prompt_assembler: PromptAssembler
):
    prompt_assembler.user = MagicMock()
    prompt = prompt_assembler.from_prompt_to_model(prompt)
    assert prompt.permissions == [ResourcePermission.READ]
