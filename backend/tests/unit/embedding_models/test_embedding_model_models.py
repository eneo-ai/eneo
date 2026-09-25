from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from eneo.embedding_models.domain.embedding_model import EmbeddingModel
from eneo.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelPublic,
)


class MockUser:
    def __init__(self):
        self.id = uuid4()
        self.tenant_id = uuid4()
        self.tenant = None


def test_public_embedding_model_keeps_batch_size_in_json():
    model = EmbeddingModel(
        id=uuid4(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
        user=MockUser(),
        nickname="E5 Large",
        name="multilingual-e5-large",
        family="openai",
        hosting="eu",
        org="Berget",
        stability="stable",
        open_source=False,
        description=None,
        hf_link=None,
        is_deprecated=False,
        is_org_enabled=True,
        max_input=8191,
        dimensions=1024,
        security_classification=None,
        max_batch_size=64,
        provider_name="Berget",
    )

    with patch("litellm.model_cost", {}):
        response = EmbeddingModelPublic.from_domain(model).model_dump(mode="json")

    assert response["max_batch_size"] == 64
    assert response["nickname"] == "E5 Large"
    assert response["provider_name"] == "Berget"
