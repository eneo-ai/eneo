from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from intric.settings.settings import FlowInputLimitsPublic, FlowInputLimitsUpdate
from intric.settings.settings_router import get_flow_input_limits, update_flow_input_limits


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
    container.user.return_value = SimpleNamespace(id="u", tenant_id="t")

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
    container.user.return_value = SimpleNamespace(id="u", tenant_id="t")

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
    container.user.return_value = SimpleNamespace(id="u", tenant_id="t")

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
    container.user.return_value = SimpleNamespace(id="u", tenant_id="t")

    payload = FlowInputLimitsUpdate(max_files_per_run=100, audio_max_files_per_run=30)
    response = await update_flow_input_limits(payload=payload, container=container)

    assert response.max_files_per_run == 100
    assert response.audio_max_files_per_run == 30
    service.update_flow_input_limits.assert_awaited_once_with(payload)
