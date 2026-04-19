from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from intric.roles.permissions import Permission
from intric.settings.settings import (
    AIBuilderBudgetSettingsPublic,
    AIBuilderBudgetSettingsUpdate,
    FlowEvidencePolicyPublic,
    FlowEvidencePolicyUpdate,
    FlowInputLimitsPublic,
    FlowInputLimitsUpdate,
    FlowRetentionPolicyPublic,
    FlowRetentionPolicyUpdate,
)
from intric.settings.settings_router import (
    get_ai_builder_budget_settings,
    get_flow_evidence_policy,
    get_flow_input_limits,
    get_flow_retention_policy,
    update_ai_builder_budget_settings,
    update_flow_evidence_policy,
    update_flow_input_limits,
    update_flow_retention_policy,
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
        allow_space_admin_raw_export_class3=False,
        allow_run_owner_raw_export_class3=True,
        allow_service_key_raw_export_class3=False,
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    response = await get_flow_evidence_policy(container=container)

    assert response.allow_run_owner_raw_export_class3 is True
    service.get_flow_evidence_policy.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_patch_flow_evidence_policy_delegates_to_service() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.update_flow_evidence_policy.return_value = FlowEvidencePolicyPublic(
        allow_space_admin_raw_export_class3=True,
        allow_run_owner_raw_export_class3=False,
        allow_service_key_raw_export_class3=True,
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    payload = FlowEvidencePolicyUpdate(allow_service_key_raw_export_class3=True)
    response = await update_flow_evidence_policy(payload=payload, container=container)

    assert response.allow_service_key_raw_export_class3 is True
    service.update_flow_evidence_policy.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_get_flow_retention_policy_delegates_to_service() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.get_flow_retention_policy.return_value = FlowRetentionPolicyPublic(
        shared_default_days=30,
        source_audio_days=3,
        transcript_text_days=7,
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    response = await get_flow_retention_policy(container=container)

    assert response.shared_default_days == 30
    service.get_flow_retention_policy.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_patch_flow_retention_policy_delegates_to_service() -> None:
    container = MagicMock()
    service = AsyncMock()
    service.update_flow_retention_policy.return_value = FlowRetentionPolicyPublic(
        shared_default_days=30,
        source_audio_days=3,
        run_debug_evidence_days=14,
    )
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )

    payload = FlowRetentionPolicyUpdate(
        shared_default_days=30,
        source_audio_days=3,
    )
    response = await update_flow_retention_policy(payload=payload, container=container)

    assert response.source_audio_days == 3
    service.update_flow_retention_policy.assert_awaited_once_with(payload)
