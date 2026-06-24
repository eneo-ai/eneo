"""Tests for org-controlled model pricing visibility.

The presentation assembler must drop input/output prices when the tenant has
opted out of showing pricing to users, and keep them otherwise.
"""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from intric.ai_models.completion_models.completion_model import (
    CompletionModelPublic,
    CompletionModelSecurityStatus,
)
from intric.completion_models.domain.completion_model import CompletionModel
from intric.completion_models.presentation.completion_model_assembler import (
    CompletionModelAssembler,
)


class MockUser:
    def __init__(self):
        self.id = uuid4()
        self.tenant_id = uuid4()
        self.tenant = None
        self.modules = []


def _make_model():
    return CompletionModel(
        user=MockUser(),
        id=uuid4(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
        nickname="gpt-4o",
        name="gpt-4o",
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
        is_deprecated=False,
        deployment_name=None,
        is_org_enabled=True,
        is_org_default=False,
        reasoning=False,
        provider_type="openai",
        input_cost_per_token=Decimal("0.000005"),
        output_cost_per_token=Decimal("0.000015"),
    )


def test_pricing_kept_when_visible():
    assembler = CompletionModelAssembler()
    public = assembler.from_completion_model_to_model(_make_model(), show_pricing=True)

    assert public.input_cost_per_token == Decimal("0.000005")
    assert public.output_cost_per_token == Decimal("0.000015")


def test_pricing_hidden_when_not_visible():
    assembler = CompletionModelAssembler()
    public = assembler.from_completion_model_to_model(_make_model(), show_pricing=False)

    assert public.input_cost_per_token is None
    assert public.output_cost_per_token is None


def test_pricing_visible_by_default():
    assembler = CompletionModelAssembler()
    public = assembler.from_completion_model_to_model(_make_model())

    assert public.input_cost_per_token == Decimal("0.000005")
    assert public.output_cost_per_token == Decimal("0.000015")


def test_domain_projection_hides_pricing_when_not_visible():
    public = CompletionModelPublic.from_domain(_make_model(), show_pricing=False)

    assert public.input_cost_per_token is None
    assert public.output_cost_per_token is None


def test_security_status_projection_hides_pricing_when_not_visible():
    public = CompletionModelSecurityStatus.from_domain(
        _make_model(), show_pricing=False
    )

    assert public.input_cost_per_token is None
    assert public.output_cost_per_token is None
