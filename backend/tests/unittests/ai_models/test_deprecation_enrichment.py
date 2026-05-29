"""
Tests for deprecation_date enrichment in model Public schemas.

Verifies that CompletionModelPublic, EmbeddingModelPublic, and
TranscriptionModelPublic correctly populate deprecation_date and
override is_deprecated based on LiteLLM's model_cost data.
"""

from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from intric.ai_models.completion_models.completion_model import CompletionModelPublic
from intric.completion_models.domain.completion_model import CompletionModel
from intric.completion_models.presentation.completion_model_assembler import (
    CompletionModelAssembler,
)
from intric.embedding_models.domain.embedding_model import EmbeddingModel
from intric.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelPublic,
)
from intric.transcription_models.domain.transcription_model import TranscriptionModel
from intric.transcription_models.presentation.transcription_model_models import (
    TranscriptionModelPublic,
)


class MockUser:
    def __init__(self):
        self.id = uuid4()
        self.tenant_id = uuid4()
        self.tenant = None
        self.modules = []


MOCK_MODEL_COST = {
    "openai/gpt-4-0613": {
        "litellm_provider": "openai",
        "deprecation_date": "2025-06-13",
    },
    "openai/gpt-4o": {
        "litellm_provider": "openai",
    },
    "openai/text-embedding-3-small": {
        "litellm_provider": "openai",
        "deprecation_date": "2025-06-01",
    },
    "openai/whisper-1": {
        "litellm_provider": "openai",
        "deprecation_date": "2025-09-01",
    },
}


def _make_completion_model(name="gpt-4o", provider_type="openai", is_deprecated=False):
    user = MockUser()
    return CompletionModel(
        user=user,
        id=uuid4(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
        nickname=name,
        name=name,
        max_input_tokens=128000,
        max_output_tokens=4096,
        vision=False,
        family="openai",
        hosting="usa",
        org="OpenAI",
        stability="stable",
        open_source=False,
        description=None,
        nr_billion_parameters=None,
        hf_link=None,
        is_deprecated=is_deprecated,
        deployment_name=None,
        is_org_enabled=True,
        is_org_default=False,
        reasoning=False,
        provider_type=provider_type,
    )


def _make_embedding_model(name="text-embedding-3-small", provider_type="openai"):
    user = MockUser()
    return EmbeddingModel(
        user=user,
        id=uuid4(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
        nickname=name,
        name=name,
        family="openai",
        hosting="usa",
        org="OpenAI",
        stability="stable",
        open_source=False,
        description=None,
        hf_link=None,
        is_deprecated=False,
        is_org_enabled=True,
        max_input=8191,
        dimensions=1536,
        security_classification=None,
        provider_type=provider_type,
    )


def _make_transcription_model(name="whisper-1", provider_type="openai"):
    user = MockUser()
    return TranscriptionModel(
        user=user,
        id=uuid4(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
        nickname=name,
        name=name,
        family="openai",
        hosting="usa",
        org="OpenAI",
        stability="stable",
        open_source=False,
        description=None,
        hf_link=None,
        base_url="",
        is_deprecated=False,
        is_org_enabled=True,
        is_org_default=False,
        provider_type=provider_type,
    )


class TestCompletionModelPublicDeprecation:
    def test_from_domain_sets_deprecation_date(self):
        """from_domain should populate deprecation_date from litellm."""
        model = _make_completion_model(name="gpt-4-0613", provider_type="openai")

        with patch("litellm.model_cost", MOCK_MODEL_COST):
            public = CompletionModelPublic.from_domain(model)

        assert public.deprecation_date == "2025-06-13"
        assert public.is_deprecated is True
        assert public.can_access is False

    def test_from_domain_no_deprecation_date(self):
        """from_domain should leave deprecation_date as None when not in litellm."""
        model = _make_completion_model(name="gpt-4o", provider_type="openai")

        with patch("litellm.model_cost", MOCK_MODEL_COST):
            public = CompletionModelPublic.from_domain(model)

        assert public.deprecation_date is None
        assert public.is_deprecated is False

    def test_from_domain_preserves_manual_deprecation(self):
        """If model is manually deprecated in DB, it stays deprecated even without litellm date."""
        model = _make_completion_model(
            name="gpt-4o", provider_type="openai", is_deprecated=True
        )

        with patch("litellm.model_cost", MOCK_MODEL_COST):
            public = CompletionModelPublic.from_domain(model)

        assert public.is_deprecated is True
        assert public.deprecation_date is None

    def test_from_domain_unknown_model(self):
        """Models not in litellm.model_cost should get None deprecation_date."""
        model = _make_completion_model(name="custom-model", provider_type="hosted_vllm")

        with patch("litellm.model_cost", MOCK_MODEL_COST):
            public = CompletionModelPublic.from_domain(model)

        assert public.deprecation_date is None
        assert public.is_deprecated is False


class TestCompletionModelAssemblerDeprecation:
    def test_assembler_sets_deprecation_date(self):
        """Assembler should populate deprecation_date from litellm."""
        model = _make_completion_model(name="gpt-4-0613", provider_type="openai")
        assembler = CompletionModelAssembler()

        with patch("litellm.model_cost", MOCK_MODEL_COST):
            public = assembler.from_completion_model_to_model(model)

        assert public.deprecation_date == "2025-06-13"
        assert public.is_deprecated is True
        assert public.can_access is False

    def test_assembler_no_deprecation_date(self):
        """Assembler should leave deprecation_date as None when not in litellm."""
        model = _make_completion_model(name="gpt-4o", provider_type="openai")
        assembler = CompletionModelAssembler()

        with patch("litellm.model_cost", MOCK_MODEL_COST):
            public = assembler.from_completion_model_to_model(model)

        assert public.deprecation_date is None
        assert public.is_deprecated is False


class TestEmbeddingModelPublicDeprecation:
    def test_from_domain_sets_deprecation_date(self):
        """EmbeddingModelPublic should populate deprecation_date from litellm."""
        model = _make_embedding_model(
            name="text-embedding-3-small", provider_type="openai"
        )

        with patch("litellm.model_cost", MOCK_MODEL_COST):
            public = EmbeddingModelPublic.from_domain(model)

        assert public.deprecation_date == "2025-06-01"
        assert public.is_deprecated is True
        assert public.can_access is False

    def test_from_domain_no_deprecation_date(self):
        """Should leave deprecation_date as None when model has no date in litellm."""
        model = _make_embedding_model(name="custom-embed", provider_type="hosted_vllm")

        with patch("litellm.model_cost", MOCK_MODEL_COST):
            public = EmbeddingModelPublic.from_domain(model)

        assert public.deprecation_date is None
        assert public.is_deprecated is False


class TestTranscriptionModelPublicDeprecation:
    def test_from_domain_sets_deprecation_date(self):
        """TranscriptionModelPublic should populate deprecation_date from litellm."""
        model = _make_transcription_model(name="whisper-1", provider_type="openai")

        with patch("litellm.model_cost", MOCK_MODEL_COST):
            public = TranscriptionModelPublic.from_domain(model)

        assert public.deprecation_date == "2025-09-01"
        assert public.is_deprecated is True
        assert public.can_access is False

    def test_from_domain_no_deprecation_date(self):
        """Should leave deprecation_date as None when model has no date in litellm."""
        model = _make_transcription_model(
            name="custom-whisper", provider_type="hosted_vllm"
        )

        with patch("litellm.model_cost", MOCK_MODEL_COST):
            public = TranscriptionModelPublic.from_domain(model)

        assert public.deprecation_date is None
        assert public.is_deprecated is False
