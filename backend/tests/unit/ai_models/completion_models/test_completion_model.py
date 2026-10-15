"""The catalogue presentation of a completion model carries the tenant's
reader flag, so the admin page can show which model holds the role."""

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import (
    CompletionModelPublic,
    CompletionModelSecurityStatus,
)
from eneo.completion_models.domain.completion_model import CompletionModel


def _domain_model(*, is_org_reader: bool) -> CompletionModel:
    return CompletionModel(
        user=SimpleNamespace(id=uuid4(), tenant_id=uuid4(), tenant=None),
        id=uuid4(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
        nickname="gpt-4.1",
        name="gpt-4.1",
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
        is_org_reader=is_org_reader,
        reasoning=False,
        provider_type="openai",
    )


@pytest.mark.parametrize(
    "presentation", [CompletionModelPublic, CompletionModelSecurityStatus]
)
@pytest.mark.parametrize("is_org_reader", [True, False])
def test_presentation_carries_the_reader_flag(presentation, is_org_reader):
    public = presentation.from_domain(_domain_model(is_org_reader=is_org_reader))

    assert public.is_org_reader is is_org_reader
