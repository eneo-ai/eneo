from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from eneo.completion_models.domain.completion_model import CompletionModel
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.tenants.tenant import TenantInDB


def _load_model(output_tokens: int | None) -> CompletionModel:
    now = datetime.now(timezone.utc)
    row = CompletionModels(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="custom-deployment",
        nickname="Custom deployment",
        litellm_model_name="openai/custom-deployment",
        tenant_id=uuid4(),
        provider_id=uuid4(),
        max_input_tokens=1_000_000,
        max_output_tokens=output_tokens,
        open_source=False,
        is_deprecated=False,
        is_enabled=True,
        is_default=False,
        vision=False,
        reasoning=False,
        supports_tool_calling=True,
        supports_strict_tool_schema=False,
    )
    return CompletionModel.create_from_db(
        row,
        tenant=TenantInDB.model_construct(id=row.tenant_id, name="Test tenant"),
        provider_type="openai",
    )


def test_unknown_output_limit_is_not_inferred_from_the_context_window() -> None:
    with patch(
        "eneo.model_providers.domain.model_defaults._get_model_cost", return_value={}
    ):
        with pytest.raises(ValueError, match="missing max_output_tokens"):
            _load_model(None)


@pytest.mark.parametrize(
    ("configured_output", "expected_output"), [(None, 128_000), (32_000, 32_000)]
)
def test_model_limits_use_configured_values_or_known_provider_metadata(
    configured_output: int | None, expected_output: int
) -> None:
    with patch(
        "eneo.model_providers.domain.model_defaults._get_model_cost",
        return_value={
            "openai/custom-deployment": {
                "max_input_tokens": 1_000_000,
                "max_output_tokens": 128_000,
            }
        },
    ):
        model = _load_model(configured_output)

    assert model.max_input_tokens == 1_000_000
    assert model.max_output_tokens == expected_output
