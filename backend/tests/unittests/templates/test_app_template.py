from datetime import datetime
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.spaces.api.space_models import TemplateCreate
from eneo.templates.app_template.api.app_template_models import AppTemplateWizard
from eneo.templates.app_template.app_template import AppTemplate

template1 = AppTemplate(
    id=uuid4(),
    name="Test App Template",
    description="Test App Template Description",
    category="default",
    prompt_text="Test App Prompt",
    completion_model={},
    completion_model_kwargs={},
    wizard=AppTemplateWizard(
        **{
            "attachments": None,
            "collections": None,
        }
    ),
    created_at=datetime.now(),
    updated_at=datetime.now(),
    input_description=None,
    input_type="text",
    organization="default",
)

template2 = AppTemplate(
    id=uuid4(),
    name="Test App Template with Required Attachment",
    description="Test App Template with Required Attachment Description",
    category="default",
    prompt_text="Test App Prompt",
    completion_model={},
    completion_model_kwargs={},
    wizard=AppTemplateWizard(
        **{
            "attachments": {"required": True},
            "collections": None,
        }
    ),
    created_at=datetime.now(),
    updated_at=datetime.now(),
    input_description=None,
    input_type="text",
    organization="default",
)


async def test_app_template_invalid_wizard_data():
    template_data = {
        "id": "c71fcd07-c984-4b51-9066-7aa0803a3104",
        "additional_fields": [
            {
                "type": "groups",  # Unsupported type
                "value": [{"id": "36f9473d-77da-45ae-a36a-4461f02642ca"}],
            }
        ],
    }
    data = TemplateCreate(**template_data)

    with pytest.raises(BadRequestException, match="Unsupported type"):
        template1.validate_wizard_data(template_data=data)


async def test_app_template_unexpected_attachments_data():
    template_data = {
        "id": "c71fcd07-c984-4b51-9066-7aa0803a3104",
        "additional_fields": [
            {
                "type": "attachments",
                "value": [{"id": "36f9473d-77da-45ae-a36a-4461f02642ca"}],
            }
        ],
    }
    data = TemplateCreate(**template_data)

    with pytest.raises(
        BadRequestException, match="Unexpected attachments data when creating assistant"
    ):
        template1.validate_wizard_data(template_data=data)


async def test_app_template_valid_attachments_data():
    template_data = {
        "id": "c71fcd07-c984-4b51-9066-7aa0803a3104",
        "additional_fields": [
            {
                "type": "attachments",
                "value": [{"id": "36f9473d-77da-45ae-a36a-4461f02642ca"}],
            }
        ],
    }
    data = TemplateCreate(**template_data)

    template2.validate_wizard_data(template_data=data)


async def test_organization():
    assert template1.is_from_eneo()
    template1.organization = "Other organization"
    assert not template1.is_from_eneo()
