from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.flows.domain.flow_classification_retention_policy import (
    FlowClassificationRetentionPolicy,
)
from eneo.roles.permissions import Permission
from eneo.settings.settings import (
    AIBuilderBudgetSettingsPublic,
    AIBuilderBudgetSettingsUpdate,
    FlowClassificationRetentionPolicyUpdate,
    FlowDocumentRenderLimitsPublic,
    FlowDocumentRenderLimitsUpdate,
    FlowEvidencePolicyPublic,
    FlowEvidencePolicyUpdate,
    FlowInputLimitsPublic,
    FlowInputLimitsUpdate,
    FlowRetentionEffectiveStatePublic,
    FlowRetentionPolicyPublic,
    FlowRetentionPolicyUpdate,
    FlowRuntimePolicyPublic,
    FlowRuntimePolicyUpdate,
)
from eneo.settings.settings_router import (
    delete_flow_classification_retention_policy,
    get_ai_builder_budget_settings,
    get_flow_document_render_limits,
    get_flow_evidence_policy,
    get_flow_input_limits,
    get_flow_retention_policy,
    get_flow_runtime_policy,
    list_flow_classification_retention_policies,
    put_flow_classification_retention_policy,
    update_ai_builder_budget_settings,
    update_flow_document_render_limits,
    update_flow_evidence_policy,
    update_flow_input_limits,
    update_flow_retention_policy,
    update_flow_runtime_policy,
)


@pytest.mark.asyncio
async def test_get_flow_input_limits_delegates_to_service() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.get_flow_input_limits.return_value = FlowInputLimitsPublic(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
        max_files_per_run=None,
        audio_max_files_per_run=10,
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    response = await get_flow_input_limits(container=container)

    assert response.file_max_size_bytes == 10_000_000
    assert response.audio_max_size_bytes == 25_000_000
    assert response.max_files_per_run is None
    assert response.audio_max_files_per_run == 10
    service.get_flow_input_limits.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_patch_flow_input_limits_delegates_to_service() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.update_flow_input_limits.return_value = FlowInputLimitsPublic(
        file_max_size_bytes=11_000_000,
        audio_max_size_bytes=26_000_000,
        max_files_per_run=None,
        audio_max_files_per_run=10,
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    payload = FlowInputLimitsUpdate(audio_max_size_bytes=26_000_000)
    response = await update_flow_input_limits(payload=payload, container=container)

    assert response.audio_max_size_bytes == 26_000_000
    service.update_flow_input_limits.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_get_includes_file_count_fields() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.get_flow_input_limits.return_value = FlowInputLimitsPublic(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
        max_files_per_run=50,
        audio_max_files_per_run=20,
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    response = await get_flow_input_limits(container=container)

    assert response.max_files_per_run == 50
    assert response.audio_max_files_per_run == 20


@pytest.mark.asyncio
async def test_patch_with_file_count_fields() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.update_flow_input_limits.return_value = FlowInputLimitsPublic(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
        max_files_per_run=100,
        audio_max_files_per_run=30,
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    payload = FlowInputLimitsUpdate(max_files_per_run=100, audio_max_files_per_run=30)
    response = await update_flow_input_limits(payload=payload, container=container)

    assert response.max_files_per_run == 100
    assert response.audio_max_files_per_run == 30
    service.update_flow_input_limits.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_get_flow_document_render_limits_delegates_to_service() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.get_flow_document_render_limits.return_value = (
        FlowDocumentRenderLimitsPublic(
            max_source_chars=500_000,
            max_blocks=2_000,
            max_text_chars=500_000,
            max_table_rows=5_000,
            max_table_columns=50,
            max_table_cells=50_000,
            max_cell_chars=20_000,
            max_list_items=5_000,
            max_structured_nodes=10_000,
            max_structured_depth=32,
            max_object_fields=200,
        )
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    response = await get_flow_document_render_limits(container=container)

    assert response.max_source_chars == 500_000
    service.get_flow_document_render_limits.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_patch_flow_document_render_limits_delegates_to_service() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.update_flow_document_render_limits.return_value = (
        FlowDocumentRenderLimitsPublic(
            max_source_chars=800_000,
            max_blocks=2_000,
            max_text_chars=500_000,
            max_table_rows=5_000,
            max_table_columns=50,
            max_table_cells=50_000,
            max_cell_chars=20_000,
            max_list_items=5_000,
            max_structured_nodes=10_000,
            max_structured_depth=32,
            max_object_fields=200,
        )
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    payload = FlowDocumentRenderLimitsUpdate(max_source_chars=800_000)
    response = await update_flow_document_render_limits(
        payload=payload, container=container
    )

    assert response.max_source_chars == 800_000
    service.update_flow_document_render_limits.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_get_flow_runtime_policy_delegates_to_service() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.get_flow_runtime_policy.return_value = FlowRuntimePolicyPublic(
        default_step_timeout_seconds=900,
        max_step_timeout_seconds=1800,
        hard_ceiling_seconds=3540,
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    response = await get_flow_runtime_policy(container=container)

    assert response.default_step_timeout_seconds == 900
    assert response.max_step_timeout_seconds == 1800
    service.get_flow_runtime_policy.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_patch_flow_runtime_policy_delegates_to_service() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.update_flow_runtime_policy.return_value = FlowRuntimePolicyPublic(
        default_step_timeout_seconds=1200,
        max_step_timeout_seconds=2400,
        hard_ceiling_seconds=3540,
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    payload = FlowRuntimePolicyUpdate(default_step_timeout_seconds=1200)
    response = await update_flow_runtime_policy(payload=payload, container=container)

    assert response.default_step_timeout_seconds == 1200
    service.update_flow_runtime_policy.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_get_ai_builder_budget_settings_delegates_to_service() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.get_ai_builder_budget_settings.return_value = AIBuilderBudgetSettingsPublic(
        conversation_safety_buffer_tokens=1500,
        minimum_conversation_budget_tokens=6000,
        unknown_model_context_window_tokens=None,
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    response = await get_ai_builder_budget_settings(container=container)

    assert response.conversation_safety_buffer_tokens == 1500
    assert response.minimum_conversation_budget_tokens == 6000
    service.get_ai_builder_budget_settings.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_patch_ai_builder_budget_settings_delegates_to_service() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.update_ai_builder_budget_settings.return_value = (
        AIBuilderBudgetSettingsPublic(
            conversation_safety_buffer_tokens=1800,
            minimum_conversation_budget_tokens=5000,
            unknown_model_context_window_tokens=256000,
        )
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    payload = AIBuilderBudgetSettingsUpdate(
        conversation_safety_buffer_tokens=1800,
        unknown_model_context_window_tokens=256000,
    )
    response = await update_ai_builder_budget_settings(
        payload=payload, container=container
    )

    assert response.unknown_model_context_window_tokens == 256000
    service.update_ai_builder_budget_settings.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_get_flow_evidence_policy_delegates_to_service() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.get_flow_evidence_policy.return_value = FlowEvidencePolicyPublic(
        allow_sensitive_flow_exports=False,
        allow_space_admin_raw_export_class3=False,
        allow_run_owner_raw_export_class3=True,
        allow_service_key_raw_export_class3=False,
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    response = await get_flow_evidence_policy(container=container)

    assert response.allow_sensitive_flow_exports is False
    assert response.allow_run_owner_raw_export_class3 is True
    service.get_flow_evidence_policy.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_patch_flow_evidence_policy_delegates_to_service() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.update_flow_evidence_policy.return_value = FlowEvidencePolicyPublic(
        allow_sensitive_flow_exports=True,
        allow_space_admin_raw_export_class3=True,
        allow_run_owner_raw_export_class3=False,
        allow_service_key_raw_export_class3=True,
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    payload = FlowEvidencePolicyUpdate(
        allow_sensitive_flow_exports=True,
        allow_service_key_raw_export_class3=True,
    )
    response = await update_flow_evidence_policy(payload=payload, container=container)

    assert response.allow_sensitive_flow_exports is True
    assert response.allow_service_key_raw_export_class3 is True
    service.update_flow_evidence_policy.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_get_flow_retention_policy_delegates_to_service() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.get_flow_retention_policy.return_value = FlowRetentionPolicyPublic(
        run_debug_evidence_days=7,
        flow_run_history_retention_days=None,
        flow_runtime_upload_abandonment_days=None,
        effective_state=FlowRetentionEffectiveStatePublic(
            run_history_deletion_active=False,
            runtime_upload_abandonment_active=False,
            classification_policy_count=0,
        ),
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    response = await get_flow_retention_policy(container=container)

    assert response.run_debug_evidence_days == 7
    service.get_flow_retention_policy.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_patch_flow_retention_policy_delegates_to_service() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.update_flow_retention_policy.return_value = FlowRetentionPolicyPublic(
        run_debug_evidence_days=14,
        flow_run_history_retention_days=None,
        flow_runtime_upload_abandonment_days=None,
        effective_state=FlowRetentionEffectiveStatePublic(
            run_history_deletion_active=False,
            runtime_upload_abandonment_active=False,
            classification_policy_count=0,
        ),
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    payload = FlowRetentionPolicyUpdate(run_debug_evidence_days=14)
    response = await update_flow_retention_policy(payload=payload, container=container)

    assert response.run_debug_evidence_days == 14
    service.update_flow_retention_policy.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_list_flow_classification_retention_policies_delegates_to_flow_service() -> (
    None
):
    classification_id = uuid4()
    container = MagicMock()
    service = AsyncMock()
    service.list_policies.return_value = [
        FlowClassificationRetentionPolicy(
            tenant_id=uuid4(),
            security_classification_id=classification_id,
            data_retention_days=7,
        )
    ]
    container.flow_classification_retention_policy_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    response = await list_flow_classification_retention_policies(container=container)

    assert response.policies[0].security_classification_id == classification_id
    assert response.policies[0].data_retention_days == 7
    service.list_policies.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_put_flow_classification_retention_policy_delegates_to_flow_service() -> (
    None
):
    classification_id = uuid4()
    container = MagicMock()
    service = AsyncMock()
    service.set_policy.return_value = FlowClassificationRetentionPolicy(
        tenant_id=uuid4(),
        security_classification_id=classification_id,
        data_retention_days=14,
    )
    container.flow_classification_retention_policy_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )
    payload = FlowClassificationRetentionPolicyUpdate(data_retention_days=14)

    response = await put_flow_classification_retention_policy(
        security_classification_id=classification_id,
        payload=payload,
        container=container,
    )

    assert response.data_retention_days == 14
    service.set_policy.assert_awaited_once_with(
        security_classification_id=classification_id,
        data_retention_days=14,
        confirmation=None,
    )


@pytest.mark.asyncio
async def test_delete_flow_classification_retention_policy_delegates_to_flow_service() -> (
    None
):
    classification_id = uuid4()
    container = MagicMock()
    service = AsyncMock()
    container.flow_classification_retention_policy_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    response = await delete_flow_classification_retention_policy(
        security_classification_id=classification_id,
        container=container,
    )

    assert response.status_code == 204
    service.delete_policy.assert_awaited_once_with(
        security_classification_id=classification_id
    )
