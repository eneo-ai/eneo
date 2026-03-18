from uuid import uuid4

import pytest

from intric.tenants.tenant import TenantInDB, TenantState


def test_tenant_in_db_normalizes_null_flow_settings():
    tenant = TenantInDB(
        id=uuid4(),
        name="Tenant",
        display_name="Tenant",
        quota_limit=1024**3,
        modules=[],
        api_credentials={},
        federation_config={},
        crawler_settings={},
        api_key_policy={},
        flow_settings=None,
        state=TenantState.ACTIVE,
    )

    assert tenant.flow_settings == {}


def test_tenant_in_db_validates_ai_builder_flow_settings():
    tenant = TenantInDB(
        id=uuid4(),
        name="Tenant",
        display_name="Tenant",
        quota_limit=1024**3,
        modules=[],
        api_credentials={},
        federation_config={},
        crawler_settings={},
        api_key_policy={},
        flow_settings={
            "ai_builder": {
                "conversation_safety_buffer_tokens": 1500,
                "minimum_conversation_budget_tokens": 6000,
            }
        },
        state=TenantState.ACTIVE,
    )

    assert tenant.flow_settings["ai_builder"]["conversation_safety_buffer_tokens"] == 1500


def test_tenant_in_db_rejects_invalid_ai_builder_flow_settings():
    with pytest.raises(ValueError, match="flow_settings.ai_builder"):
        TenantInDB(
            id=uuid4(),
            name="Tenant",
            display_name="Tenant",
            quota_limit=1024**3,
            modules=[],
            api_credentials={},
            federation_config={},
            crawler_settings={},
            api_key_policy={},
            flow_settings={
                "ai_builder": {
                    "conversation_safety_buffer_tokens": "many",
                }
            },
            state=TenantState.ACTIVE,
        )
