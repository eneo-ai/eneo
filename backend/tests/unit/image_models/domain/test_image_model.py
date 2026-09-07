"""The image model entity and its request vocabulary."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import get_args
from unittest.mock import MagicMock
from uuid import uuid4

from eneo.image_models.domain.image_model import (
    AUTO_IMAGE_OPTION,
    IMAGE_QUALITIES,
    IMAGE_SIZES,
    ImageModel,
)
from eneo.image_models.presentation.image_model_models import (
    ImageModelPublic,
    ImageQuality,
    ImageSize,
)


def _db_row(**overrides):
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="gpt-image-1",
        nickname="GPT Image",
        family="openai",
        hosting="usa",
        org=None,
        stability="stable",
        open_source=None,
        description=None,
        hf_link=None,
        is_deprecated=False,
        is_enabled=True,
        is_default=False,
        default_size="1024x1024",
        default_quality="high",
        cost_per_image=Decimal("0.04"),
        security_classification=None,
        tenant_id=uuid4(),
        provider_id=uuid4(),
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _user():
    user = MagicMock()
    user.tenant = MagicMock(security_enabled=False)
    return user


class TestVocabulary:
    def test_auto_is_the_first_option_of_both_lists(self):
        assert IMAGE_SIZES[0] == AUTO_IMAGE_OPTION
        assert IMAGE_QUALITIES[0] == AUTO_IMAGE_OPTION

    def test_api_literals_match_the_domain_vocabulary(self):
        assert set(get_args(ImageSize)) == set(IMAGE_SIZES)
        assert set(get_args(ImageQuality)) == set(IMAGE_QUALITIES)


class TestCreateFromDb:
    def test_maps_columns_without_name_inversion(self):
        row = _db_row()

        model = ImageModel.create_from_db(
            row, _user(), provider_name="OpenAI", provider_type="openai"
        )

        assert model.name == "gpt-image-1"
        assert model.nickname == "GPT Image"
        assert model.default_size == "1024x1024"
        assert model.default_quality == "high"
        assert model.cost_per_image == Decimal("0.04")
        assert model.is_org_enabled is True
        assert model.is_org_default is False
        assert model.open_source is False
        assert model.provider_name == "OpenAI"
        assert model.provider_type == "openai"
        assert model.tenant_id == row.tenant_id
        assert model.provider_id == row.provider_id

    def test_public_dto_carries_defaults_and_cost(self):
        model = ImageModel.create_from_db(_db_row(), _user())

        public = ImageModelPublic.from_domain(model)

        assert public.default_size == "1024x1024"
        assert public.default_quality == "high"
        assert public.cost_per_image == Decimal("0.04")
        assert public.name == "gpt-image-1"
        assert public.nickname == "GPT Image"
