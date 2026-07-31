from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant_factory import AssistantFactory
from eneo.completion_models.domain.model_kwargs_capabilities import (
    SupportedModelKwargs,
)
from eneo.database.tables.assistant_table import Assistants
from eneo.templates.app_template.app_template import AppTemplate
from eneo.users.user import UserInDB, UserSparse


@pytest.fixture
def factory():
    return AssistantFactory(
        prompt_factory=MagicMock(),
        assistant_template_factory=MagicMock(),
    )


def test_create_assistant_from_template(factory: AssistantFactory):
    completion_model = MagicMock()
    user = UserSparse(
        id=uuid4(),
        email="assistant-factory@example.com",
        username="assistant-factory",
    )

    prompt = MagicMock()
    template = AppTemplate(
        id="fake-uuid-1234",
        name="Test Assistant Template",
        description="Test Assitant Template Description",
        category="default",
        prompt_text="Test Assistant Prompt",
        completion_model={},
        completion_model_kwargs={},
        wizard={},
        created_at=datetime.now(),
        updated_at=datetime.now(),
        input_description=None,
        input_type="text",
        organization="default",
    )

    app = factory.create_assistant(
        name=template.name,
        user=user,
        space_id=uuid4(),
        completion_model=completion_model,
        completion_model_kwargs=ModelKwargs(),
        prompt=prompt,
        logging_enabled=True,
        template=template,
    )

    assert app.source_template.id == "fake-uuid-1234"
    assert app.source_template.prompt_text == "Test Assistant Prompt"


def _space_assistant_row(*, user_id, space_id):
    assistant = Assistants(
        id=uuid4(),
        name="Space Assistant",
        user_id=user_id,
        space_id=space_id,
        completion_model_id=None,
        completion_model_kwargs={},
        guardrail_active=False,
        logging_enabled=True,
        is_default=False,
        published=False,
        description=None,
        insight_enabled=False,
        data_retention_days=None,
        metadata_json={},
        hidden=False,
        origin="user",
        managing_flow_id=None,
        icon_id=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    assistant.assistant_groups = []
    assistant.assistant_websites = []
    assistant.assistant_integration_knowledge = []
    assistant.attachments = []
    assistant.mcp_servers = []
    assistant.template = None
    setattr(assistant, "prompt", None)
    return assistant


def test_create_space_assistant_from_db_pins_optional_user_projection(
    factory: AssistantFactory,
    user: UserInDB,
):
    assistant_row = _space_assistant_row(user_id=user.id, space_id=uuid4())

    tenant_scoped_assistant = factory.create_space_assistant_from_db(
        assistant_in_db=assistant_row,
        user=None,
        attachments=[],
    )
    user_scoped_assistant = factory.create_space_assistant_from_db(
        assistant_in_db=assistant_row,
        user=user,
        attachments=[],
    )

    assert tenant_scoped_assistant.user is None
    assert user_scoped_assistant.user == UserSparse.model_validate(user)


def test_create_space_assistant_preserves_persisted_model_kwargs(
    factory: AssistantFactory,
    user: UserInDB,
):
    assistant_row = _space_assistant_row(user_id=user.id, space_id=uuid4())
    completion_model = MagicMock()
    completion_model.id = uuid4()
    completion_model.get_supported_model_kwargs.return_value = SupportedModelKwargs()
    assistant_row.completion_model_id = completion_model.id
    assistant_row.completion_model_kwargs = {"top_p": 0.72}

    assistant = factory.create_space_assistant_from_db(
        assistant_in_db=assistant_row,
        user=user,
        attachments=[],
        completion_models=[completion_model],
    )

    assert assistant.completion_model_kwargs.top_p == 0.72
