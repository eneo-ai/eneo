from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.apps.apps.api.app_models import InputField, InputFieldType
from eneo.apps.apps.app_factory import AppFactory
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.app_table import Apps
from eneo.database.tables.model_providers_table import ModelProviders
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
    # The factory always materialises ModelKwargs(); leaking None into the
    # domain crashes the AppPublic response and the repo .model_dump path.
    assert app.completion_model_kwargs == ModelKwargs()
    assert app.input_fields == [InputField(type=InputFieldType.TEXT_FIELD)]
    assert app.attachments == []


def test_create_model_kwargs_coerces_none_to_default(factory: AppFactory):
    """`_create_model_kwargs(None)` must return ModelKwargs(), not None.

    A DB row or template with NULL `completion_model_kwargs` must not
    leak `None` into the App domain object, where it would crash the
    AppPublic API response (non-Optional ModelKwargs field) and the
    repository's `.model_dump()` write path.
    """
    assert factory._create_model_kwargs(None) == ModelKwargs()


def test_create_model_kwargs_preserves_provided_values(factory: AppFactory):
    """Non-None inputs flow through unchanged."""
    result = factory._create_model_kwargs({"temperature": 0.7})

    assert result.temperature == 0.7


@pytest.mark.parametrize("bad_value", [[], "not a dict", 42, [1, 2, 3]])
def test_create_model_kwargs_rejects_non_dict_jsonb(factory: AppFactory, bad_value):
    """A corrupt non-dict JSONB value must raise ValidationError so the
    per-row isolation belt in space_factory._build_or_skip can catch it.
    A manual `.get(...)` walk would raise AttributeError instead, which
    bypasses that belt and takes down the whole space load.
    """
    with pytest.raises(ValidationError):
        factory._create_model_kwargs(bad_value)


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


def test_create_app_from_db_preserves_completion_model_provider_type(
    factory: AppFactory,
):
    now = datetime.now(timezone.utc)
    tenant_id = uuid4()
    provider = ModelProviders(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        tenant_id=tenant_id,
        name="Self-hosted vLLM",
        provider_type="vllm",
        credentials={},
        config={},
        is_active=True,
    )
    completion_model = CompletionModels(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="meta-llama/Llama-3.1-70B-Instruct",
        nickname="Llama 3.1",
        open_source=True,
        max_input_tokens=128000,
        max_output_tokens=4096,
        is_deprecated=False,
        nr_billion_parameters=70,
        hf_link=None,
        family="llama",
        stability="stable",
        hosting="self-hosted",
        description=None,
        deployment_name=None,
        org=None,
        vision=False,
        reasoning=False,
        supports_tool_calling=True,
        base_url=None,
        litellm_model_name=None,
        model_kwargs_capabilities=None,
        tenant_id=tenant_id,
        provider_id=provider.id,
        is_enabled=True,
        is_default=False,
        security_classification_id=None,
    )
    completion_model.provider = provider
    app_record = Apps(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        tenant_id=tenant_id,
        user_id=uuid4(),
        space_id=uuid4(),
        name="Provider app",
        description=None,
        completion_model_kwargs=None,
        published=False,
        data_retention_days=None,
        template_id=None,
        completion_model_id=completion_model.id,
        transcription_model_id=None,
        icon_id=None,
    )
    app_record.completion_model = completion_model
    app_record.input_fields = []
    app_record.attachments = []
    app_record.template = None

    app = factory.create_app_from_db(app_record)

    assert app.completion_model is not None
    assert app.completion_model.provider_type == "vllm"
    assert app.completion_model.supported_model_kwargs.top_p.supported is True
