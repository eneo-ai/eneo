from datetime import datetime
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.spaces.api.space_models import TemplateCreate
from eneo.templates.assistant_template.api.assistant_template_models import (
    AssistantTemplateWizard,
)
from eneo.templates.assistant_template.assistant_template import AssistantTemplate

template1 = AssistantTemplate(
    id=uuid4(),
    name="Test Template",
    description="Test Description",
    category="default",
    prompt_text="Test Prompt",
    completion_model={},
    completion_model_kwargs={},
    wizard=AssistantTemplateWizard(
        **{
            "attachments": None,
            "collections": None,
        }
    ),
    created_at=datetime.now(),
    updated_at=datetime.now(),
    organization="default",
)

template2 = AssistantTemplate(
    id=uuid4(),
    name="Test Template",
    description="Test Description",
    category="default",
    prompt_text="Test Prompt",
    completion_model={},
    completion_model_kwargs={},
    wizard=AssistantTemplateWizard(
        **{
            "attachments": {"required": True},
            "collections": None,
        }
    ),
    created_at=datetime.now(),
    updated_at=datetime.now(),
    organization="default",
)

template3 = AssistantTemplate(
    id=uuid4(),
    name="Test Template",
    description="Test Description",
    category="default",
    prompt_text="Test Prompt",
    completion_model={},
    completion_model_kwargs={},
    wizard=AssistantTemplateWizard(
        **{
            "attachments": None,
            "collections": {"required": True},
        }
    ),
    created_at=datetime.now(),
    updated_at=datetime.now(),
    organization="not default",
)


async def test_assistant_template_invalid_wizard_data():
    template_data = {
        "id": "c71fcd07-c984-4b51-9066-7aa0803a3104",
        "additional_fields": [
            {
                "type": "groups",
                "value": [{"id": "36f9473d-77da-45ae-a36a-4461f02642ca"}],
            }
        ],
    }
    data = TemplateCreate(**template_data)

    with pytest.raises(
        BadRequestException, match="Unexpected groups data when creating assistant"
    ):
        template1.validate_assistant_wizard_data(template_data=data)

    template_data2 = {
        "id": "c71fcd07-c984-4b51-9066-7aa0803a3104",
        "additional_fields": [
            {
                "type": "attachments",
                "value": [{"id": "36f9473d-77da-45ae-a36a-4461f02642ca"}],
            }
        ],
    }
    data = TemplateCreate(**template_data2)

    with pytest.raises(
        BadRequestException, match="Unexpected attachments data when creating assistant"
    ):
        template3.validate_assistant_wizard_data(template_data=data)


async def test_assistant_template_valid_wizard_data():
    template_data = {
        "id": "c71fcd07-c984-4b51-9066-7aa0803a3104",
        "additional_fields": [
            {
                "type": "groups",
                "value": [{"id": "36f9473d-77da-45ae-a36a-4461f02642ca"}],
            }
        ],
    }
    data = TemplateCreate(**template_data)
    template3.validate_assistant_wizard_data(template_data=data)

    template_data2 = {
        "id": "c71fcd07-c984-4b51-9066-7aa0803a3104",
        "additional_fields": [
            {
                "type": "attachments",
                "value": [{"id": "36f9473d-77da-45ae-a36a-4461f02642ca"}],
            }
        ],
    }
    data = TemplateCreate(**template_data2)
    template2.validate_assistant_wizard_data(template_data=data)


async def test_organization():
    assert template1.is_from_eneo()
    assert not template3.is_from_eneo()
