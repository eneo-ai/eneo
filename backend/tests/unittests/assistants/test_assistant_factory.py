from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from intric.ai_models.completion_models.completion_model import ModelKwargs
from intric.assistants.assistant_factory import AssistantFactory
from intric.templates.app_template.app_template import AppTemplate
from intric.users.user import UserSparse


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
