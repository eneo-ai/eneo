from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.flows.flow_settings import FLOW_SETTINGS_UNKNOWN_TOP_LEVEL_FIELD_CODE
from eneo.main.exceptions import BadRequestException
from eneo.tenants.tenant import (
    TenantInDB,
    TenantState,
    TenantUpdate,
    TenantUpdatePublic,
)


def _tenant_with_flow_settings(flow_settings: dict[str, object]) -> TenantInDB:
    return TenantInDB(
        id=uuid4(),
        name="Tenant",
        display_name="Tenant",
        quota_limit=1024**3,
        modules=[],
        api_credentials={},
        federation_config={},
        crawler_settings={},
        api_key_policy={},
        flow_settings=flow_settings,
        state=TenantState.ACTIVE,
    )


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


def test_tenant_in_db_scrubs_unknown_top_level_flow_settings_keys():
    tenant = _tenant_with_flow_settings(
        {
            "evidence_polici": {"allow_sensitive_flow_exports": True},
            "input_limits": {"max_files_per_run": 12},
        }
    )

    assert "evidence_polici" not in tenant.flow_settings
    assert tenant.flow_settings["input_limits"] == {"max_files_per_run": 12}


def test_tenant_update_rejects_unknown_top_level_flow_settings_keys():
    with pytest.raises(BadRequestException) as exc_info:
        TenantUpdate(
            id=uuid4(),
            flow_settings={"evidence_polici": {"allow_sensitive_flow_exports": True}},
        )

    assert exc_info.value.code == FLOW_SETTINGS_UNKNOWN_TOP_LEVEL_FIELD_CODE


def test_tenant_update_keeps_internal_flow_settings_write_contract():
    update = TenantUpdate(
        id=uuid4(),
        flow_settings={"input_limits": {"max_files_per_run": 12}},
    )

    assert update.flow_settings == {"input_limits": {"max_files_per_run": 12}}


def test_tenant_update_validates_known_flow_settings_policy_payloads():
    with pytest.raises(BadRequestException) as exc_info:
        TenantUpdate(
            id=uuid4(),
            flow_settings={"retention_policy": {"run_debug_evidence_days": "many"}},
        )

    assert exc_info.value.code == "flow_settings_invalid_payload"


def test_tenant_update_public_does_not_accept_raw_flow_settings():
    assert "flow_settings" not in TenantUpdatePublic.model_fields

    with pytest.raises(ValidationError):
        TenantUpdatePublic.model_validate({"flow_settings": {"input_limits": {}}})


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
                "max_attachments": 37,
                "max_message_chars": 12_000,
                "max_template_inspection_uncompressed_bytes": 64 * 1024 * 1024,
                "max_template_placeholders": 750,
            }
        },
        state=TenantState.ACTIVE,
    )

    assert (
        tenant.flow_settings["ai_builder"]["conversation_safety_buffer_tokens"] == 1500
    )
    assert tenant.flow_settings["ai_builder"]["max_attachments"] == 37
    assert tenant.flow_settings["ai_builder"]["max_template_placeholders"] == 750


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


def test_tenant_in_db_propagates_unexpected_ai_builder_validator_error(
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_validation(_value: object) -> dict[str, object]:
        raise RuntimeError("ai builder validator failed")

    monkeypatch.setattr(
        "eneo.flows.flow_settings.validate_ai_builder_budget_settings_object",
        fail_validation,
    )

    with pytest.raises(RuntimeError, match="ai builder validator failed"):
        _tenant_with_flow_settings(
            {"ai_builder": {"conversation_safety_buffer_tokens": 1500}}
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


def test_tenant_in_db_rejects_unknown_flow_input_limit_key():
    with pytest.raises(
        ValueError,
        match="flow_settings.input_limits contains unknown fields",
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
                "input_limits": {
                    "file_max_size_bytes": 20_000_000,
                    "typo": 1,
                }
            },
            state=TenantState.ACTIVE,
        )


def test_tenant_in_db_validates_retention_policy_flow_settings():
    tenant = _tenant_with_flow_settings(
        {
            "retention_policy": {
                "run_debug_evidence_days": 14,
            }
        }
    )

    assert tenant.flow_settings["retention_policy"]["run_debug_evidence_days"] == 14


def test_tenant_in_db_rejects_invalid_retention_policy_flow_settings():
    with pytest.raises(ValueError, match="run_debug_evidence_days"):
        _tenant_with_flow_settings(
            {
                "retention_policy": {
                    "run_debug_evidence_days": "many",
                }
            }
        )


def test_tenant_in_db_scrubs_deleted_retention_policy_keys():
    tenant = _tenant_with_flow_settings(
        {
            "retention_policy": {
                "source_audio_days": 3,
                "generated_artifact_days": 7,
                "run_debug_evidence_days": 14,
            }
        }
    )

    assert tenant.flow_settings["retention_policy"] == {"run_debug_evidence_days": 14}


def test_tenant_in_db_rejects_unknown_retention_policy_key():
    with pytest.raises(
        ValueError,
        match="flow_settings.retention_policy contains unknown fields: unexpected_days",
    ):
        _tenant_with_flow_settings(
            {
                "retention_policy": {
                    "unexpected_days": 3,
                }
            }
        )


def test_tenant_in_db_propagates_unexpected_retention_policy_validator_error(
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_validation(_value: object) -> dict[str, object]:
        raise RuntimeError("retention policy validator failed")

    monkeypatch.setattr(
        "eneo.flows.flow_settings.validate_flow_retention_policy_object",
        fail_validation,
    )

    with pytest.raises(RuntimeError, match="retention policy validator failed"):
        _tenant_with_flow_settings(
            {"retention_policy": {"run_debug_evidence_days": 14}}
        )


def test_tenant_in_db_validates_document_render_limit_settings():
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
            "document_render_limits": {
                "max_source_chars": 750_000,
                "max_table_cells": 75_000,
            }
        },
        state=TenantState.ACTIVE,
    )

    assert tenant.flow_settings["document_render_limits"]["max_source_chars"] == 750_000


def test_tenant_in_db_rejects_invalid_document_render_limit_settings():
    with pytest.raises(ValueError, match="max_source_chars"):
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
                "document_render_limits": {
                    "max_source_chars": "many",
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
                "allow_sensitive_flow_exports": True,
                "classification_3": {
                    "allow_space_admin_raw_export": True,
                    "allow_run_owner_raw_export": False,
                    "allow_service_key_raw_export": True,
                },
            }
        },
        state=TenantState.ACTIVE,
    )

    assert (
        tenant.flow_settings["evidence_policy"]["allow_sensitive_flow_exports"] is True
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


def test_tenant_in_db_rejects_invalid_flow_evidence_policy_sensitive_flag():
    with pytest.raises(
        ValueError, match="flow_settings.evidence_policy.allow_sensitive_flow_exports"
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
                    "allow_sensitive_flow_exports": "yes",
                }
            },
            state=TenantState.ACTIVE,
        )


def test_tenant_in_db_rejects_unknown_flow_evidence_policy_key():
    with pytest.raises(
        ValueError, match="flow_settings.evidence_policy contains unknown fields"
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
                    "unknown": True,
                }
            },
            state=TenantState.ACTIVE,
        )


def test_tenant_in_db_validates_flow_runtime_policy_settings():
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
            "runtime_policy": {
                "default_step_timeout_seconds": 1200,
                "max_step_timeout_seconds": 2400,
            }
        },
        state=TenantState.ACTIVE,
    )

    assert (
        tenant.flow_settings["runtime_policy"]["default_step_timeout_seconds"] == 1200
    )


def test_tenant_in_db_validates_versioned_flow_runtime_policy_settings():
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
            "runtime_policy": {
                "version": 1,
                "default_step_timeout_seconds": 1200,
                "max_step_timeout_seconds": 2400,
            }
        },
        state=TenantState.ACTIVE,
    )

    assert tenant.flow_settings["runtime_policy"] == {
        "version": 1,
        "default_step_timeout_seconds": 1200,
        "max_step_timeout_seconds": 2400,
    }


def test_tenant_in_db_rejects_invalid_flow_runtime_policy_settings():
    with pytest.raises(ValueError, match="default_step_timeout_seconds"):
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
                "runtime_policy": {
                    "default_step_timeout_seconds": "long",
                }
            },
            state=TenantState.ACTIVE,
        )


def test_tenant_in_db_rejects_unsupported_flow_runtime_policy_version():
    with pytest.raises(ValueError, match="flow_settings.runtime_policy.version"):
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
                "runtime_policy": {
                    "version": 2,
                    "default_step_timeout_seconds": 1200,
                }
            },
            state=TenantState.ACTIVE,
        )
