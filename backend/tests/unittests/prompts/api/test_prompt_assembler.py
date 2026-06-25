from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.main.models import ResourcePermission
from intric.prompts.api.prompt_assembler import PromptAssembler
from intric.prompts.prompt import Prompt
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


def _system_user_row():
    # Stand-in for the per-tenant system user: a non-interactive account seeded
    # with a synthetic, non-deliverable address on a reserved TLD
    # (system+<tenant_id>@eneo.local) that Pydantic's EmailStr refuses.
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        is_system_user=True,
        id=uuid4(),
        created_at=now,
        updated_at=now,
        email=f"system+{uuid4()}@eneo.local",
        username="system",
    )


def test_system_user_owned_prompt_serializes_without_email_validation(
    prompt_assembler: PromptAssembler,
):
    # Opening a help assistant assembles its prompt, whose owner is the system
    # user. Its reserved-TLD email must pass through (model_construct), not be
    # re-validated, otherwise this 500s.
    system_user = _system_user_row()
    prompt = MagicMock(
        id=uuid4(),
        text="text",
        description="description",
        is_selected=True,
        user=system_user,
        user_id=system_user.id,
        tenant_id=uuid4(),
    )
    prompt_assembler.user = MagicMock()

    result = prompt_assembler.from_prompt_to_model(prompt)

    assert result.user.email == system_user.email


def test_non_system_user_reserved_tld_email_still_rejected(
    prompt_assembler: PromptAssembler,
):
    # The dodge is scoped to the system user: a normal owner with an invalid
    # email is still rejected, so output validation is not weakened globally.
    now = datetime.now(timezone.utc)
    bad_user = SimpleNamespace(
        is_system_user=False,
        id=uuid4(),
        created_at=now,
        updated_at=now,
        email="someone@eneo.local",
        username="someone",
    )
    prompt = MagicMock(
        id=uuid4(),
        text="text",
        description="description",
        is_selected=True,
        user=bad_user,
        user_id=bad_user.id,
        tenant_id=uuid4(),
    )
    prompt_assembler.user = MagicMock()

    with pytest.raises(ValidationError) as exc_info:
        prompt_assembler.from_prompt_to_model(prompt)
    assert "email" in str(exc_info.value)
