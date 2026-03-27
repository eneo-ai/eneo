from datetime import datetime
from unittest.mock import MagicMock

import pytest

from eneo.apps.apps.api.app_models import InputField, InputFieldType
from eneo.apps.apps.app_factory import AppFactory
from eneo.templates.app_template.app_template import AppTemplate


@pytest.fixture
def factory():
    return AppFactory(app_template_factory=MagicMock())


def test_create_new_app(factory: AppFactory):
    space = MagicMock()
    name = MagicMock()
    completion_model = MagicMock()
    user = MagicMock()
    app = factory.create_app(
        user=user,
        space=space,
        name=name,
        completion_model=completion_model,
        transcription_model=MagicMock(),
    )

    assert app.id is None
    assert app.user_id == user.id
    assert app.tenant_id == user.tenant_id
    assert app.space_id == space.id
    assert app.name == name
    assert app.description is None
    assert app.prompt is None
    assert app.completion_model is not None
    assert app.completion_model_kwargs is None
    assert app.input_fields == [InputField(type=InputFieldType.TEXT_FIELD)]
    assert app.attachments == []


def test_create_app_from_template(factory: AppFactory):
    space = MagicMock()
    completion_model = MagicMock()
    input_fields = MagicMock()
    prompt = MagicMock()
    user = MagicMock()
    template = AppTemplate(
        id="fake-uuid-1234",
        name="Test App Template",
        description="Test App Template Description",
        category="default",
        prompt_text="Test App Prompt",
        completion_model={},
        completion_model_kwargs={},
        wizard={},
        created_at=datetime.now(),
        updated_at=datetime.now(),
        input_description=None,
        input_type="text",
        organization="default",
    )
    app = factory.create_app_from_template(
        user=user,
        template=template,
        space=space,
        completion_model=completion_model,
        input_fields=input_fields,
        prompt=prompt,
        attachments=[],
    )

    assert app.source_template.id == "fake-uuid-1234"
    assert app.source_template.prompt_text == "Test App Prompt"
