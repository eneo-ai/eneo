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

    assert (
        tenant.flow_settings["ai_builder"]["conversation_safety_buffer_tokens"] == 1500
    )


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


def test_tenant_in_db_validates_flow_input_limit_settings():
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
            "input_limits": {
                "file_max_size_bytes": 20_000_000,
                "audio_max_size_bytes": 50_000_000,
                "max_files_per_run": 50,
                "audio_max_files_per_run": 10,
            }
        },
        state=TenantState.ACTIVE,
    )

    assert tenant.flow_settings["input_limits"]["max_files_per_run"] == 50


def test_tenant_in_db_rejects_flow_input_limits_outside_runtime_bounds():
    with pytest.raises(ValueError, match="audio_max_files_per_run"):
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
                "input_limits": {
                    "audio_max_files_per_run": 101,
                }
            },
            state=TenantState.ACTIVE,
        )


def test_tenant_in_db_validates_flow_evidence_policy_settings():
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
            "evidence_policy": {
                "classification_3": {
                    "allow_space_admin_raw_export": True,
                    "allow_run_owner_raw_export": False,
                    "allow_service_key_raw_export": True,
                }
            }
        },
        state=TenantState.ACTIVE,
    )

    assert (
        tenant.flow_settings["evidence_policy"]["classification_3"][
            "allow_space_admin_raw_export"
        ]
        is True
    )


def test_tenant_in_db_rejects_invalid_flow_evidence_policy_settings():
    with pytest.raises(
        ValueError, match="flow_settings.evidence_policy.classification_3"
    ):
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
                "evidence_policy": {
                    "classification_3": {
                        "allow_space_admin_raw_export": "yes",
                    }
                }
            },
            state=TenantState.ACTIVE,
        )
